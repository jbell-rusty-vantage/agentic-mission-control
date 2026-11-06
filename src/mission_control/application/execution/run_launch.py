"""The governed API-to-Temporal launch of an admitted run (RRM-009).

`POST /run-control/v1/run-requests` only admits (REQ-CP-RUN-001). `RunLaunchService` is the
production step that starts the admitted run's `BellLabsRunWorkflow`: it binds the caller's
family input to the admitted authority (scope, run, effective configuration, Workflow Type,
run version, blueprint digest), derives a fork's parent and patched templates from the fork
receipt (REQ-CP-EXEC-012, RRM-006), and submits through the production submitter, whose
root start carries the Search Attributes (REQ-CP-EXEC-015) and whose duplicate-start policy
makes a second launch of the same pending run idempotent.

Nothing here is company- or fixture-specific.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from mission_control.application.execution.run_control_repository import (
    TemporalIdentityConflict,
    TemporalIdentityRecorder,
)
from mission_control.application.execution.service import RunControlService
from mission_control.application.programs.fork_templates import ForkPatchNotApplicable
from mission_control.application.recovery.run_forks import ForkMaterializationStore
from mission_control.application.recovery.runtime_recovery import ForkRepository
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import GoalDirectedBlueprint, StageGraphBlueprint
from mission_control.domain.coordinator.launch import (
    BlueprintFamily,
    LaunchIdempotencyConflict,
    WorkflowSubmission,
)
from mission_control.domain.outputs.contracts import OutputPromiseSet
from mission_control.domain.policies.contracts import ActorContext, RunPhase, RunProjection
from mission_control.domain.policies.forks import RunForkPatch, RunForkReceipt, RunForkRequest
from mission_control.domain.programs.contracts import (
    GoalDirectedRunInput,
    GoalDirectedStartPosition,
    StageGraphRunInput,
    StageGraphStartPosition,
)

LAUNCH_PERMISSION = "workflow_run.start"
GOAL_OBJECTIVE_PATH = "goal.objective"
STAGE_OBJECTIVE_PREFIX = "stage_objectives."
STAGE_INPUT_ADAPTER: TypeAdapter[StageGraphRunInput] = TypeAdapter(StageGraphRunInput)
GOAL_INPUT_ADAPTER: TypeAdapter[GoalDirectedRunInput] = TypeAdapter(GoalDirectedRunInput)


def fork_semantic_input_binding_ref(fork_request_id: str) -> str:
    """The derived run's semantic input binding reference, bound to the fork request."""

    return f"semantic-input:fork:{fork_request_id}"


class RunLaunchRejected(ValueError):
    """The launch does not bind the admitted authority, or the run cannot start yet."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class TemporalClusterIdentity:
    """The Temporal cluster a launch service submits to (MP-22, `mc.run_cluster_binding.v1`).

    `cluster_id` is the operator's label (`<target>:<address>/<namespace>` by default); the
    physical identity compared at launch is the address and namespace pair.
    """

    cluster_id: str
    target: str
    address: str
    namespace: str
    task_queue: str

    def same_cluster(self, other: TemporalClusterIdentity) -> bool:
        return (self.address, self.namespace) == (other.address, other.namespace)


@dataclass(frozen=True)
class RunClusterBinding:
    run_id: str
    workflow_id: str
    cluster: TemporalClusterIdentity
    recorded_at: datetime


class RunClusterBindingPort(Protocol):
    """Write-once: the first admitted launch binds the run; later binds return the stored row."""

    async def bind(
        self,
        request_scope: str,
        run_id: str,
        *,
        workflow_id: str,
        cluster: TemporalClusterIdentity,
        now: datetime,
    ) -> RunClusterBinding: ...


class RunLaunchRequest(BaseModel):
    """The caller's family input for one admitted run; every identity is verified."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_scope: str = Field(min_length=1, max_length=256)
    run_id: str = Field(min_length=1, max_length=512)
    family: Literal["StageGraph", "GoalDirected"]
    stagegraph: dict[str, Any] | None = None
    goal_directed: dict[str, Any] | None = None
    # A fork launch names prepared templates for its admitted ERC. With an unchanged ERC
    # these are the source run's; a configuration patch needs freshly compiled templates.
    source_semantic_input_binding_ref: str | None = Field(default=None, min_length=1)
    # FT-E3/G7: the mission the run executes; the root then starts with `mc_mission_id`.
    mission_id: str | None = Field(default=None, min_length=1, max_length=128)


class RunLaunchReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    request_scope: str
    family: Literal["StageGraph", "GoalDirected"]
    workflow_id: str
    temporal_run_id: str | None
    semantic_input_binding_ref: str
    parent_run_id: str | None = None
    fork_request_id: str | None = None
    accepted_run_version: int


class RunWorkflowSubmitter(Protocol):
    async def submit(
        self,
        workflow_input: object,
        *,
        workflow_id: str,
        blueprint_family: BlueprintFamily,
        parent_run_id: str | None = None,
        mission_id: str | None = None,
    ) -> WorkflowSubmission: ...


class ForkTemplateDerivationPort(Protocol):
    """Applies a fork patch's semantic-input changes to the derived run's templates."""

    async def derive_stagegraph(
        self,
        *,
        request_scope: str,
        source_semantic_input_binding_ref: str,
        derived_semantic_input_binding_ref: str,
        patch: RunForkPatch,
        expected_configuration_digest: str,
    ) -> tuple[str, ...]: ...


class MissionIdResolver(Protocol):
    """FT-C4: the ledger mission of a run, set as `mc_mission_id` on the root at start."""

    async def __call__(self, request_scope: str, run_id: str) -> str | None: ...


class PrerequisiteLaunchGuard(Protocol):
    async def __call__(self, request_scope: str, run_id: str) -> None: ...


class PromiseLaunchRegistrar(Protocol):
    """OVE-166/WI-02: registers the admitted blueprint's named promises for the run
    (idempotent); raises ``RunLaunchRejected`` when the run registered another set."""

    async def __call__(
        self,
        request_scope: str,
        run_id: str,
        configuration_digest: str,
        promises: OutputPromiseSet,
    ) -> None: ...


class RunLaunchService:
    def __init__(
        self,
        *,
        run_control: RunControlService,
        submitter: RunWorkflowSubmitter,
        forks: ForkRepository | None = None,
        materializations: ForkMaterializationStore | None = None,
        fork_templates: ForkTemplateDerivationPort | None = None,
        mission_ids: MissionIdResolver | None = None,
        cluster_bindings: RunClusterBindingPort | None = None,
        cluster: TemporalClusterIdentity | None = None,
        prerequisites: PrerequisiteLaunchGuard | None = None,
        temporal_ids: TemporalIdentityRecorder | None = None,
        promises: PromiseLaunchRegistrar | None = None,
    ) -> None:
        self._promises = promises
        if (cluster_bindings is None) != (cluster is None):
            raise ValueError("cluster bindings and the submitting cluster are composed together")
        self._cluster_bindings = cluster_bindings
        self._cluster = cluster
        # 1.4.4 (F-T4-2): the run-control repository records `mission_run.temporal_*`
        # right after the submit; absent, the columns stay NULL (and `run inspect` says so).
        if temporal_ids is None:
            candidate = getattr(run_control, "repository", None)
            if candidate is not None and hasattr(candidate, "record_temporal_ids"):
                temporal_ids = candidate
        self._temporal_ids = temporal_ids
        self._mission_ids = mission_ids
        self._run_control = run_control
        self._submitter = submitter
        self._forks = forks
        self._materializations = materializations
        self._fork_templates = fork_templates
        self._prerequisites = prerequisites

    def configure_promises(self, registrar: PromiseLaunchRegistrar) -> None:
        """Trusted composition registers the admitted promises on every launch route."""
        self._promises = registrar

    def configure_prerequisites(self, check: PrerequisiteLaunchGuard) -> None:
        """Trusted composition shares the manifest preflight with every launch route."""
        self._prerequisites = check

    async def launch(self, request: RunLaunchRequest, actor: ActorContext) -> RunLaunchReceipt:
        if LAUNCH_PERMISSION not in actor.permissions:
            raise RunLaunchRejected("unauthorized", f"{LAUNCH_PERMISSION} is required")
        run = await self._run_control.get_run(request.request_scope, request.run_id)
        if run.phase != RunPhase.PENDING:
            raise RunLaunchRejected(
                "run_not_pending",
                f"the run is {run.phase.value}; only a pending admitted run can be launched",
            )
        family, workflow_input = self._validated_input(request, run)
        if self._prerequisites is not None:
            contextual = getattr(type(self._prerequisites), "require_launch", None)
            if contextual is not None:
                await contextual(self._prerequisites, request, workflow_input)
            else:
                await self._prerequisites(request.request_scope, request.run_id)
        # The family settles exactly the baseline it is told about (GoalDirected at closing),
        # so the input must carry the admitted baseline reservation, never another amount.
        budget = await self._run_control.get_budget(request.request_scope, request.run_id)
        if dict(workflow_input.baseline_reservation) != dict(
            budget.reservations.get("baseline", {})
        ):
            raise RunLaunchRejected(
                "budget_mismatch",
                "family input does not carry the admitted baseline reservation",
            )
        await self.register_promises(request.request_scope, run.run_id, workflow_input)
        fork = await self._fork_of(request)
        parent_run_id: str | None = None
        fork_request_id: str | None = None
        if fork is not None:
            fork_request, receipt = fork
            fork_request_id = fork_request.request_id
            parent_run_id = receipt.source_run_id
            workflow_input = await self._apply_fork(request, fork_request, receipt, workflow_input)
        # FT-E3 passes the mission explicitly; otherwise FT-C4 looks it up for visibility.
        mission_id = request.mission_id
        if mission_id is None and self._mission_ids is not None:
            mission_id = await self._mission_ids(request.request_scope, run.run_id)
        workflow_id = f"belllabs-run/{run.run_id}"
        await self._bind_cluster(request.request_scope, run.run_id, workflow_id)
        try:
            extra: dict[str, str] = {"mission_id": mission_id} if mission_id is not None else {}
            submission = await self._submitter.submit(
                workflow_input,
                workflow_id=workflow_id,
                blueprint_family=family,
                parent_run_id=parent_run_id,
                **extra,
            )
        except LaunchIdempotencyConflict as error:
            raise RunLaunchRejected(error.code, str(error)) from error
        if self._temporal_ids is not None:
            try:
                await self._temporal_ids.record_temporal_ids(
                    request.request_scope,
                    run.run_id,
                    workflow_id=submission.workflow_id,
                    temporal_run_id=submission.temporal_run_id,
                )
            except TemporalIdentityConflict as error:
                raise RunLaunchRejected("temporal_identity_conflict", str(error)) from error
        return RunLaunchReceipt(
            run_id=run.run_id,
            request_scope=run.request_scope,
            family=request.family,
            workflow_id=submission.workflow_id,
            temporal_run_id=submission.temporal_run_id,
            semantic_input_binding_ref=workflow_input.semantic_input_binding_ref,
            parent_run_id=parent_run_id,
            fork_request_id=fork_request_id,
            accepted_run_version=run.version,
        )

    async def register_promises(self, request_scope: str, run_id: str, workflow_input: Any) -> None:
        """The admitted blueprint's named promises exist before any invocation of the run can
        submit or receive inputs through a sealed transfer plan (OVE-166, WI-02). The blueprint
        is the admitted one (its configuration digest is checked first); a conflicting set
        refuses as ``promises_refused``, and a route with no registrar never launches a run
        that promises named outputs (``promises_unwired``)."""

        promised = workflow_input.blueprint.get("output_promises")
        if promised is None:
            return
        if self._promises is None:
            raise RunLaunchRejected(
                "promises_unwired",
                "the run promises named outputs but this launch route registers none",
            )
        await self._promises(
            request_scope,
            run_id,
            workflow_input.effective_configuration_digest,
            OutputPromiseSet.model_validate(promised),
        )

    async def _bind_cluster(self, request_scope: str, run_id: str, workflow_id: str) -> None:
        """MP-22: a run launches only in the cluster its first admitted launch bound it to.

        The binding is written before the submit (write-once, the run's tenant scope). A
        service bound to another cluster (an outage drill, a second installation) is refused
        instead of starting a second copy of the mission; there is no automatic replay.
        """

        if self._cluster_bindings is None or self._cluster is None:
            return
        bound = await self._cluster_bindings.bind(
            request_scope,
            run_id,
            workflow_id=workflow_id,
            cluster=self._cluster,
            now=datetime.now(UTC),
        )
        if not bound.cluster.same_cluster(self._cluster):
            raise RunLaunchRejected(
                "run_bound_to_other_cluster",
                f"run {run_id} is bound to Temporal cluster {bound.cluster.cluster_id} "
                f"({bound.cluster.address}/{bound.cluster.namespace}); this service submits to "
                f"{self._cluster.cluster_id} ({self._cluster.address}/{self._cluster.namespace})",
            )

    def _validated_input(
        self, request: RunLaunchRequest, run: RunProjection
    ) -> tuple[BlueprintFamily, StageGraphRunInput | GoalDirectedRunInput]:
        payload = request.stagegraph if request.family == "StageGraph" else request.goal_directed
        if payload is None or (
            (request.stagegraph is not None) == (request.goal_directed is not None)
        ):
            raise RunLaunchRejected(
                "invalid_family_input", "exactly one family input must match the declared family"
            )
        try:
            workflow_input: StageGraphRunInput | GoalDirectedRunInput = (
                STAGE_INPUT_ADAPTER.validate_python(payload)
                if request.family == "StageGraph"
                else GOAL_INPUT_ADAPTER.validate_python(payload)
            )
        except (ValueError, TypeError) as error:
            raise RunLaunchRejected("invalid_family_input", str(error)) from error
        if workflow_input.run_id != run.run_id or workflow_input.request_scope != run.request_scope:
            raise RunLaunchRejected("identity_mismatch", "family input names another run or scope")
        if workflow_input.effective_configuration_digest != run.effective_configuration_digest:
            raise RunLaunchRejected(
                "configuration_mismatch",
                "family input is not bound to the admitted effective configuration",
            )
        if workflow_input.initial_run_version != run.version:
            raise RunLaunchRejected(
                "stale_run_version",
                f"family input binds run version {workflow_input.initial_run_version}, "
                f"the admitted run is at {run.version}",
            )
        if workflow_input.execution_epoch != 1:
            raise RunLaunchRejected("invalid_family_input", "a launch starts execution epoch 1")
        if not workflow_input.semantic_input_binding_ref:
            raise RunLaunchRejected(
                "invalid_family_input", "family input requires its semantic input binding ref"
            )
        if isinstance(workflow_input, StageGraphRunInput):
            if workflow_input.workflow_type_digest != run.workflow_type_ref.digest:
                raise RunLaunchRejected(
                    "configuration_mismatch", "family input names another Workflow Type"
                )
            try:
                blueprint: StageGraphBlueprint | GoalDirectedBlueprint = (
                    StageGraphBlueprint.model_validate(workflow_input.blueprint)
                )
            except ValueError as error:
                raise RunLaunchRejected("invalid_family_input", str(error)) from error
            family = BlueprintFamily.STAGE_GRAPH
        else:
            if run.request_scope.startswith("mc/"):
                if workflow_input.workflow_type_digest not in {"", run.workflow_type_ref.digest}:
                    raise RunLaunchRejected(
                        "configuration_mismatch", "family input names another Workflow Type"
                    )
                workflow_input = replace(
                    workflow_input, workflow_type_digest=run.workflow_type_ref.digest
                )
            try:
                blueprint = GoalDirectedBlueprint.model_validate(workflow_input.blueprint)
            except ValueError as error:
                raise RunLaunchRejected("invalid_family_input", str(error)) from error
            family = BlueprintFamily.GOAL_DIRECTED
        if sha256_digest(blueprint) != workflow_input.blueprint_digest:
            raise RunLaunchRejected(
                "configuration_mismatch", "blueprint digest does not match the frozen blueprint"
            )
        return family, workflow_input

    async def _fork_of(
        self, request: RunLaunchRequest
    ) -> tuple[RunForkRequest, RunForkReceipt] | None:
        if self._materializations is None or self._forks is None:
            return None
        fork = await self._materializations.fork_of_run(request.request_scope, request.run_id)
        if fork is None:
            return None
        if not fork.materialized:
            raise RunLaunchRejected(
                "fork_not_materialized",
                "a fork-derived run starts only once its fork is materialized",
                retryable=True,
            )
        fork_request = await self._forks.get_request(request.request_scope, fork.fork_request_id)
        receipt = await self._forks.get(request.request_scope, fork.fork_request_id)
        if (
            fork_request is not None
            and receipt is None
            and fork_request.patch.cognitive_seed is not None
        ):
            # Tracing Stage 3 (R2-2): a seeded fork records its receipt only once the seed
            # head is in place; until then the derived unit would start without its seed.
            raise RunLaunchRejected(
                "fork_seed_pending",
                "the fork's cognitive seed is not in place yet; retry the fork, then the launch",
                retryable=True,
            )
        if fork_request is None or receipt is None or receipt.target_run_id != request.run_id:
            raise RunLaunchRejected(
                "fork_lineage_missing", "the fork request or receipt of this run is unavailable"
            )
        return fork_request, receipt

    async def _apply_fork(
        self,
        request: RunLaunchRequest,
        fork_request: RunForkRequest,
        receipt: RunForkReceipt,
        workflow_input: StageGraphRunInput | GoalDirectedRunInput,
    ) -> StageGraphRunInput | GoalDirectedRunInput:
        """The derived input bound to the fork: the patched templates (Stage Graph), the
        patched objective and the minted revision (Goal Directed), and the start position
        the fork decided (1.4.4, TR-D13/TR-D14), filled here or equal when the caller set it."""

        expected_ref = fork_semantic_input_binding_ref(fork_request.request_id)
        if workflow_input.semantic_input_binding_ref != expected_ref:
            raise RunLaunchRejected(
                "fork_binding_mismatch",
                f"a fork-derived run binds its semantic input as {expected_ref}",
            )
        if isinstance(workflow_input, StageGraphRunInput):
            return await self._apply_stage_graph_fork(
                request, fork_request.patch, receipt, workflow_input, expected_ref
            )
        return self._apply_goal_fork(fork_request.patch, receipt, workflow_input)

    async def _apply_stage_graph_fork(
        self,
        request: RunLaunchRequest,
        patch: RunForkPatch,
        receipt: RunForkReceipt,
        workflow_input: StageGraphRunInput,
        derived_ref: str,
    ) -> StageGraphRunInput:
        """The patched templates and the fork's Stage Graph start position (TR-D13)."""

        if request.source_semantic_input_binding_ref is None:
            raise RunLaunchRejected(
                "fork_source_templates_required",
                "a StageGraph fork launch names the source run's semantic input binding",
            )
        if self._fork_templates is None:
            raise RunLaunchRejected(
                "fork_templates_unavailable", "fork template derivation is not composed"
            )
        try:
            await self._fork_templates.derive_stagegraph(
                request_scope=request.request_scope,
                source_semantic_input_binding_ref=request.source_semantic_input_binding_ref,
                derived_semantic_input_binding_ref=derived_ref,
                patch=patch,
                expected_configuration_digest=workflow_input.effective_configuration_digest,
            )
        except ForkPatchNotApplicable as error:
            raise RunLaunchRejected("fork_templates_mismatch", str(error)) from error
        start = receipt.start_position
        if start is None:
            return workflow_input
        stage_start = StageGraphStartPosition(
            workflow_cycle_ordinal=start.workflow_cycle_ordinal or 0,
            stage_cycle_ordinals=dict(start.stage_cycle_ordinals),
            stage_objectives=dict(start.stage_objectives),
        )
        if workflow_input.start_position not in (None, stage_start):
            raise RunLaunchRejected(
                "fork_start_position_mismatch",
                "the derived StageGraph input names a start position the fork did not decide",
            )
        return replace(workflow_input, start_position=stage_start)

    @staticmethod
    def _apply_goal_fork(
        patch: RunForkPatch, receipt: RunForkReceipt, workflow_input: GoalDirectedRunInput
    ) -> GoalDirectedRunInput:
        """The patched objective, the minted revision and the Goal Directed start position
        (TR-D14)."""

        change = patch.change(GOAL_OBJECTIVE_PATH)
        if change is not None and workflow_input.initial_revision.objective != change.value:
            raise RunLaunchRejected(
                "fork_patch_mismatch",
                "the derived GoalDirected input does not carry the patched goal objective",
            )
        minted = receipt.derived_goal_revision_id
        if minted is not None and workflow_input.initial_revision.revision_id != minted:
            raise RunLaunchRejected(
                "fork_revision_mismatch",
                "the derived GoalDirected input must carry the fork's derived Goal Revision id "
                f"({minted}) as its initial revision",
            )
        start = receipt.start_position
        if start is None:
            return workflow_input
        goal_start = GoalDirectedStartPosition(
            goal_iteration=start.goal_iteration or 1,
            session_generation=start.session_generation or 1,
            agent_run=start.agent_run or 1,
        )
        if workflow_input.start_position not in (None, goal_start):
            raise RunLaunchRejected(
                "fork_start_position_mismatch",
                "the derived GoalDirected input names a start position the fork did not decide",
            )
        return replace(workflow_input, start_position=goal_start)


__all__ = [
    "LAUNCH_PERMISSION",
    "ForkTemplateDerivationPort",
    "RunClusterBinding",
    "RunClusterBindingPort",
    "RunLaunchReceipt",
    "RunLaunchRejected",
    "RunLaunchRequest",
    "RunLaunchService",
    "RunWorkflowSubmitter",
    "TemporalClusterIdentity",
    "fork_semantic_input_binding_ref",
]
