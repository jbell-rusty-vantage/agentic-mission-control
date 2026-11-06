"""MO-44 acceptance: sample watchers fire deterministically in a Temporal test environment,
limits hold, and neither a replayed history, a retried activity nor a fresh evaluator over the
same journal acts twice (SPEC-04 §5, §8 "Watchers").

`mc.watchers.v1` runs on the time-skipping test server with the real activity and the real
evaluation service; the journal and the command path are the in-memory FIXTURE ports
(`tests/unit/watchers/fakes.py`). A timeline releases each observation into the journal once
workflow time reaches it, so the run unfolds over two simulated hours in seconds. The same
service over PostgreSQL is proven in `tests/integration/postgres/test_mo44_watchers_postgres.py`.

Sample watchers (SPEC-04 §5.1): `ci-red-fix` (signal + condition -> instruct, max 3, 10 min
apart), `stalled` (absence of frames and signals for 20 min while active -> notify + probe,
max 2), `artifact-to-ingest` (signal + condition -> instruct, rate 2/h, token budget; `launch`
is not built, see HANDOFF) and `done-notify` (run.completed -> notify). A second timeline
covers a silence held by a longer `min_interval`, the recursion bound across watcher chains,
and an `event_wait` whose event comes before the StageGraph declares its wait.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mission_control.adapters.temporal.activities.watchers import WatcherActivities
from mission_control.adapters.temporal.submission import TemporalWorkflowSubmitter
from mission_control.adapters.temporal.watcher_starter import TemporalWatcherStarter
from mission_control.adapters.temporal.workflow_sandbox import coordinator_workflow_runner
from mission_control.adapters.temporal.workflows.watchers import (
    WATCHERS_WORKFLOW,
    WatchersWorkflow,
    WatchersWorkflowInput,
    WatchersWorkflowResult,
)
from mission_control.application.chains.relay import (
    ChainIntent,
    ChainIntentRelay,
    LaunchServiceChainStarter,
)
from mission_control.application.execution.run_launch import RunLaunchService
from mission_control.application.watchers.service import (
    WatcherEvaluationService,
    WatcherPassReport,
    WatcherPassRequest,
)
from mission_control.contracts.identities import (
    mission_root_id,
    mission_watchers_id,
    parse_request_scope,
)
from mission_control.domain.programs.watchers import WatcherDescriptor, WatcherSpec, compile_watcher
from tests.integration.temporal.test_chain_start_idempotent import (
    NOW,
    AdmittedRunInputs,
    OneShotStore,
)
from tests.integration.temporal.test_chain_start_idempotent import SCOPE as CHAIN_SCOPE
from tests.unit.run_control.test_run_control import request, service
from tests.unit.watchers.fakes import RUN_ID, FakeRunGateway, MemoryWatcherStore
from tests.unit.watchers.test_watcher_manifest import definition, event_wait_document

SCOPE = "mc/00000000-0000-4000-8000-000000000001/biotech/00000000-0000-4000-8000-000000000002"
MINUTE = 60


def watcher(watcher_id: str, body: dict[str, Any]) -> WatcherDescriptor:
    return compile_watcher(
        WatcherSpec.model_validate(body),
        watcher_id=watcher_id,
        origin="manifest",
        pointer=f"/mission/controls/watchers/{watcher_id}",
    )


SAMPLES = (
    watcher(
        "ci-red-fix",
        {
            "on": {
                "signal": "github.check_suite.completed",
                "where": "event.conclusion == 'failure' and "
                "startswith(event.head_branch, run.branch_prefix)",
            },
            "then": [{"instruct": {"text": "CI is red; fix it.", "include": ["event.summary"]}}],
            "limits": {"max_fires": 3, "min_interval": "10m"},
        },
    ),
    watcher(
        "stalled",
        {
            "on": {
                "absence": {"of": ["frame", "signal"], "for": "20m"},
                "while": "run.phase == 'active'",
            },
            "then": [
                {"notify": {"kind": "blocked", "text": "No progress for 20 minutes"}},
                {"probe": {}},
            ],
            "limits": {"max_fires": 2},
        },
    ),
    watcher(
        "artifact-to-ingest",
        {
            "on": {"signal": "artifact.ready", "where": "event.media_type == 'application/pdf'"},
            "then": [
                {"instruct": {"text": "Ingest this artifact.", "include": ["event.artifact_ref"]}}
            ],
            "limits": {"max_fires": 50, "rate": "2/h", "budget": {"tokens": 2_000_000}},
        },
    ),
    watcher(
        "done-notify",
        {"on": {"event": "run.completed"}, "then": [{"notify": {"kind": "terminal_result"}}]},
    ),
)


@dataclass(frozen=True)
class Step:
    minute: float
    apply: Callable[[MemoryWatcherStore, FakeRunGateway, datetime], None]


def ci(conclusion: str, summary: str) -> Callable[..., None]:
    def apply(store: MemoryWatcherStore, _runs: FakeRunGateway, when: datetime) -> None:
        store.signal(
            "github.check_suite.completed",
            {"conclusion": conclusion, "head_branch": f"mc/{RUN_ID}/fix", "summary": summary},
            when=when,
            trust="provider_signed",
        )

    return apply


def artifact(media_type: str, ref: str) -> Callable[..., None]:
    def apply(store: MemoryWatcherStore, _runs: FakeRunGateway, when: datetime) -> None:
        store.signal("artifact.ready", {"media_type": media_type, "artifact_ref": ref}, when=when)

    return apply


def frame(store: MemoryWatcherStore, _runs: FakeRunGateway, when: datetime) -> None:
    store.frames.append(when)


def spend(store: MemoryWatcherStore, _runs: FakeRunGateway, _when: datetime) -> None:
    store.usage_by_dimension["tokens.total"] = 2_000_000


def finish(store: MemoryWatcherStore, runs: FakeRunGateway, when: datetime) -> None:
    store.event("workflow_run.terminalize", when=when, alias="run.completed")
    runs.view.lifecycle, runs.view.phase = "completed", "terminal"


TIMELINE = (
    Step(1, frame),
    Step(2, ci("failure", "unit tests red")),  # ci-red-fix 1
    Step(5, ci("failure", "still red")),  # min_interval
    Step(13, ci("failure", "lint red")),  # ci-red-fix 2
    Step(14, artifact("application/pdf", "artifact://pdf/1")),  # artifact 1
    Step(15, artifact("application/pdf", "artifact://pdf/2")),  # artifact 2
    Step(16, artifact("application/pdf", "artifact://pdf/3")),  # rate 2/h
    Step(17, artifact("text/plain", "artifact://txt/1")),  # filtered by where
    Step(20, ci("success", "green")),  # filtered by where
    Step(30, ci("failure", "red again")),  # ci-red-fix 3
    Step(45, ci("failure", "red forever")),  # max_fires; stalled due at 65
    Step(75, spend),
    Step(80, artifact("application/pdf", "artifact://pdf/4")),  # budget; stalled due at 100
    Step(130, finish),  # stalled's third silence (120) was suppressed: max_fires
)


class TimelineService:
    """Releases each timeline step once the workflow's clock reaches it, then runs the pass."""

    def __init__(
        self,
        base: datetime,
        store: MemoryWatcherStore,
        runs: FakeRunGateway,
        timeline: tuple[Step, ...] = TIMELINE,
    ) -> None:
        self.base = base
        self.store = store
        self.runs = runs
        self.pending = list(timeline)
        self.service = WatcherEvaluationService(store, runs)
        self.passes: list[WatcherPassReport] = []

    async def run_pass(self, request: WatcherPassRequest) -> WatcherPassReport:
        while self.pending and self.base + timedelta(minutes=self.pending[0].minute) <= request.now:
            step = self.pending.pop(0)
            step.apply(self.store, self.runs, self.base + timedelta(minutes=step.minute))
        report = await self.service.run_pass(request)
        self.passes.append(report)
        return report


async def run_watchers(
    env: WorkflowEnvironment, services: Callable[[str], Any], workflow_id: str
) -> tuple[WatchersWorkflowResult, WorkflowHistory]:
    queue = f"watchers-{uuid.uuid4()}"
    async with Worker(
        env.client,
        task_queue=queue,
        workflows=[WatchersWorkflow],
        activities=[WatcherActivities(services).evaluate],
        workflow_runner=coordinator_workflow_runner(),
    ):
        handle = await env.client.start_workflow(
            WATCHERS_WORKFLOW,
            WatchersWorkflowInput(request_scope=SCOPE, run_id=RUN_ID, poll_seconds=5 * MINUTE),
            id=workflow_id,
            task_queue=queue,
            result_type=WatchersWorkflowResult,
        )
        result = await handle.result()
        return result, await handle.fetch_history()


def fired_at(store: MemoryWatcherStore, watcher_id: str, base: datetime) -> list[float]:
    return [
        (datetime.fromisoformat(item["fired_at"]) - base).total_seconds() / MINUTE
        for item in store.fired(watcher_id)
    ]


async def test_sample_watchers_fire_deterministically_within_their_limits_and_never_twice() -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        base = await env.get_current_time()
        store, runs = MemoryWatcherStore(SAMPLES), FakeRunGateway()
        store.fail_records = 1  # the first firing's record fails once: the activity retries
        timeline = TimelineService(base, store, runs)
        result, history = await run_watchers(
            env, lambda scope: timeline if scope == SCOPE else None, f"watchers-{uuid.uuid4()}"
        )

        assert fired_at(store, "ci-red-fix", base) == [2, 13, 30]
        assert fired_at(store, "artifact-to-ingest", base) == [14, 15]
        assert fired_at(store, "stalled", base) == [65, 100]
        assert fired_at(store, "done-notify", base) == [130]
        assert all(item.event_type == "watcher.fired" for item in store.recorded)
        assert (result.fired, result.failed) == (8, 0)
        suppressed: dict[str, int] = {}
        for report in timeline.passes:
            for item in report.suppressed:
                key = f"{item.watcher_id}:{item.reason}"
                suppressed[key] = suppressed.get(key, 0) + 1
        assert suppressed["ci-red-fix:min_interval"] == 1
        assert suppressed["ci-red-fix:max_fires"] == 1
        assert suppressed["artifact-to-ingest:rate_limited"] == 1
        assert suppressed["artifact-to-ingest:budget_exhausted"] == 1
        assert suppressed["stalled:max_fires"] >= 1

        # Five instructions were admitted once each; the retried first pass replayed its own.
        assert runs.kinds() == ["queue_instruction"] * 5
        assert len(runs.calls) == 6
        first, retried = runs.calls[0], runs.calls[1]
        assert first.request_id == retried.request_id
        stalled = store.fired("stalled")
        assert [item["actions"][1]["facts"]["phase"] for item in stalled] == ["active", "active"]
        assert [item["notify_kind"] for item in stalled] == ["blocked", "blocked"]
        ingest = runs.calls[3].payload.content.text  # type: ignore[union-attr]
        assert '> {"event.artifact_ref": "artifact://pdf/1"}' in ingest

        # Replaying the recorded history is deterministic and issues nothing.
        await Replayer(
            workflows=[WatchersWorkflow], workflow_runner=coordinator_workflow_runner()
        ).replay_workflow(history)
        assert len(runs.calls) == 6 and len(store.recorded) == 8

        # A fresh evaluator over the same journal (cursor 0) finds every firing in history.
        fresh = WatcherEvaluationService(store, runs)
        again, _ = await run_watchers(
            env, lambda scope: fresh if scope == SCOPE else None, f"watchers-{uuid.uuid4()}"
        )
        assert (again.fired, again.failed) == (0, 0)
        assert len(runs.calls) == 6 and len(store.recorded) == 8


async def test_one_evaluator_per_run_including_chain_released_consumers() -> None:
    run_service, _ = service()
    admitted = await run_service.admit(
        request(request_scope=CHAIN_SCOPE, request_id=str(uuid.uuid4()))
    )
    assert admitted.run_id is not None
    parsed = parse_request_scope(CHAIN_SCOPE)
    intent = ChainIntent(
        intent_kind="start_run",
        delivery_key=f"chain-start:{admitted.run_id}",
        request_scope=CHAIN_SCOPE,
        chain_id=uuid.uuid4(),
        mission_id=uuid.uuid4(),
        run_id=uuid.UUID(int=1),
        run_key=admitted.run_id,
        family="GoalDirected",
        initial_goal="Ingest the supplied evidence map",
        actor_ref="chain:test",
    )
    async with await WorkflowEnvironment.start_time_skipping() as env:
        watchers = TemporalWatcherStarter(env.client, task_queue="chain-test-watchers")
        relay = ChainIntentRelay(
            store=OneShotStore(intent),  # the first acknowledgement is lost: delivered twice
            starter=LaunchServiceChainStarter(
                inputs=AdmittedRunInputs(run_service),
                launches=RunLaunchService(
                    run_control=run_service,
                    submitter=TemporalWorkflowSubmitter(
                        env.client,
                        stagegraph_task_queue="chain-test-stagegraph",
                        goal_directed_task_queue="chain-test-goal",
                        mission_installation_id=parsed.installation_id,
                        mission_application_id=parsed.application_id,
                    ),
                ),
                watchers=watchers,
            ),
        )
        await relay.relay_once(CHAIN_SCOPE, now=NOW)
        workflow_id = mission_watchers_id(CHAIN_SCOPE, admitted.run_id)
        assert workflow_id == f"{mission_root_id(CHAIN_SCOPE, admitted.run_id)}/watchers"
        handle = env.client.get_workflow_handle(workflow_id)
        first = await handle.describe()
        assert first.workflow_type == WATCHERS_WORKFLOW
        assert first.task_queue == "chain-test-watchers"
        # The redelivered intent and a repeated start reach the same single evaluator.
        await relay.relay_once(CHAIN_SCOPE, now=NOW)
        assert await watchers.start(CHAIN_SCOPE, admitted.run_id) == workflow_id
        assert (await handle.describe()).run_id == first.run_id


def merged(store: MemoryWatcherStore, _runs: FakeRunGateway, when: datetime) -> None:
    store.event("github.pull_request.merged", {"base": "main", "merged": True}, when=when)


def declare(_store: MemoryWatcherStore, runs: FakeRunGateway, _when: datetime) -> None:
    runs.view.declare("stagegraph-wait:await-merge")


async def test_held_clocks_recursion_and_an_early_event_wait_on_the_workflow() -> None:
    (await_merge,) = definition(event_wait_document()).policies.watchers
    stall = watcher(
        "stall",
        {
            "on": {"absence": {"of": ["frame"], "for": "20m"}},
            "then": [{"notify": {"kind": "blocked"}}],
            "limits": {"max_fires": 3, "min_interval": "60m"},
        },
    )
    relay = watcher(
        "relay",
        {"on": {"event": "watcher.fired"}, "then": [{"notify": {"kind": "progress"}}]},
    )
    timeline = (Step(5, merged), Step(50, declare), Step(150, finish))
    async with await WorkflowEnvironment.start_time_skipping() as env:
        base = await env.get_current_time()
        store, runs = MemoryWatcherStore((stall, relay, await_merge)), FakeRunGateway()
        service = TimelineService(base, store, runs, timeline)
        result, history = await run_watchers(
            env, lambda scope: service if scope == SCOPE else None, f"watchers-{uuid.uuid4()}"
        )

        # The silence (from the arming time) held by min_interval fires as the interval
        # allows, without spinning.
        assert [round(item) for item in fired_at(store, "stall", base)] == [20, 80, 140]
        assert len(service.passes) < 60
        # The early merge is held until the wait is declared, then releases it once.
        assert fired_at(store, "event_wait:await-merge", base) == [5]
        assert any(report.held for report in service.passes)
        assert runs.kinds() == ["satisfy_wait"] and runs.view.projection.active_waits == []
        # A watcher reacting to watcher.fired fires at depth 2; its own record is depth 3.
        relayed = store.fired("relay")
        assert len(relayed) == 4 and {item["depth"] for item in relayed} == {2}
        bounded = [
            item
            for report in service.passes
            for item in report.suppressed
            if item.reason == "recursion_bound"
        ]
        assert {item.watcher_id for item in bounded} == {"relay"} and len(bounded) == 4
        assert (result.fired, result.failed) == (8, 0)
        await Replayer(
            workflows=[WatchersWorkflow], workflow_runner=coordinator_workflow_runner()
        ).replay_workflow(history)
        assert len(store.recorded) == 8
