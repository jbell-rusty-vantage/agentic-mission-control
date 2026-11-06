"""MO-44 (SPEC-04 §5.3): the Watcher Evaluator over a disposable PostgreSQL 17.

Restricted runtime login, forced RLS, the released common chain. The run is a real admitted
and started run; signals are real Native Event Store frames written through the FrameWriter
with a `signal.<type>` native kind (the IngressDrainer's representation, SPEC-04 §3, stood in
for by this FIXTURE), journal facts are appended through the canonical ledger writer, and
every action goes through the real `MissionControlService` and its command mailbox.

Proves: a firing is one admitted command plus one `watcher.fired` journal event (and outbox
row) keyed by `(watcher_id, trigger_key)`; a replayed pass and a re-recorded firing write
nothing; a pass that died between its command and its record, retried after the run moved,
still instructs once; the coordinator inbox turns a `notify` into one notification of its
kind; another tenant sees none of it; an `event_wait` stage's declared wait is released by its
implied watcher (once) and a `pause` action is applied through real run control; and
descriptors are read from the committed definition snapshot, with manifest start launching the
run's evaluator (and refusing to start without one). Last, on the real local Temporal server,
manifest start launches `mc.watchers.v1` and the worker composition fires a declared watcher
once and never records it again.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any
from uuid import uuid4

import asyncpg
import pytest
from temporalio.client import Client
from temporalio.worker import Worker

from mission_control.adapters.postgres.frames.repository import PostgresFrameRepository
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.adapters.postgres.watchers import PostgresWatcherStore
from mission_control.adapters.temporal.watcher_composition import compose_watcher_activities
from mission_control.adapters.temporal.watcher_starter import TemporalWatcherStarter
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.watchers import WatchersWorkflow
from mission_control.application.authoring.manifest_submit import ManifestStartUnavailable
from mission_control.application.frames.writer import FrameWriter
from mission_control.application.subscriptions.coordinator import NotificationKind
from mission_control.application.watchers.ports import WatcherCursor
from mission_control.application.watchers.service import (
    WATCHER_ACTOR_ID,
    WATCHER_AUTHORITY,
    WatcherEvaluationService,
    WatcherPassRequest,
)
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.frames.contracts import FrameKind
from mission_control.domain.policies.contracts import (
    CommandStatus,
    DomainEventEnvelope,
    SetWaitAction,
)
from mission_control.domain.policies.mailbox import MailboxState
from mission_control.domain.programs.watchers import (
    WatcherDescriptor,
    WatcherSpec,
    compile_watcher,
    wait_condition_id,
)
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.fixtures.provider_frames import observation
from tests.integration.postgres.frames_common import admit_unit_attempt
from tests.integration.postgres.runtime_common import (
    common_db,  # noqa: F401
    scoped_command,
)
from tests.integration.postgres.test_manifest_submit import (
    OWNER,
    Stack,
    goal_loop_manifest,
    request,
)
from tests.integration.postgres.test_mp15_coordinator_inbox_postgres import (
    COORDINATOR,
    append_fixture_events,
    inbox_service,
    mission_service,
    owner_fetch,
    subscribe,
)
from tests.unit.run_control.test_boundary_commands import declared_wait, states
from tests.unit.watchers.fakes import T0
from tests.unit.watchers.test_watcher_manifest import definition, event_wait_document

pytestmark = pytest.mark.common_db

TEMPORAL_ADDRESS = os.environ.get("MC_TEMPORAL_TEST_ADDRESS", "127.0.0.1:7233")
TEMPORAL_NAMESPACE = os.environ.get("MC_TEMPORAL_TEST_NAMESPACE", "default")


def watcher(watcher_id: str, body: dict[str, Any]) -> WatcherDescriptor:
    return compile_watcher(
        WatcherSpec.model_validate(body),
        watcher_id=watcher_id,
        origin="manifest",
        pointer=f"/mission/controls/watchers/{watcher_id}",
    )


CI = watcher(
    "ci-red-fix",
    {
        "on": {
            "signal": "github.check_suite.completed",
            "where": "event.conclusion == 'failure' and "
            "startswith(event.head_branch, run.branch_prefix)",
        },
        "then": [{"instruct": {"text": "CI is red; fix it.", "include": ["event.summary"]}}],
        "limits": {"max_fires": 3},
    },
)
ARTIFACT = watcher(
    "artifact-in",
    {
        "on": {"event": "artifact.admitted"},
        "then": [{"notify": {"kind": "blocked", "text": "review the new artifact"}}],
    },
)


def command_issuer(kind: str) -> str:
    """The idempotency issuer `MissionControlService` binds an evaluator command to."""

    return json.dumps(["mc.command.v1", WATCHER_ACTOR_ID, kind], separators=(",", ":"))


class FixedProgram(PostgresWatcherStore):
    """The PostgreSQL store with the descriptors given here instead of a definition snapshot."""

    def __init__(
        self, pool: asyncpg.Pool, scope: str, descriptors: tuple[WatcherDescriptor, ...]
    ) -> None:
        super().__init__(pool, scope)
        self.fixed = descriptors

    async def descriptors(self, run_id: str) -> tuple[WatcherDescriptor, ...]:
        del run_id
        return self.fixed


async def test_firings_are_admitted_commands_plus_one_journal_record_each_and_never_twice(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool(max_size=6)
    try:
        scope = common_db.scope()
        admitted = await admit_unit_attempt(pool, common_db)
        run_key = admitted.run_key
        frames = PostgresFrameRepository(pool)
        writer = FrameWriter(frames, await frames.open_execution(admitted.start()))
        branch = f"mc/{run_key}/fix"
        await writer.write(
            [
                observation("turn-1", FrameKind.MESSAGE, {"text": "working"}),
                observation(
                    "signal-1",
                    FrameKind.UNKNOWN,
                    {
                        "data": {
                            "conclusion": "failure",
                            "head_branch": branch,
                            "summary": "3 tests failed",
                        },
                        "trust_tier": "provider_signed",
                    },
                    raw_kind="signal.github.check_suite.completed",
                ),
                observation(
                    "signal-2",
                    FrameKind.UNKNOWN,
                    {"data": {"conclusion": "failure", "head_branch": "main"}},
                    raw_kind="signal.github.check_suite.completed",
                ),
            ]
        )
        await append_fixture_events(
            pool, scope, run_key, [("artifact.admitted", {"artifact_ref": "artifact://a/1"})]
        )
        run_uuid = await frames.run_uuid(scope, run_key)
        assert run_uuid is not None
        sid = await subscribe(inbox_service(pool, scope), run_uuid)
        facade, mailbox = mission_service(pool, scope)
        store = FixedProgram(pool, scope, (CI, ARTIFACT))
        service = WatcherEvaluationService(store, facade)

        seen = await store.last_seen(run_key)
        assert {"event", "frame", "signal"} <= set(seen)
        page = await store.observations(run_key, after=WatcherCursor(), limit=100)
        # One batch shares its observation time; frame ids order it deterministically.
        signals = {
            item.data["head_branch"]: item for item in page.observations if item.source == "signal"
        }
        assert [item.types for item in signals.values()] == [("github.check_suite.completed",)] * 2
        assert signals[branch].trust == "provider_signed" and signals["main"].trust is None
        assert signals[branch].data["summary"] == "3 tests failed"

        report = await service.run_pass(
            WatcherPassRequest(run_id=run_key, cursor=WatcherCursor(), armed_at=T0, now=T0)
        )
        outcomes = {item.watcher_id: item for item in report.firings}
        assert set(outcomes) == {"ci-red-fix", "artifact-in"}
        assert outcomes["ci-red-fix"].actions[0].status == "admitted"
        assert outcomes["artifact-in"].actions[0].status == "recorded"
        (entry,) = await mailbox.list_entries(scope, run_key)
        assert entry.state is MailboxState.QUEUED and entry.kind == "queue_instruction"
        rows = await owner_fetch(
            common_db,
            "SELECT e.event_type, e.payload->'payload'->>'watcher_id' AS watcher, o.delivery_key "
            "FROM mission_control.mission_event e JOIN mission_control.outbox o "
            "ON o.event_id = e.event_id WHERE e.event_type LIKE 'watcher.%' ORDER BY e.seq",
        )
        assert [(row["event_type"], row["watcher"]) for row in rows] == [
            ("watcher.fired", "ci-red-fix"),
            ("watcher.fired", "artifact-in"),
        ]
        assert rows[0]["delivery_key"].startswith(f"watcher.fired:{run_key}:ci-red-fix:signal:")
        history = await store.history(run_key)
        assert {(item.watcher_id, item.outcome) for item in history} == {
            ("ci-red-fix", "fired"),
            ("artifact-in", "fired"),
        }

        # The same page again (a retried activity or a lost cursor) issues and records nothing.
        replay = await service.run_pass(
            WatcherPassRequest(run_id=run_key, cursor=WatcherCursor(), armed_at=T0, now=T0)
        )
        assert replay.firings == ()
        assert len(await mailbox.list_entries(scope, run_key)) == 1
        # Recording a firing twice is a no-op keyed by its event id.
        envelope = await recorded_envelope(pool, scope, rows[0]["delivery_key"])
        assert await store.record(run_key, envelope) is False

        # The inbox: the notify watcher is one `blocked` notification with its message.
        page = await inbox_service(pool, scope).poll(sid, COORDINATOR)
        blocked = [item for item in page.notifications if item.kind is NotificationKind.BLOCKED]
        (notification,) = blocked
        assert notification.facts["watcher_id"] == "artifact-in"
        assert notification.facts["message"] == "review the new artifact"

        # Another tenant reads none of the journal, signals or history.
        other = FixedProgram(pool, common_db.scope("tenant-2"), (CI,))
        assert (
            await other.observations(run_key, after=WatcherCursor(), limit=10)
        ).observations == ()
        assert await other.history(run_key) == ()
    finally:
        await pool.close()


async def test_a_signal_uploaded_late_with_an_early_observation_time_is_still_read(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool()
    try:
        scope = common_db.scope()
        admitted = await admit_unit_attempt(pool, common_db)
        frames = PostgresFrameRepository(pool)
        writer = FrameWriter(frames, await frames.open_execution(admitted.start()))
        kind = "signal.github.check_suite.completed"
        await writer.write([observation("live", FrameKind.UNKNOWN, {"data": {}}, raw_kind=kind)])
        store = PostgresWatcherStore(pool, scope)
        first = await store.observations(admitted.run_key, after=WatcherCursor(), limit=100)
        (live,) = [item for item in first.observations if item.source == "signal"]
        # A spooled signal uploaded at Stop keeps the time its producer observed it.
        spooled = observation("spooled", FrameKind.UNKNOWN, {"data": {}}, raw_kind=kind)
        early = live.at - timedelta(hours=1)
        await writer.write([spooled.model_copy(update={"observed_at": early})])
        later = await store.observations(admitted.run_key, after=first.cursor, limit=100)
        (item,) = [item for item in later.observations if item.source == "signal"]
        assert item.at == early and item.ref != live.ref
        again = await store.observations(admitted.run_key, after=later.cursor, limit=100)
        assert [item for item in again.observations if item.source == "signal"] == []
    finally:
        await pool.close()


class DiesBeforeRecord(FixedProgram):
    """The pass dies once after its commands, before its journal record."""

    def __init__(
        self, pool: asyncpg.Pool, scope: str, descriptors: tuple[WatcherDescriptor, ...]
    ) -> None:
        super().__init__(pool, scope, descriptors)
        self.deaths = 1

    async def record(self, run_id: str, event: DomainEventEnvelope) -> bool:
        if self.deaths:
            self.deaths -= 1
            raise ConnectionError("the pass died before its record")
        return await super().record(run_id, event)


async def test_a_pass_that_died_before_its_record_never_instructs_twice(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool(max_size=6)
    try:
        scope = common_db.scope()
        admitted = await admit_unit_attempt(pool, common_db)
        run_key, run_control = admitted.run_key, admitted.run_control
        frames = PostgresFrameRepository(pool)
        writer = FrameWriter(frames, await frames.open_execution(admitted.start()))
        await writer.write(
            [
                observation(
                    "signal-1",
                    FrameKind.UNKNOWN,
                    {
                        "data": {"conclusion": "failure", "head_branch": f"mc/{run_key}/fix"},
                        "trust_tier": "provider_signed",
                    },
                    raw_kind="signal.github.check_suite.completed",
                )
            ]
        )
        facade, mailbox = mission_service(pool, scope)
        store = DiesBeforeRecord(pool, scope, (CI,))
        service = WatcherEvaluationService(store, facade)
        request = WatcherPassRequest(run_id=run_key, cursor=WatcherCursor(), armed_at=T0, now=T0)
        with pytest.raises(ConnectionError):
            await service.run_pass(request)
        assert len(await mailbox.list_entries(scope, run_key)) == 1
        assert await store.history(run_key) == ()

        # The run moves before the activity retry, so the rebuilt request names a new frontier.
        version = (await run_control.get_run(scope, run_key)).version
        moved = await run_control.execute(
            scoped_command(
                common_db,
                run_key,
                version,
                "declare-other-wait",
                SetWaitAction(
                    condition=declared_wait("stagegraph-wait:other"), runnable_work_remains=True
                ),
            )
        )
        assert moved.status == CommandStatus.ACCEPTED

        report = await service.run_pass(request)
        (firing,) = report.firings
        assert (firing.outcome, firing.recorded) == ("fired", True)
        assert (firing.actions[0].status, firing.actions[0].detail) == (
            "replayed",
            "frontier_moved",
        )
        assert len(await mailbox.list_entries(scope, run_key)) == 1
        assert [(item.watcher_id, item.outcome) for item in await store.history(run_key)] == [
            ("ci-red-fix", "fired")
        ]
    finally:
        await pool.close()


async def test_an_event_wait_is_released_and_a_pause_admitted_through_real_run_control(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool(max_size=6)
    try:
        scope = common_db.scope()
        admitted = await admit_unit_attempt(pool, common_db)
        run_key, run_control = admitted.run_key, admitted.run_control
        # The StageGraph declares the `event_wait` stage's wait when it reaches the stage.
        (implied,) = definition(event_wait_document()).policies.watchers
        release_wait = implied.actions[0].satisfy_wait
        assert release_wait is not None
        condition_id = wait_condition_id(release_wait.node)
        version = (await run_control.get_run(scope, run_key)).version
        declared = await run_control.execute(
            scoped_command(
                common_db,
                run_key,
                version,
                "declare-await-merge",
                SetWaitAction(condition=declared_wait(condition_id), runnable_work_remains=True),
            )
        )
        assert declared.status == CommandStatus.ACCEPTED
        waiting = await run_control.get_run(scope, run_key)
        assert [item.condition_id for item in waiting.active_waits] == [condition_id]
        hold = watcher(
            "hold",
            {"on": {"event": "artifact.admitted"}, "then": [{"command": {"kind": "pause"}}]},
        )
        facade, _mailbox = mission_service(pool, scope)
        service = WatcherEvaluationService(FixedProgram(pool, scope, (implied, hold)), facade)
        await append_fixture_events(
            pool,
            scope,
            run_key,
            [("github.pull_request.merged", {"base": "dev", "merged": True})],  # no match
        )
        first = await service.run_pass(
            WatcherPassRequest(run_id=run_key, cursor=WatcherCursor(), armed_at=T0, now=T0)
        )
        assert first.firings == ()

        await append_fixture_events(
            pool,
            scope,
            run_key,
            [
                ("github.pull_request.merged", {"base": "main", "merged": True}),
                ("artifact.admitted", {"artifact_ref": "artifact://a/1"}),
            ],
        )
        report = await service.run_pass(
            WatcherPassRequest(run_id=run_key, cursor=first.cursor, armed_at=T0, now=T0)
        )
        outcomes = {item.watcher_id: item.actions[0] for item in report.firings}
        assert {key: item.status for key, item in outcomes.items()} == {
            "event_wait:await-merge": "admitted",
            "hold": "admitted",
        }
        # No execution target is bound, so run control is the boundary: both are applied. The
        # wait is released and the run holds on the evaluator's pause decision.
        projection = await run_control.get_run(scope, run_key)
        assert projection.active_waits == ()
        assert [item.authority_ref for item in projection.active_pauses] == [WATCHER_AUTHORITY]
        for kind, watcher_id in (("satisfy_wait", "event_wait:await-merge"), ("pause", "hold")):
            delivered = await run_control.get_boundary_command(
                scope, run_key, command_issuer(kind), str(outcomes[watcher_id].request_id)
            )
            assert delivered is not None and states(delivered)[-1] == "applied"

        # The implied watcher fires once: a second matching event finds max_fires spent.
        await append_fixture_events(
            pool,
            scope,
            run_key,
            [("github.pull_request.merged", {"base": "main", "merged": True})],
        )
        again = await service.run_pass(
            WatcherPassRequest(run_id=run_key, cursor=report.cursor, armed_at=T0, now=T0)
        )
        assert again.firings == ()
        assert [(item.watcher_id, item.reason) for item in again.suppressed] == [
            ("event_wait:await-merge", "max_fires")
        ]
    finally:
        await pool.close()


async def test_an_event_before_its_wait_is_declared_is_held_and_released_once_declared(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool(max_size=6)
    try:
        scope = common_db.scope()
        admitted = await admit_unit_attempt(pool, common_db)
        run_key, run_control = admitted.run_key, admitted.run_control
        (implied,) = definition(event_wait_document()).policies.watchers
        facade, _mailbox = mission_service(pool, scope)
        store = FixedProgram(pool, scope, (implied,))
        service = WatcherEvaluationService(store, facade)
        # The pull request merges before the StageGraph reaches the `event_wait` stage.
        await append_fixture_events(
            pool,
            scope,
            run_key,
            [("github.pull_request.merged", {"base": "main", "merged": True})],
        )
        early = await service.run_pass(
            WatcherPassRequest(run_id=run_key, cursor=WatcherCursor(), armed_at=T0, now=T0)
        )
        assert early.firings == () and [item.watcher_id for item in early.held] == [
            implied.watcher_id
        ]
        assert await store.history(run_key) == ()

        condition_id = wait_condition_id("await-merge")
        version = (await run_control.get_run(scope, run_key)).version
        declared = await run_control.execute(
            scoped_command(
                common_db,
                run_key,
                version,
                "declare-await-merge",
                SetWaitAction(condition=declared_wait(condition_id), runnable_work_remains=True),
            )
        )
        assert declared.status == CommandStatus.ACCEPTED
        released = await service.run_pass(
            WatcherPassRequest(
                run_id=run_key, cursor=early.cursor, armed_at=T0, now=T0, held=early.held
            )
        )
        (firing,) = released.firings
        assert (firing.outcome, firing.actions[0].status) == ("fired", "admitted")
        assert released.held == ()
        assert (await run_control.get_run(scope, run_key)).active_waits == ()
        assert [(item.watcher_id, item.outcome) for item in await store.history(run_key)] == [
            (implied.watcher_id, "fired")
        ]
    finally:
        await pool.close()


async def recorded_envelope(
    pool: asyncpg.Pool, scope: str, delivery_key: str
) -> DomainEventEnvelope:
    async with pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        raw = await connection.fetchval(
            f"SELECT payload FROM mission_control.outbox WHERE {mc.SCOPE} AND delivery_key = $4",
            *args,
            delivery_key,
        )
    return DomainEventEnvelope.model_validate(mc.load(raw))


class RecordingStarter:
    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []

    async def start(self, request_scope: str, run_id: str) -> str:
        self.started.append((request_scope, run_id))
        return f"mc/watchers/{run_id}"


STALLED = {
    "id": "stalled",
    "on": {"absence": {"of": ["frame"], "for": "20m"}},
    "then": [{"notify": {"kind": "blocked"}}],
    "limits": {"max_fires": 2},
}


def watched_manifest(*watchers: dict[str, Any]) -> str:
    document = copy.deepcopy(load_manifest_yaml(goal_loop_manifest()))
    document["manifest"] = "mission/v2"
    document["mission"]["controls"]["watchers"] = list(watchers or (STALLED,))
    return canonical_manifest_bytes(document).decode("utf-8")


async def test_start_launches_the_evaluator_that_reads_the_committed_descriptors(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        stack = Stack(common_db, pool)
        service = await stack.build()
        starter = RecordingStarter()
        watched = await stack.build(watchers=starter)
        receipt, _ = await service.submit(request(watched_manifest(), uuid4()))
        (mission,) = receipt.missions
        assert mission.run_id is not None
        # No evaluator composed: a run with watchers is never started without them.
        with pytest.raises(ManifestStartUnavailable, match="no Watcher Evaluator"):
            await service.start(mission.run_id, OWNER)
        assert stack.submitter.calls == []

        started = await watched.start(mission.run_id, OWNER)
        assert starter.started == [(stack.scope, mission.run_id)]
        assert started.watchers_workflow_id == f"mc/watchers/{mission.run_id}"

        store = PostgresWatcherStore(pool, stack.scope)
        (descriptor,) = await store.descriptors(mission.run_id)
        definition = MissionDefinition.model_validate(
            (await stack.submissions.run_subscriptions(stack.scope, mission.run_id))["definition"]
        )
        assert (descriptor,) == definition.policies.watchers
        assert descriptor.watcher_id == "stalled" and descriptor.trigger.seconds == 1200
    finally:
        await pool.close()


class FlakyStarter(RecordingStarter):
    """Fails its first start, as a Temporal hiccup (or a process dying mid-start) would."""

    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    async def start(self, request_scope: str, run_id: str) -> str:
        if not self.failed:
            self.failed = True
            raise ConnectionError("temporal unavailable for a moment")
        return await super().start(request_scope, run_id)


async def test_a_start_whose_evaluator_failed_launches_nothing_and_is_retried_in_full(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    try:
        stack = Stack(common_db, pool)
        starter = FlakyStarter()
        service = await stack.build(watchers=starter)
        receipt, _ = await service.submit(request(watched_manifest(), uuid4()))
        (mission,) = receipt.missions
        assert mission.run_id is not None
        with pytest.raises(ConnectionError):
            await service.start(mission.run_id, OWNER)
        # The evaluator starts first: the run is still pending, so the retry launches it.
        assert stack.submitter.calls == []

        started = await service.start(mission.run_id, OWNER)
        assert starter.started == [(stack.scope, mission.run_id)]
        assert started.watchers_workflow_id == f"mc/watchers/{mission.run_id}"
        assert len(stack.submitter.calls) == 1
    finally:
        await pool.close()


async def eventually[T](
    probe: Callable[[], Awaitable[T]], done: Callable[[T], bool], *, seconds: float = 60
) -> T:
    """The probe's first value that is done, read every half second for at most ``seconds``."""

    for _ in range(int(seconds * 2)):
        value = await probe()
        if done(value):
            return value
        await asyncio.sleep(0.5)
    pytest.fail(f"not done within {seconds} s")


async def local_temporal() -> Client:
    try:
        return await Client.connect(TEMPORAL_ADDRESS, namespace=TEMPORAL_NAMESPACE)
    except RuntimeError as error:
        pytest.fail(f"the real local Temporal server at {TEMPORAL_ADDRESS} is required: {error}")


async def test_manifest_start_runs_the_composed_evaluator_on_the_local_temporal_server(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool("mission_control_runtime")
    client = await local_temporal()
    queue = f"mo44-watchers-{uuid4()}"
    handle = None
    try:
        stack = Stack(common_db, pool)
        service = await stack.build(
            watchers=TemporalWatcherStarter(client, task_queue=queue, poll_seconds=1)
        )
        manifest = watched_manifest(
            {
                "id": "artifact-in",
                "on": {"event": "artifact.admitted"},
                "then": [{"notify": {"kind": "blocked", "text": "review the new artifact"}}],
            }
        )
        receipt, _ = await service.submit(request(manifest, uuid4()))
        (mission,) = receipt.missions
        run_id = mission.run_id
        assert run_id is not None
        activities = compose_watcher_activities(
            pool, run_control=stack.run_control, client=client, request_scopes=[stack.scope]
        )
        async with Worker(
            client,
            task_queue=queue,
            workflows=[WatchersWorkflow],
            activities=[activities.evaluate],
            workflow_runner=coordinator_workflow_runner(),
        ):
            started = await service.start(run_id, OWNER)
            assert started.watchers_workflow_id is not None
            evaluator = handle = client.get_workflow_handle(started.watchers_workflow_id)
            await append_fixture_events(
                pool,
                stack.scope,
                run_id,
                [("artifact.admitted", {"artifact_ref": "artifact://a/1"})],
            )
            store = PostgresWatcherStore(pool, stack.scope)
            history = await eventually(lambda: store.history(run_id), bool)
            assert [(item.watcher_id, item.outcome) for item in history] == [
                ("artifact-in", "fired")
            ]
            # Later passes find the firing in the journal and never record it again.
            passes = (await evaluator.query(WatchersWorkflow.state))["passes"]
            await eventually(
                lambda: evaluator.query(WatchersWorkflow.state),
                lambda state: state["passes"] >= passes + 2,
            )
            assert len(await store.history(run_id)) == 1
    finally:
        if handle is not None:
            await handle.terminate("MO-44 test cleanup")
        await pool.close()
