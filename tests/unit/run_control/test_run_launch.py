"""RRM-009: the governed launch binds the caller's family input to the admitted authority."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from mission_control.application.execution.run_launch import (
    RunClusterBinding,
    RunLaunchRejected,
    RunLaunchRequest,
    RunLaunchService,
    TemporalClusterIdentity,
    fork_semantic_input_binding_ref,
)
from mission_control.application.recovery.run_forks import ForkOfRun
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.coordinator.launch import BlueprintFamily, WorkflowSubmission
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.programs.contracts import StageGraphRunInput
from tests.fixtures.rrm009_production_stack import stage_blueprint
from tests.unit.run_control.test_run_control import (
    DIGEST,
    WORKFLOW_DIGEST,
    actor,
    request,
    service,
)

SCOPE = "tenant-1"


class RecordingSubmitter:
    def __init__(self) -> None:
        self.submissions: list[tuple[str, BlueprintFamily, str | None]] = []

    async def submit(
        self,
        workflow_input: object,
        *,
        workflow_id: str,
        blueprint_family: BlueprintFamily,
        parent_run_id: str | None = None,
    ) -> WorkflowSubmission:
        self.submissions.append((workflow_id, blueprint_family, parent_run_id))
        return WorkflowSubmission(workflow_id=workflow_id, temporal_run_id="temporal-run-1")


class UnmaterializedFork:
    async def fork_of_run(self, request_scope: str, derived_run_id: str) -> ForkOfRun | None:
        del request_scope, derived_run_id
        return ForkOfRun(fork_request_id="fork-1", materialized=False)


class NoFork:
    async def fork_of_run(self, request_scope: str, derived_run_id: str) -> ForkOfRun | None:
        del request_scope, derived_run_id
        return None


class NoForkReceipts:
    async def get_request(self, request_scope: str, request_id: str) -> Any:
        del request_scope, request_id
        return None

    async def get(self, request_scope: str, request_id: str) -> Any:
        del request_scope, request_id
        return None


def _input(run_id: str, *, version: int = 1, **overrides: Any) -> dict[str, Any]:
    graph = stage_blueprint()
    values = asdict(
        StageGraphRunInput(
            run_id=run_id,
            request_scope=SCOPE,
            effective_configuration_digest=DIGEST,
            workflow_type_digest=WORKFLOW_DIGEST,
            blueprint_digest=sha256_digest(graph),
            blueprint=graph.model_dump(mode="json"),
            initial_run_version=version,
            semantic_input_binding_ref="semantic-input:launch",
            # `request()` admits this baseline reservation.
            baseline_reservation={"tokens.total": 20},
        )
    )
    values.update(overrides)
    return values


def _launch(run_id: str, payload: dict[str, Any], **extra: Any) -> RunLaunchRequest:
    return RunLaunchRequest(
        request_scope=SCOPE, run_id=run_id, family="StageGraph", stagegraph=payload, **extra
    )


class RecordingClusterBindings:
    """FIXTURE: the first bind wins; later binds return the stored row (0032 semantics)."""

    def __init__(self) -> None:
        self.bound: dict[str, RunClusterBinding] = {}

    async def bind(
        self,
        request_scope: str,
        run_id: str,
        *,
        workflow_id: str,
        cluster: TemporalClusterIdentity,
        now: datetime,
    ) -> RunClusterBinding:
        key = f"{request_scope}/{run_id}"
        if key not in self.bound:
            self.bound[key] = RunClusterBinding(
                run_id=run_id, workflow_id=workflow_id, cluster=cluster, recorded_at=now
            )
        return self.bound[key]


LOCAL_CLUSTER = TemporalClusterIdentity(
    cluster_id="local:127.0.0.1:7233/default",
    target="local",
    address="127.0.0.1:7233",
    namespace="default",
    task_queue="mc-root",
)
CLOUD_CLUSTER = TemporalClusterIdentity(
    cluster_id="cloud:example.tmprl.cloud:7233/mc.acct",
    target="cloud",
    address="example.tmprl.cloud:7233",
    namespace="mc.acct",
    task_queue="mc-root",
)


@pytest.mark.asyncio
async def test_launch_binds_the_run_to_its_first_cluster_and_refuses_another() -> None:
    """MP-22: the binding is written before the submit; a service in another cluster never
    starts a second copy of the run, and the same cluster stays idempotent."""

    run_control, _ = service()
    admitted = await run_control.admit(request(request_id="launch-cluster"))
    run_id = admitted.run_id
    assert run_id is not None
    bindings = RecordingClusterBindings()
    with pytest.raises(ValueError, match="composed together"):
        RunLaunchService(
            run_control=run_control, submitter=RecordingSubmitter(), cluster=LOCAL_CLUSTER
        )
    elsewhere = RecordingSubmitter()
    cloud = RunLaunchService(
        run_control=run_control,
        submitter=elsewhere,
        cluster_bindings=bindings,
        cluster=CLOUD_CLUSTER,
    )
    local_submitter = RecordingSubmitter()
    local = RunLaunchService(
        run_control=run_control,
        submitter=local_submitter,
        cluster_bindings=bindings,
        cluster=LOCAL_CLUSTER,
    )
    receipt = await local.launch(_launch(run_id, _input(run_id)), actor())
    assert receipt.workflow_id == f"belllabs-run/{run_id}"
    bound = bindings.bound[f"{SCOPE}/{run_id}"]
    assert bound.cluster == LOCAL_CLUSTER and bound.workflow_id == receipt.workflow_id
    with pytest.raises(RunLaunchRejected) as refused:
        await cloud.launch(_launch(run_id, _input(run_id)), actor())
    assert refused.value.code == "run_bound_to_other_cluster"
    assert elsewhere.submissions == [], "the other cluster never submitted"
    # The bound cluster may launch again (the submitter's duplicate policy decides).
    await local.launch(_launch(run_id, _input(run_id)), actor())
    assert len(local_submitter.submissions) == 2
    assert bindings.bound[f"{SCOPE}/{run_id}"] == bound


@pytest.mark.asyncio
async def test_launch_starts_only_an_input_bound_to_the_admitted_run() -> None:
    run_control, _ = service()
    admitted = await run_control.admit(request(request_id="launch-1"))
    run_id = admitted.run_id
    assert run_id is not None
    submitter = RecordingSubmitter()
    launcher = RunLaunchService(run_control=run_control, submitter=submitter)

    with pytest.raises(RunLaunchRejected, match="workflow_run.start"):
        await launcher.launch(
            _launch(run_id, _input(run_id)),
            ActorContext(actor_id="operator", permissions=frozenset()),
        )
    for payload, code in (
        (_input(run_id, version=2), "stale_run_version"),
        (
            _input(run_id, effective_configuration_digest="sha256:" + "f" * 64),
            "configuration_mismatch",
        ),
        (_input(run_id, workflow_type_digest="sha256:" + "f" * 64), "configuration_mismatch"),
        (_input(run_id, blueprint_digest="sha256:" + "f" * 64), "configuration_mismatch"),
        (_input("another-run"), "identity_mismatch"),
        (_input(run_id, semantic_input_binding_ref=""), "invalid_family_input"),
        (_input(run_id, execution_epoch=2), "invalid_family_input"),
        (_input(run_id, baseline_reservation={}), "budget_mismatch"),
        (_input(run_id, baseline_reservation={"tokens.total": 21}), "budget_mismatch"),
    ):
        with pytest.raises(RunLaunchRejected) as rejected:
            await launcher.launch(_launch(run_id, payload), actor())
        assert rejected.value.code == code, (code, rejected.value.message)
    assert submitter.submissions == []

    receipt = await launcher.launch(_launch(run_id, _input(run_id)), actor())
    assert receipt.workflow_id == f"belllabs-run/{run_id}"
    assert receipt.parent_run_id is None and receipt.fork_request_id is None
    assert receipt.accepted_run_version == 1
    assert submitter.submissions == [(f"belllabs-run/{run_id}", BlueprintFamily.STAGE_GRAPH, None)]

    with pytest.raises(RunLaunchRejected, match="exactly one family input"):
        await launcher.launch(
            RunLaunchRequest(request_scope=SCOPE, run_id=run_id, family="GoalDirected"), actor()
        )


@pytest.mark.asyncio
async def test_fork_derived_run_waits_for_materialization_and_binds_the_fork_reference() -> None:
    run_control, _ = service()
    admitted = await run_control.admit(request(request_id="launch-fork"))
    run_id = admitted.run_id
    assert run_id is not None
    submitter = RecordingSubmitter()
    pending = RunLaunchService(
        run_control=run_control,
        submitter=submitter,
        forks=NoForkReceipts(),
        materializations=UnmaterializedFork(),
    )
    with pytest.raises(RunLaunchRejected) as rejected:
        await pending.launch(_launch(run_id, _input(run_id)), actor())
    assert rejected.value.code == "fork_not_materialized" and rejected.value.retryable
    assert submitter.submissions == []

    plain = RunLaunchService(
        run_control=run_control,
        submitter=submitter,
        forks=NoForkReceipts(),
        materializations=NoFork(),
    )
    receipt = await plain.launch(_launch(run_id, _input(run_id)), actor())
    assert receipt.parent_run_id is None
    assert fork_semantic_input_binding_ref("fork-1") == "semantic-input:fork:fork-1"


class MissionAwareSubmitter(RecordingSubmitter):
    def __init__(self) -> None:
        super().__init__()
        self.mission_ids: list[str | None] = []

    async def submit(
        self,
        workflow_input: object,
        *,
        workflow_id: str,
        blueprint_family: BlueprintFamily,
        parent_run_id: str | None = None,
        mission_id: str | None = None,
    ) -> WorkflowSubmission:
        self.mission_ids.append(mission_id)
        return await super().submit(
            workflow_input,
            workflow_id=workflow_id,
            blueprint_family=blueprint_family,
            parent_run_id=parent_run_id,
        )


@pytest.mark.asyncio
async def test_launch_passes_the_ledger_mission_to_the_root_search_attributes() -> None:
    """FT-C4: the root starts with `mc_mission_id` from the ledger when it is resolvable."""

    run_control, _ = service()
    admitted = await run_control.admit(request(request_id="launch-mission"))
    run_id = admitted.run_id
    assert run_id is not None
    submitter = MissionAwareSubmitter()

    async def mission_ids(request_scope: str, run: str) -> str | None:
        assert (request_scope, run) == (SCOPE, run_id)
        return "mission-ft-c4"

    launcher = RunLaunchService(
        run_control=run_control, submitter=submitter, mission_ids=mission_ids
    )
    await launcher.launch(_launch(run_id, _input(run_id)), actor())
    assert submitter.mission_ids == ["mission-ft-c4"]


# --- 1.4.4 (F-T4-2): the Temporal identity of the run, recorded right after the submit -----


@pytest.mark.asyncio
async def test_launch_records_the_temporal_ids_and_refuses_a_rebind() -> None:
    run_control, repository = service()
    admitted = await run_control.admit(request(request_id="launch-temporal"))
    run_id = admitted.run_id
    assert run_id is not None
    submitter = RecordingSubmitter()
    launcher = RunLaunchService(
        run_control=run_control, submitter=submitter, temporal_ids=repository
    )
    receipt = await launcher.launch(_launch(run_id, _input(run_id)), actor())
    assert repository.temporal_ids(SCOPE, run_id) == (receipt.workflow_id, "temporal-run-1")
    assert receipt.temporal_run_id == "temporal-run-1"

    other = await run_control.admit(request(request_id="launch-temporal-2"))
    assert other.run_id is not None
    await repository.record_temporal_ids(
        SCOPE, other.run_id, workflow_id=f"belllabs-run/{other.run_id}", temporal_run_id="older"
    )
    with pytest.raises(RunLaunchRejected) as rejected:
        await launcher.launch(_launch(other.run_id, _input(other.run_id)), actor())
    assert rejected.value.code == "temporal_identity_conflict"
    assert repository.temporal_ids(SCOPE, other.run_id) == (
        f"belllabs-run/{other.run_id}",
        "older",
    )
    # Without an explicit recorder the launch service records through the run-control
    # service's own repository (composition needs no extra wiring).
    plain = await run_control.admit(request(request_id="launch-temporal-3"))
    assert plain.run_id is not None
    plain_receipt = await RunLaunchService(run_control=run_control, submitter=submitter).launch(
        _launch(plain.run_id, _input(plain.run_id)), actor()
    )
    assert repository.temporal_ids(SCOPE, plain.run_id) == (
        plain_receipt.workflow_id,
        "temporal-run-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("old_templates", [False, True])
async def test_fork_launch_requires_templates_matching_the_derived_admitted_configuration(
    old_templates: bool,
) -> None:
    from mission_control.application.programs.fork_templates import StageGraphForkTemplateDerivation
    from mission_control.domain.policies.forks import ForkPatchChange, RunForkPatch
    from tests.unit.operations.test_operation_execution import operation_request
    from tests.unit.orchestration.test_fork_templates import MemoryTemplates

    run_control, _ = service()
    successor_digest = "sha256:" + "e" * 64
    template = operation_request().model_copy(
        update={"effective_configuration_digest": DIGEST if old_templates else successor_digest}
    )
    templates = MemoryTemplates()
    templates.stored[(SCOPE, "semantic-input:prepared")] = {"draft/execute/default": template}
    submitter = MissionAwareSubmitter()
    launcher = RunLaunchService(
        run_control=run_control,
        submitter=submitter,
        fork_templates=StageGraphForkTemplateDerivation(templates),
    )
    patch = RunForkPatch.create(
        source_snapshot_id="run-snapshot:" + "a" * 64,
        source_snapshot_digest="sha256:" + "b" * 64,
        target_admission_request_ref="run-request:tenant-1:operator:fork",
        changes=(ForkPatchChange(path="effective_configuration_digest", value=successor_digest),),
        invalidation_frontier=("*",),
    )
    derived_ref = fork_semantic_input_binding_ref("fork-prepared")
    launch = _launch(
        "derived-run",
        _input("derived-run", effective_configuration_digest=successor_digest),
        source_semantic_input_binding_ref="semantic-input:prepared",
    )
    workflow_input = StageGraphRunInput(
        **_input("derived-run", effective_configuration_digest=successor_digest)
    )
    receipt: Any = SimpleNamespace(start_position=None)
    if old_templates:
        with pytest.raises(RunLaunchRejected) as rejected:
            await launcher._apply_stage_graph_fork(
                launch, patch, receipt, workflow_input, derived_ref
            )
        assert rejected.value.code == "fork_templates_mismatch"
        assert (SCOPE, derived_ref) not in templates.stored
    else:
        await launcher._apply_stage_graph_fork(launch, patch, receipt, workflow_input, derived_ref)
        assert templates.stored[(SCOPE, derived_ref)] == {"draft/execute/default": template}
    assert submitter.submissions == []
