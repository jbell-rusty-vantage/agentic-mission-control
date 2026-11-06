"""Recover the exact template binding from the durable Mission Control root input."""

from datetime import timedelta

from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from mission_control.contracts.identities import mission_root_id
from mission_control.domain.programs.contracts import BellLabsRunInput


class TemporalNativeInputBinding:
    def __init__(self, client: Client) -> None:
        self._client = client

    async def __call__(self, scope: str, run_id: str, digest: str) -> tuple[str, str] | None:
        handle = self._client.get_workflow_handle(mission_root_id(scope, run_id))
        events = handle.fetch_history_events(page_size=1, rpc_timeout=timedelta(seconds=10))
        try:
            first = await anext(events)
        except RPCError as exc:
            if exc.status == RPCStatusCode.NOT_FOUND:
                return None
            raise ValueError("native launch history is unavailable") from exc
        except StopAsyncIteration:
            return None
        if not first.HasField("workflow_execution_started_event_attributes"):
            raise ValueError("native launch history has no start binding")
        started = first.workflow_execution_started_event_attributes
        if started.workflow_type.name != "mc.mission_run.v1":
            raise ValueError("native launch history belongs to another workflow type")
        decoded = await self._client.data_converter.decode(
            started.input.payloads, [BellLabsRunInput]
        )
        if len(decoded) != 1 or not isinstance(decoded[0], BellLabsRunInput):
            raise ValueError("native launch input is invalid")
        root = decoded[0]
        root.validate_mission_binding()
        if (root.request_scope, root.run_id, root.effective_configuration_digest) != (
            scope,
            run_id,
            digest,
        ):
            raise ValueError("native launch input differs from admitted run")
        reference = root.family_input.get("semantic_input_binding_ref")
        if not isinstance(reference, str) or not reference:
            return None
        return root.family, reference
