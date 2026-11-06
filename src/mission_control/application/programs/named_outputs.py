"""Settle a stage's exact named submissions before its family consumes output references."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from mission_control.application.outputs.fulfillment import HostAccess, OutputFulfillmentService
from mission_control.application.ports.outputs import OutputContractStore
from mission_control.application.programs.completion_validation import validate_completion
from mission_control.domain.authoring.contracts import StageNode
from mission_control.domain.outputs.contracts import Enforcement, ExactOutput, OutputForm
from mission_control.domain.programs.completion import CompletionValidation
from mission_control.domain.programs.contracts import StageExecutionIdentity


@dataclass(frozen=True)
class NamedStageReconciliation:
    result: dict[str, Any]
    validation: CompletionValidation | None = None
    # L1-02: the fulfilled (accepted) exact revisions bound in ``result``, keyed by their
    # ``output-revision:<id>#digest=<digest>`` ref; route facts read these values, never custody.
    fulfilled: Mapping[str, ExactOutput] = field(default_factory=dict)


class NamedStageOutputs:
    def __init__(self, store: OutputContractStore, fulfillment: OutputFulfillmentService) -> None:
        self._store, self._fulfillment = store, fulfillment

    async def reconcile(
        self,
        scope: str,
        identity: StageExecutionIdentity,
        stage: StageNode,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return (await self.reconcile_with_validation(scope, identity, stage, result)).result

    async def reconcile_with_validation(
        self,
        scope: str,
        identity: StageExecutionIdentity,
        stage: StageNode,
        result: dict[str, Any],
    ) -> NamedStageReconciliation:
        """Use only the current finalized attempt, never an older successful head.

        Legacy schema-bearing artifact stages keep their byte validator when there is no
        finalized structured named submission. Named values are checked against frozen
        stage schemas before promotion; independent requirements remain with fulfillment.
        """
        schema_mode = bool(
            stage.schema_criteria or any(slot.validation_schema for slot in stage.output_slots)
        )
        obligations = tuple(
            item
            for item in await self._store.active_obligations(scope, identity.run_id)
            if item.owner_position == stage.stage_id
        )
        if not obligations:
            return NamedStageReconciliation(result)
        structured_forms = {OutputForm.STRUCTURED, OutputForm.CONTROL_RECORD}
        if schema_mode and not any(item.contract.form in structured_forms for item in obligations):
            return NamedStageReconciliation(result)
        supported_forms = {OutputForm.TEXT, OutputForm.REFERENCE} | (
            structured_forms if schema_mode else set()
        )
        if any(item.contract.form not in supported_forms for item in obligations):
            return NamedStageReconciliation(result)
        by_slot = {item.key.removeprefix(stage.stage_id + "."): item for item in obligations}
        if set(by_slot) != {slot.output_slot_id for slot in stage.output_slots}:
            raise ValueError("named stage promises differ from the admitted output slots")
        current = {}
        for slot, obligation in by_slot.items():
            current[slot] = tuple(
                item
                for item in await (
                    self._store.finalized_subject_outputs(
                        scope,
                        identity.run_id,
                        obligation.key,
                        operation_ref=identity.operation_id,
                        operation_attempt=identity.semantic_attempt,
                        execution_generation=identity.execution_generation,
                    )
                    if schema_mode
                    else self._store.submitted_outputs(
                        scope,
                        identity.run_id,
                        obligation.key,
                        operation_ref=identity.operation_id,
                        operation_attempt=identity.semantic_attempt,
                        execution_generation=identity.execution_generation,
                    )
                )
                if item.obligation_revision == obligation.revision
                and item.run_id == identity.run_id
                and item.obligation_key == obligation.key
            )
        validation = None
        if schema_mode:
            if not any(current.values()):
                # A legacy artifact stage with no finalized named submission keeps its
                # original custody reader and byte/schema validation, unchanged.
                return NamedStageReconciliation(result)
            candidate_bindings = {
                slot: [
                    f"output-revision:{item.revision_id}#digest={item.content_digest}"
                    for item in items
                ]
                for slot, items in current.items()
            }
            candidate_result = {
                **result,
                "output_bindings": candidate_bindings,
                "output_refs": [ref for refs in candidate_bindings.values() for ref in refs],
            }
            validation = await validate_completion(
                None,
                request_scope=scope,
                stage=stage,
                interpreter=None,
                operation_result=candidate_result,
                registered_outputs=current,
                registered_run_id=identity.run_id,
            )
            if validation.status != "satisfied":
                # Exact bytes/criteria are checked BEFORE fulfillment can move any head.
                return NamedStageReconciliation(candidate_result, validation)
        # Never promote a stale sibling attempt merely because its head remains accepted.
        missing = any(
            obligation.enforcement == Enforcement.REQUIRED and not current[slot]
            for slot, obligation in by_slot.items()
        )
        frontier = await self._fulfillment.converge(
            HostAccess(
                scope=scope, actor_ref="stagegraph-worker", origin_ref="mc-host:stage-result"
            ),
            identity.run_id,
            operation_ref=identity.operation_id,
            generation=identity.execution_generation,
            operation_attempt=identity.semantic_attempt,
            execution_generation=identity.execution_generation,
            owner_position=stage.stage_id,
            promote=not missing,
        )
        decisions = (
            {}
            if frontier is None
            else {item.obligation_key: item for item in frontier.fulfillments}
        )
        bindings: dict[str, list[str]] = {}
        for slot, obligation in by_slot.items():
            decision = decisions.get(obligation.key)
            current_ids = {item.revision_id for item in current[slot]}
            eligible = (
                set(decision.eligible_members)
                if (
                    decision is not None
                    and decision.obligation_revision == obligation.revision
                    and decision.disposition == "fulfilled"
                    and set(decision.eligible_members) <= current_ids
                )
                else set()
            )
            bindings[slot] = [
                f"output-revision:{item.revision_id}#digest={item.content_digest}"
                for item in current[slot]
                if item.revision_id in eligible
            ]
        reconciled = {
            **result,
            "output_refs": [ref for refs in bindings.values() for ref in refs],
            "output_bindings": bindings,
            "named_output_fulfillment": None
            if frontier is None
            else {
                "set_id": frontier.set_id,
                "membership_digest": frontier.membership_digest,
                "missing_current": [
                    obligation.key
                    for slot, obligation in by_slot.items()
                    if obligation.enforcement == Enforcement.REQUIRED and not current[slot]
                ],
            },
        }
        fulfilled = {
            f"output-revision:{item.revision_id}#digest={item.content_digest}": item
            for slot, items in current.items()
            for item in items
            if f"output-revision:{item.revision_id}#digest={item.content_digest}" in bindings[slot]
        }
        if validation is not None:
            eligible_outputs = {
                slot: tuple(
                    item
                    for item in items
                    if f"output-revision:{item.revision_id}#digest={item.content_digest}"
                    in bindings[slot]
                )
                for slot, items in current.items()
            }
            validation = await validate_completion(
                None,
                request_scope=scope,
                stage=stage,
                interpreter=None,
                operation_result=reconciled,
                registered_outputs=eligible_outputs,
                registered_run_id=identity.run_id,
            )
        return NamedStageReconciliation(reconciled, validation, fulfilled)
