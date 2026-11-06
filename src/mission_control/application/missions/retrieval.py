"""Join existing run authorities without contacting a provider or creating another ledger."""

from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from mission_control.application.context.continuation import CheckpointReadService
from mission_control.application.coordinator.coordinator_results import WorkflowResultRepository
from mission_control.application.missions.completion_evidence import (
    CompletionEvidenceCorrupt,
    CompletionEvidenceReader,
)
from mission_control.application.missions.service import MissionControlService
from mission_control.application.programs.orchestration_binding_repository import (
    RunSemanticInputBindingRepository,
)
from mission_control.contracts.contracts import MissionControlRejected, MissionInspection
from mission_control.contracts.run_evidence import (
    CheckpointEvidence,
    CompletionEvidencePage,
    GoalCompletionEvidencePage,
    HandlerInputEvidence,
    InputEvidence,
    NativeTemplateInput,
    ResultEvidence,
    RunEvidence,
    RunInputs,
)
from mission_control.domain.execution.workspace_closure import (
    RunClosureSummary,
    WorkspaceClosureSummary,
)
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.programs.bindings import RunSemanticInputBinding, SemanticHandlerBinding

LiteralInputStatus = Literal["recorded", "not_recorded", "unavailable"]


class RunEvidenceInconsistent(RuntimeError):
    """Durable records disagree or changed while assembling a read; retry/reconcile."""


class NativeInputReader(Protocol):
    async def read(
        self, request_scope: str, run_id: str, configuration_digest: str
    ) -> tuple[NativeTemplateInput, ...]: ...


class RunClosureLister(Protocol):
    """OVE-204 slice 5: the run's Workspace Closure summaries (`PostgresWorkspaceClosures`)."""

    async def list_for_run(
        self, request_scope: str, run_key: str
    ) -> tuple[WorkspaceClosureSummary, ...]: ...


class GoalCompletionReader(Protocol):
    async def read(
        self, scope: str, run_id: str, after: str | None, limit: int
    ) -> GoalCompletionEvidencePage: ...


class RunEvidenceService:
    def __init__(
        self,
        lifecycle: MissionControlService,
        *,
        bindings: RunSemanticInputBindingRepository | None = None,
        results: WorkflowResultRepository | None = None,
        checkpoints: CheckpointReadService | None = None,
        mission_ids: Callable[[str, str], Awaitable[str | None]] | None = None,
        completion: CompletionEvidenceReader | None = None,
        native_inputs: NativeInputReader | None = None,
        goal_completion: GoalCompletionReader | None = None,
        closures: RunClosureLister | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        # OVE-204 slice 5: the run's Workspace Closures, summarized on the evidence.
        self._closures = closures
        self.request_scope = lifecycle.request_scope
        self._bindings = bindings
        self._results = results
        self._checkpoints = checkpoints
        self._mission_ids = mission_ids
        self._completion = completion
        self._native_inputs = native_inputs
        self._goal_completion = goal_completion
        if checkpoints is not None and checkpoints.request_scope != self.request_scope:
            raise ValueError("checkpoint service differs from evidence request scope")

    @staticmethod
    def _authorize(actor: ActorContext) -> None:
        if not {"workflow_run.read", "workflow.result.read"}.issubset(actor.permissions):
            raise MissionControlRejected("unauthorized", "run and result read permissions required")

    async def _binding(self, run_id: str) -> RunSemanticInputBinding | None:
        if self._bindings is None:
            return None
        binding = await self._bindings.get_for_run(request_scope=self.request_scope, run_id=run_id)
        if binding is not None:
            binding = RunSemanticInputBinding.model_validate(binding.model_dump(mode="python"))
            if (binding.request_scope, binding.run_id) != (self.request_scope, run_id):
                raise RunEvidenceInconsistent("input binding belongs to another run")
        return binding

    async def inputs(self, run_id: str, *, actor: ActorContext) -> RunInputs:
        self._authorize(actor)
        inspection = await self._lifecycle.inspect(run_id, actor)
        binding = await self._binding(run_id)
        self._check_binding(inspection, binding)
        native = await self._native(inspection)
        return RunInputs(
            run_id=run_id,
            status=self._input_status(binding, native),
            binding=binding,
            native_templates=native,
        )

    async def completion(
        self,
        run_id: str,
        *,
        actor: ActorContext,
        after_family_version: int = 0,
        limit: int = 100,
    ) -> CompletionEvidencePage:
        self._authorize(actor)
        await self._lifecycle.inspect(run_id, actor)
        return await self._completion_page(run_id, after_family_version, limit)

    async def goal_completion(
        self, run_id: str, *, actor: ActorContext, after: str | None = None, limit: int = 100
    ) -> GoalCompletionEvidencePage:
        self._authorize(actor)
        await self._lifecycle.inspect(run_id, actor)
        if self._goal_completion is None:
            return GoalCompletionEvidencePage(run_id=run_id, status="unavailable")
        try:
            return await self._goal_completion.read(self.request_scope, run_id, after, limit)
        except ValueError as exc:
            raise RunEvidenceInconsistent("goal completion evidence is inconsistent") from exc

    async def _completion_page(
        self, run_id: str, after_family_version: int = 0, limit: int = 100
    ) -> CompletionEvidencePage:
        if after_family_version < 0 or not 1 <= limit <= 100:
            raise ValueError("invalid completion evidence page bounds")
        if self._completion is None:
            return CompletionEvidencePage(run_id=run_id, status="unavailable")
        try:
            page = await self._completion.list(
                self.request_scope,
                run_id,
                after_family_version=after_family_version,
                limit=limit,
            )
        except CompletionEvidenceCorrupt as exc:
            raise RunEvidenceInconsistent("completion evidence is inconsistent") from exc
        if page.run_id != run_id or any(
            item.run_id != run_id or item.request_scope != self.request_scope
            for item in page.decisions
        ):
            raise RunEvidenceInconsistent("completion evidence belongs to another run")
        versions = tuple(item.family_version for item in page.decisions)
        if (
            len(versions) > limit
            or versions != tuple(sorted(set(versions)))
            or any(version <= after_family_version for version in versions)
            or (
                page.next_after_family_version is not None
                and (not versions or page.next_after_family_version != versions[-1])
            )
        ):
            raise RunEvidenceInconsistent("completion evidence cursor is inconsistent")
        return page

    async def _native(self, inspection: MissionInspection) -> tuple[NativeTemplateInput, ...]:
        if self._native_inputs is None:
            return ()
        try:
            return await self._native_inputs.read(
                self.request_scope,
                inspection.projection.run_id,
                inspection.projection.effective_configuration_digest,
            )
        except ValueError as exc:
            raise RunEvidenceInconsistent("native inputs are inconsistent") from exc

    def _input_status(
        self, binding: RunSemanticInputBinding | None, native: tuple[NativeTemplateInput, ...] = ()
    ) -> LiteralInputStatus:
        return (
            "recorded"
            if binding or native
            else "unavailable"
            if self._bindings is None and self._native_inputs is None
            else "not_recorded"
        )

    @staticmethod
    def _check_binding(
        inspection: MissionInspection, binding: RunSemanticInputBinding | None
    ) -> None:
        if binding is not None and binding.effective_configuration_digest != (
            inspection.projection.effective_configuration_digest
        ):
            raise RunEvidenceInconsistent("input binding differs from admitted configuration")

    async def get(self, run_id: str, *, actor: ActorContext) -> RunEvidence:
        self._authorize(actor)
        inspection = await self._lifecycle.inspect(run_id, actor)
        binding = await self._binding(run_id)
        self._check_binding(inspection, binding)
        native = await self._native(inspection)
        record = (
            await self._results.get(self.request_scope, self.request_scope, run_id)
            if self._results is not None
            else None
        )
        if record is not None and (
            (record.request_scope, record.tenant_scope, record.run_id)
            != (self.request_scope, self.request_scope, run_id)
            or inspection.phase != "terminal"
            or record.terminal_outcome != inspection.projection.terminal_outcome
            or (binding is not None and record.blueprint_family.value != binding.blueprint_family)
        ):
            raise RunEvidenceInconsistent("typed result differs from authoritative run")
        views = (
            await self._checkpoints.list(run_id, actor=actor)
            if self._checkpoints is not None
            else ()
        )
        if any(item.run_id != run_id for item in views):
            raise RunEvidenceInconsistent("checkpoint belongs to another run")
        mission_id = (
            await self._mission_ids(self.request_scope, run_id)
            if self._mission_ids is not None
            else None
        )
        completion = await self._completion_page(run_id)
        closures = (
            await self._closures.list_for_run(self.request_scope, run_id)
            if self._closures is not None
            else None
        )
        # Independent stores are not an atomic database snapshot. Detect a moving ledger
        # instead of returning evidence under a stale phase/generation/version.
        latest = await self._lifecycle.inspect(run_id, actor)
        if latest.version != inspection.version:
            raise RunEvidenceInconsistent("run changed during evidence retrieval; retry")
        return RunEvidence(
            run_id=run_id,
            mission_id=mission_id,
            request_scope=self.request_scope,
            inspection=inspection,
            completion=completion,
            inputs=InputEvidence(
                status=self._input_status(binding, native),
                binding_id=binding.binding_id if binding else None,
                binding_digest=binding.binding_digest if binding else None,
                handlers=_handlers(binding) if binding else (),
                native_template_count=len(native),
            ),
            result=ResultEvidence(
                status=(
                    "unavailable"
                    if self._results is None
                    else "recorded"
                    if record is not None
                    else "missing_terminal_result"
                    if inspection.phase == "terminal"
                    else "pending"
                ),
                record=record,
            ),
            checkpoints_status=(
                "unavailable"
                if self._checkpoints is None
                else "recorded"
                if views
                else "not_recorded"
            ),
            checkpoints=tuple(
                CheckpointEvidence(
                    checkpoint_id=item.checkpoint_id,
                    checkpoint_digest=item.checkpoint_digest,
                    validator_result=item.validator_result,
                    sealed_at=item.sealed_at,
                    transfer_status=item.transfer_status,
                    workspace_snapshot_ref=_reference(item.checkpoint, "workspace_snapshot_ref"),
                    sandbox_snapshot_ref=_reference(item.checkpoint, "sandbox_snapshot_ref"),
                    context_packet_ref=_reference(item.checkpoint, "context_packet_ref"),
                )
                for item in views
            ),
            closures_status=(
                "unavailable" if closures is None else "recorded" if closures else "not_recorded"
            ),
            closures=RunClosureSummary.of(closures) if closures else None,
        )


def _reference(body: dict[str, object], key: str) -> str | None:
    value = body.get(key)
    return value if isinstance(value, str) else None


def _handlers(binding: RunSemanticInputBinding) -> tuple[HandlerInputEvidence, ...]:
    routes: list[tuple[str, SemanticHandlerBinding]] = [
        (f"stage:{item.stage_id}", item.handler) for item in binding.stage_handlers
    ]
    routes.extend(
        (f"operation:{item.operation_class}", item.handler)
        for item in binding.goal_operation_handlers
    )
    routes.extend(
        (role, handler)
        for role, handler in (
            ("workflow_evaluator", binding.workflow_evaluator),
            ("goal_verifier", binding.goal_verifier),
            ("goal_handoff", binding.goal_handoff),
        )
        if handler is not None
    )
    return tuple(
        HandlerInputEvidence(
            role=role,
            handler_ref=handler.exact_handler_ref,
            schema_ref=handler.input.schema_ref,
            payload_digest=handler.input.payload_digest,
            output_contract_ref=handler.output_contract_ref,
            operation_execution_binding_ref=handler.operation_execution_binding_ref,
        )
        for role, handler in routes
    )
