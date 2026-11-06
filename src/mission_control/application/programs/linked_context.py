"""Freeze released linked exports in the ordinary provider-neutral operation binding."""

from mission_control.application.context.linked_transfer import LinkedExportPort
from mission_control.domain.context.transfer_builders import linked_mission
from mission_control.domain.execution.contracts import OperationExecutionRequest


async def attach_linked_context(
    operation: OperationExecutionRequest, exports: LinkedExportPort | None
) -> OperationExecutionRequest:
    selection = operation.transfer
    if exports is None or selection is None:
        return operation
    released = await exports.released_for(
        operation.request_scope, operation.identity.run_id, selection.receiver_position
    )
    if not released:
        return operation
    return OperationExecutionRequest.model_validate(
        {**operation.model_dump(mode="python"), "transfer": linked_mission(selection, released)}
    )
