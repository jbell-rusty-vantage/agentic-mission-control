"""WI-17 / OVE-180: scoped hook reads, staged candidates and safe-boundary installation.

Acceptance clauses proven here (application + domain, in-memory doubles; the PostgreSQL store is
proven in ``tests/integration/postgres/test_hook_candidate_installs_postgres.py`` and the Deep
Agents lane in ``tests/unit/deep_agents/test_hook_contributions_graph.py``):

- a read outside the declared scope, of host-owned state or over its bound refuses;
- a candidate targeting host state, a sealed input mount or a used plan path refuses;
- a same-path race installs one candidate; a crash after the write or after the outcome
  recovers exactly once (one outcome, one write);
- a candidate file cannot fulfill an obligation (output slots refuse; an installed file is not a
  submission);
- candidates and operation requests are observation results; requests go to admission.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from mission_control.application.context.hook_contributions import (
    ContributionSession,
    ContributionTarget,
    HookContributionService,
    HookGrants,
    HookReadBroker,
)
from mission_control.contracts.hooks import HookResult
from mission_control.domain.capabilities.hooks import HookEvent
from mission_control.domain.context.contributions import (
    CandidateOrigin,
    ContributionRefusal,
    HostReadScope,
    OperationRequestProposal,
    ProtectedPaths,
    StagedCandidate,
    StageGrant,
    attribute_candidate,
    content_digest,
    event_role,
    permits_contributions,
)
from mission_control.domain.context.transfer import INDEX_PATH
from mission_control.domain.outputs.contracts import OutputForm
from tests.fixtures.hook_contributions import (
    Crash,
    InMemoryInstallStore,
    MemoryWorkspace,
    RecordingOperationRequests,
)
from tests.fixtures.knowledge_binding import InMemoryStaging
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.outputs.scenario import build_stack, codes, obligation
from tests.unit.outputs.test_output_fulfillment import invocation

SCOPE = "mc/11111111-1111-1111-1111-111111111111/biotech/22222222-2222-2222-2222-222222222222"
TARGET = ContributionTarget(scope=SCOPE, run_id="run-1", operation_ref="op-1", generation=1)
NOTES = StageGrant(paths=("/prepared/**",), operation_templates=("mc.prepare.index@1",))
READS = HostReadScope(name="notes", kind="workspace", paths=("/prepared/**", "/prepared/a.md"))


def origin(
    hook: str = "hook.notes", event: HookEvent = HookEvent.AFTER_TOOL, attempt: int = 1
) -> CandidateOrigin:
    return CandidateOrigin(
        hook_id=hook,
        event=event,
        run_id="run-1",
        operation_id="op-1",
        attempt_no=attempt,
        generation=1,
        harness_execution_id=f"exec-{attempt}",
        input_digest=content_digest(b"input"),
    )


def candidate(path: str, body: str = "# prepared\n", **extra: str) -> StagedCandidate:
    return StagedCandidate(
        path=path, content=body, digest=extra.pop("digest", content_digest(body.encode()))
    )


def service(store: InMemoryInstallStore, **kw: object) -> HookContributionService:
    staging = kw.pop("staging", None) or InMemoryStaging()
    return HookContributionService(
        store=store,
        staging=staging,  # type: ignore[arg-type]
        custody=staging,  # type: ignore[arg-type]
        clock=lambda: datetime(2026, 10, 27, 12, tzinfo=UTC),
        **kw,  # type: ignore[arg-type]
    )


def session(
    store: InMemoryInstallStore,
    *,
    protected: ProtectedPaths | None = None,
    target: ContributionTarget = TARGET,
    current: object = None,
    **kw: object,
) -> ContributionSession:
    return ContributionSession(
        service=kw.pop("svc", None) or service(store, **kw),  # type: ignore[arg-type]
        target=target,
        current=current,  # type: ignore[arg-type]
        grants={"hook.notes": HookGrants(reads=(READS,), stage=NOTES)},
        protected=protected,
    )


async def stage(contrib: ContributionSession, *items: StagedCandidate, **kw: object) -> None:
    await contrib.collect(
        origin(**kw),  # type: ignore[arg-type]
        HookResult(staged_candidates=items),
    )


# ---------------------------------------------------------------- the event matrix


def test_event_roles_follow_the_output_contract_table() -> None:
    assert event_role(HookEvent.BEFORE_TOOL).value == "before_effect_guard"
    assert event_role(HookEvent.AFTER_TOOL).value == "observation"
    assert event_role(HookEvent.BEFORE_COMPACTION).value == "before_compaction"
    assert not permits_contributions(HookEvent.BEFORE_SHELL)
    assert permits_contributions(HookEvent.AFTER_FILE_EDIT)
    refused = attribute_candidate(origin(event=HookEvent.BEFORE_TOOL), candidate("/prepared/a.md"))
    assert isinstance(refused, ContributionRefusal) and refused.code == "RESULT_NOT_PERMITTED"


def test_a_script_cannot_supply_its_own_origin_or_install_state() -> None:
    with pytest.raises(ValidationError):
        StagedCandidate.model_validate(
            {
                "path": "/prepared/a.md",
                "content": "x",
                "digest": content_digest(b"x"),
                "origin": {"hook_id": "kernel"},
            }
        )
    with pytest.raises(ValidationError):
        HookResult.model_validate({"staged_candidates": [], "installed": True})


@pytest.mark.parametrize(
    "paths",
    [("/**",), ("/*",), ("/.mission/**",), ("/inputs/**",), ("/prepared/../inputs/x",)],
)
def test_grants_and_read_scopes_refuse_whole_workspace_host_state_and_inputs(paths) -> None:
    with pytest.raises(ValidationError):
        StageGrant(paths=paths)
    if paths[0] != "/inputs/**":
        with pytest.raises(ValidationError):
            HostReadScope(name="r", kind="workspace", paths=paths)


# ---------------------------------------------------------------- scoped reads


async def test_reads_are_scoped_bounded_and_never_reach_host_state() -> None:
    workspace = MemoryWorkspace(
        files={
            "/prepared/a.md": b"alpha",
            "/secret/b.md": b"beta",
            INDEX_PATH: b"{}",
            "/prepared/big.md": b"x" * 40,
            "/prepared/bin.dat": b"\xff\xfe",
        }
    )
    broker = HookReadBroker()
    small = READS.model_copy(update={"max_bytes": 32})
    allowed = await broker.resolve(small, "/prepared/a.md", workspace)
    assert allowed.content == "alpha" and allowed.digest == content_digest(b"alpha")
    assert (await broker.resolve(small, "/secret/b.md", workspace)).refused == "READ_OUT_OF_SCOPE"
    assert (await broker.resolve(small, INDEX_PATH, workspace)).refused == "READ_HOST_PRIVATE"
    assert (await broker.resolve(small, "/prepared/big.md", workspace)).refused == (
        "READ_TOO_LARGE"
    )
    assert (await broker.resolve(small, "/prepared/bin.dat", workspace)).refused == (
        "READ_NOT_TEXT"
    )
    assert (await broker.resolve(small, "/prepared/../secret/b.md", workspace)).refused == (
        "READ_OUT_OF_SCOPE"
    )
    # The event's own path (a file a tool read) is served only under a covering scope.
    reads = await broker.reads_for(
        HookEvent.AFTER_TOOL, (small,), workspace, event_paths=("/secret/b.md",)
    )
    assert [(item.target, item.refused) for item in reads] == [
        ("/prepared/a.md", None),
        ("/secret/b.md", "READ_OUT_OF_SCOPE"),
    ]


# ---------------------------------------------------------------- policy refusals


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("/.mission/state.json", "HOST_STATE_OVERWRITE"),
        ("/.Mission/state.json", "HOST_STATE_OVERWRITE"),
        ("/Inputs/report/r7/report.md", "SEALED_INPUT_REWRITE"),
        (INDEX_PATH, "HOST_STATE_OVERWRITE"),
        ("/inputs/report/r7/report.md", "SEALED_INPUT_REWRITE"),
        ("/workspace/output/report.md", "OUTPUT_SLOT_PATH"),
        ("/context/packet.md", "PROTECTED_PATH"),
        ("/elsewhere/a.md", "PATH_OUT_OF_GRANT"),
    ],
)
async def test_state_overwrite_used_plan_and_output_slot_candidates_refuse(path, code) -> None:
    store = InMemoryInstallStore()
    workspace = MemoryWorkspace()
    contrib = ContributionSession(
        service=service(store),
        target=TARGET,
        grants={
            "hook.notes": HookGrants(
                stage=StageGrant(paths=(path,))
                if code in {"OUTPUT_SLOT_PATH", "PROTECTED_PATH"}
                else NOTES
            )
        },
        protected=ProtectedPaths(
            sealed_paths=frozenset({"/inputs/report/r7/report.md"}),
            output_paths=("/workspace/output",),
            reserved_paths=("/context/packet.md",),
        ),
    )
    await stage(contrib, candidate(path))
    receipt = await contrib.boundary(workspace, "before_model_call")
    assert [item.code for item in receipt.refusals] == [code]
    assert receipt.records == () and workspace.writes == [] and store.claims == {}


async def test_a_candidate_never_overwrites_other_bytes_and_respects_its_budget() -> None:
    store = InMemoryInstallStore()
    workspace = MemoryWorkspace(files={"/prepared/a.md": b"agent's own file"})
    contrib = ContributionSession(
        service=service(store),
        target=TARGET,
        grants={
            "hook.notes": HookGrants(stage=StageGrant(paths=("/prepared/**",), max_candidates=1))
        },
    )
    await stage(contrib, candidate("/prepared/a.md"), candidate("/prepared/b.md"))
    receipt = await contrib.boundary(workspace, "before_model_call")
    assert sorted(item.code for item in receipt.refusals) == [
        "CANDIDATE_BUDGET",
        "VERSION_CONFLICT",
    ]
    assert workspace.files["/prepared/a.md"] == b"agent's own file"


async def test_a_forged_digest_and_two_candidates_on_one_path_refuse() -> None:
    store = InMemoryInstallStore()
    contrib = session(store)
    await stage(contrib, candidate("/prepared/a.md", digest=content_digest(b"other")))
    await stage(contrib, candidate("/prepared/c.md", "one"), candidate("/prepared/c.md", "two"))
    receipt = await contrib.boundary(MemoryWorkspace(), "before_model_call")
    assert [item.code for item in contrib.refusals] == ["CANDIDATE_DIGEST_MISMATCH"]
    assert [item.code for item in receipt.refusals] == ["PATH_COLLISION", "PATH_COLLISION"]


async def test_a_fenced_generation_installs_nothing() -> None:
    class Fenced:
        async def check(self, origin: CandidateOrigin) -> ContributionRefusal | None:
            return ContributionRefusal(code="GENERATION_FENCED", message="fenced")

    store = InMemoryInstallStore()
    contrib = session(store, grants=Fenced())
    await stage(contrib, candidate("/prepared/a.md"))
    receipt = await contrib.boundary(MemoryWorkspace(), "before_model_call")
    assert [item.code for item in receipt.refusals] == ["GENERATION_FENCED"]
    assert store.claims == {}


# ---------------------------------------------------------------- race and crash recovery


async def test_a_same_path_race_installs_one_candidate() -> None:
    store = InMemoryInstallStore()
    staging = InMemoryStaging()
    workspace = MemoryWorkspace()
    first, second = session(store, staging=staging), session(store, staging=staging)
    await stage(first, candidate("/prepared/a.md", "from the first worker"))
    await stage(second, candidate("/prepared/a.md", "from the second worker"), hook="hook.notes")
    receipts = await asyncio.gather(
        first.boundary(workspace, "before_model_call"),
        second.boundary(workspace, "before_model_call"),
    )
    installed = [item for receipt in receipts for item in receipt.installed]
    lost = [item.code for receipt in receipts for item in receipt.refusals]
    assert len(installed) == 1 and lost == ["PATH_CLAIMED"]
    assert len(store.claims) == 1 and len(store.outcomes) == 1
    assert workspace.writes == ["/prepared/a.md"]
    winner = next(iter(store.claims.values())).candidate
    assert content_digest(workspace.files["/prepared/a.md"]) == winner.digest


async def test_a_crash_after_the_write_recovers_once_without_writing_again() -> None:
    store = InMemoryInstallStore(crash_before_outcome=1)
    staging = InMemoryStaging()
    workspace = MemoryWorkspace()
    before = session(store, staging=staging)
    await stage(before, candidate("/prepared/a.md"))
    with pytest.raises(Crash):
        await before.boundary(workspace, "before_model_call")
    assert workspace.writes == ["/prepared/a.md"] and store.outcomes == {}

    # A fresh worker resumes the attempt: the next boundary records the outcome once.
    after = session(store, staging=staging)
    receipt = await after.boundary(workspace, "before_model_call")
    assert [(item.path, item.recovered) for item in receipt.installed] == [("/prepared/a.md", True)]
    assert workspace.writes == ["/prepared/a.md"] and len(store.outcomes) == 1
    # The retried hook re-stages the same candidate: same identity, nothing written again.
    await stage(after, candidate("/prepared/a.md"))
    again = await after.boundary(workspace, "before_model_call")
    assert [item.recovered for item in again.installed] == [True]
    assert workspace.writes == ["/prepared/a.md"] and len(store.outcomes) == 1


async def test_a_crash_after_the_outcome_is_never_installed_twice() -> None:
    store = InMemoryInstallStore(crash_after_outcome=1)
    staging = InMemoryStaging()
    workspace = MemoryWorkspace()
    before = session(store, staging=staging)
    await stage(before, candidate("/prepared/a.md"))
    with pytest.raises(Crash):
        await before.boundary(workspace, "before_model_call")
    after = session(store, staging=staging)
    await stage(after, candidate("/prepared/a.md"))
    receipt = await after.boundary(workspace, "before_model_call")
    assert [item.recovered for item in receipt.installed] == [True]
    assert workspace.writes == ["/prepared/a.md"] and len(store.outcomes) == 1


async def test_a_state_channel_install_is_confirmed_only_after_its_step_commits() -> None:
    store = InMemoryInstallStore()
    staging = InMemoryStaging()
    workspace = MemoryWorkspace(durable=False)
    contrib = session(store, staging=staging)
    await stage(contrib, candidate("/prepared/a.md"))
    first = await contrib.boundary(workspace, "before_model_call")
    assert [item.state for item in first.records] == ["pending"] and store.outcomes == {}

    # The step is lost (a crash before its checkpoint): the next attempt writes it again once.
    workspace.lose_step()
    resumed = session(store, staging=staging)
    second = await resumed.boundary(workspace, "before_model_call")
    assert [item.state for item in second.records] == ["pending"]
    workspace.commit()
    third = await resumed.boundary(workspace, "before_model_call")
    assert [(item.state, item.recovered) for item in third.records] == [("installed", False)]
    assert workspace.writes == ["/prepared/a.md", "/prepared/a.md"] and len(store.outcomes) == 1


# ---------------------------------------------------------------- no self-fulfillment


async def test_an_installed_candidate_does_not_fulfill_an_obligation() -> None:
    outputs = InMemoryOutputContractStore()
    stack = await build_stack(
        outputs, outputs.submissions, invocation(), obligation("draft.report", OutputForm.TEXT)
    )
    store = InMemoryInstallStore()
    workspace = MemoryWorkspace()
    contrib = ContributionSession(
        service=service(store),
        target=TARGET,
        grants={"hook.notes": HookGrants(stage=StageGrant(paths=("/prepared/**", "/out/**")))},
        protected=ProtectedPaths(output_paths=("/out",)),
    )
    report = "# Findings\n"
    await stage(
        contrib, candidate("/prepared/report.md", report), candidate("/out/report.md", report)
    )
    receipt = await contrib.boundary(workspace, "before_model_call")
    assert [item.path for item in receipt.installed] == ["/prepared/report.md"]
    assert [item.code for item in receipt.refusals] == ["OUTPUT_SLOT_PATH"]
    result = await stack.evaluate()
    assert result.blocking == ("draft.report",) and codes(result, "draft.report") == ["MISSING"]


# ---------------------------------------------------------------- operation requests


async def test_operation_requests_are_attributed_admitted_separately_or_refused() -> None:
    store = InMemoryInstallStore()
    unwired = session(store)
    proposal = OperationRequestProposal(
        template="mc.prepare.index@1", purpose="index the staged notes", request_key="index-1"
    )
    await unwired.collect(origin(), HookResult(operation_requests=(proposal,)))
    assert [item.code for item in unwired.requests] == ["OPERATION_REQUEST_UNWIRED"]

    admission = RecordingOperationRequests()
    wired = session(store, requests=admission)
    not_granted = proposal.model_copy(update={"template": "mc.external.write@1"})
    await wired.collect(origin(), HookResult(operation_requests=(proposal, not_granted)))
    await wired.collect(origin(), HookResult(operation_requests=(proposal,)))  # a retry
    await wired.collect(
        origin(event=HookEvent.BEFORE_TOOL), HookResult(operation_requests=(proposal,))
    )
    assert [item.status for item in wired.requests] == ["admitted", "admitted"]
    assert len(admission.admitted) == 1
    request = admission.admitted[0]
    assert request.origin.hook_id == "hook.notes" and request.origin.event is HookEvent.AFTER_TOOL
    assert sorted(item.code for item in wired.refusals) == [
        "OPERATION_TEMPLATE_NOT_ADMITTED",
        "RESULT_NOT_PERMITTED",
    ]


# ---------------------------------------------------- review: attempts, fence and visibility


async def test_a_retry_attempt_on_a_fresh_backend_installs_and_never_replays_the_earlier_one() -> (
    None
):
    store = InMemoryInstallStore()
    staging = InMemoryStaging()
    first_backend = MemoryWorkspace(durable=False)  # attempt 1 dies before its step commits
    first = session(store, staging=staging)
    await stage(first, candidate("/prepared/a.md"))
    assert [item.state for item in (await first.boundary(first_backend, "b")).records] == [
        "pending"
    ]

    retry = ContributionTarget(scope=SCOPE, run_id="run-1", operation_ref="op-1", attempt=2)
    fresh = MemoryWorkspace()
    second = session(store, staging=staging, target=retry)
    # Nothing staged yet: attempt 1's pending claim is never written into attempt 2's workspace.
    assert (await second.boundary(fresh, "b")).records == () and fresh.writes == []
    await stage(second, candidate("/prepared/a.md", "attempt two"), attempt=2)
    receipt = await second.boundary(fresh, "b")
    assert [(item.state, item.recovered) for item in receipt.records] == [("installed", False)]
    assert fresh.files["/prepared/a.md"] == b"attempt two"
    assert len(store.claims) == 2 and len(store.outcomes) == 1


async def test_a_recorded_install_whose_bytes_are_gone_is_not_reported_installed() -> None:
    store = InMemoryInstallStore()
    staging = InMemoryStaging()
    workspace = MemoryWorkspace()
    contrib = session(store, staging=staging)
    await stage(contrib, candidate("/prepared/a.md"))
    await contrib.boundary(workspace, "b")
    del workspace.files["/prepared/a.md"]
    await stage(contrib, candidate("/prepared/a.md"))
    receipt = await contrib.boundary(workspace, "b")
    assert receipt.installed == ()
    assert [item.code for item in receipt.refusals] == ["INSTALLED_FILE_ABSENT"]


async def test_a_fenced_run_settles_nothing() -> None:
    class Fenced:
        async def check(self, origin: CandidateOrigin) -> ContributionRefusal | None:
            return ContributionRefusal(code="GENERATION_FENCED", message="fenced")

    store = InMemoryInstallStore(crash_before_outcome=1)
    staging = InMemoryStaging()
    workspace = MemoryWorkspace()
    dying = session(store, staging=staging)
    await stage(dying, candidate("/prepared/a.md"))
    with pytest.raises(Crash):
        await dying.boundary(workspace, "b")
    workspace.files.clear()  # the write had not landed either
    fenced = session(store, staging=staging, current=Fenced())
    receipt = await fenced.boundary(workspace, "b")
    assert [item.code for item in receipt.refusals] == ["GENERATION_FENCED"]
    assert receipt.records == () and store.outcomes == {} and workspace.files == {}


async def test_collect_outcomes_and_leftovers_at_close_are_visible() -> None:
    store = InMemoryInstallStore()
    contrib = session(store, requests=RecordingOperationRequests())
    proposal = OperationRequestProposal(
        template="mc.prepare.index@1", purpose="index", request_key="k1"
    )
    outcome = await contrib.collect(
        origin(event=HookEvent.STOP),
        HookResult(
            staged_candidates=(candidate("/prepared/late.md"), candidate("bad path")),
            operation_requests=(proposal,),
        ),
    )
    assert [item.candidate.path for item in outcome.staged] == ["/prepared/late.md"]
    assert [item.code for item in outcome.refusals] == ["PATH_INVALID"]
    assert [item.status for item in outcome.requests] == ["admitted"]
    closed = contrib.close()
    assert [(item.code, item.path) for item in closed] == [
        ("CANDIDATE_NOT_INSTALLED", "/prepared/late.md")
    ]
    assert contrib.staged == [] and store.claims == {}
    assert [item.code for item in contrib.refusals] == ["PATH_INVALID", "CANDIDATE_NOT_INSTALLED"]


@pytest.mark.parametrize(
    ("now", "code"),
    [
        ("policy", "OUTPUT_SLOT_PATH"),  # the path became an output slot
        ("grant", "PATH_OUT_OF_GRANT"),  # the hook's stage grant was revoked
    ],
)
async def test_settlement_honours_a_revoked_policy_or_grant(now: str, code: str) -> None:
    store = InMemoryInstallStore()
    staging = InMemoryStaging()
    workspace = MemoryWorkspace(durable=False)
    contrib = session(store, staging=staging)
    await stage(contrib, candidate("/prepared/a.md"))
    assert [item.state for item in (await contrib.boundary(workspace, "b")).records] == ["pending"]
    workspace.lose_step()  # nothing committed: settlement would write it again
    later = ContributionSession(
        service=service(store, staging=staging),
        target=TARGET,
        grants={"hook.notes": HookGrants(stage=NOTES if now == "policy" else None)},
        protected=ProtectedPaths(output_paths=("/prepared",)) if now == "policy" else None,
    )
    receipt = await later.boundary(workspace, "b")
    assert [item.code for item in receipt.refusals] == [code]
    assert receipt.records == () and store.outcomes == {} and workspace.writes == ["/prepared/a.md"]
