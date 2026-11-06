"""The live attempt's explicit adoption of an admitted async child output (OVE-184).

`adopt_async_task_output` (``async_subagents.BellLabsAsyncSubagentMiddleware``) calls
:class:`LiveInvocationChildAdopter`, which reads the live invocation the knowledge tools bind
around cognition (its host-built access and owner position) and enters the parent's ordinary
submission act through :class:`AsyncChildOutputAdoption`. The tool result has the knowledge
tools' envelope (``tool``, ``ok``, ``result``, ``refusal``).
"""

from __future__ import annotations

from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from mission_control.application.knowledge.toolset import KnowledgeToolset
from mission_control.application.subordinates.adoption import (
    AdoptionRefused,
    AsyncChildOutputAdoption,
)
from mission_control.domain.execution.contracts import OperationExecutionBinding

ADOPT_TOOL = "adopt_async_task_output"


class LiveInvocationChildAdopter:
    def __init__(
        self,
        toolset: KnowledgeToolset,
        adoption: AsyncChildOutputAdoption,
        parent: OperationExecutionBinding,
    ) -> None:
        self._toolset = toolset
        self._adoption = adoption
        self._parent = parent

    async def adopt(
        self,
        *,
        child_execution_id: str,
        child_name: str,
        obligation_key: str,
        deliverable_id: str | None,
        submission_key: str,
    ) -> dict[str, object]:
        live = CURRENT_INVOCATION.get()
        if live is None:
            return _refusal("NO_LIVE_INVOCATION", "adoption runs only inside the live attempt")
        outcome = await self._adoption.adopt(
            self._parent,
            access=self._toolset.access(await self._toolset.locate(live)),
            position=live.position,
            child_execution_id=child_execution_id,
            child_name=child_name,
            obligation_key=obligation_key,
            deliverable_id=deliverable_id,
            submission_key=submission_key,
        )
        if isinstance(outcome, AdoptionRefused):
            return _refusal(outcome.code, outcome.message)
        ack = outcome.ack
        if ack.status != "accepted" or ack.error is not None:
            error = ack.error
            return _refusal(
                error.code.value if error is not None else "SUBMISSION_REFUSED",
                error.safe_message if error is not None else "the submission was not accepted",
            )
        return {
            "tool": ADOPT_TOOL,
            "ok": True,
            "result": {
                "submission_id": ack.submission_id,
                "obligation": obligation_key,
                "derivation_ref": outcome.derivation_ref,
                "output_digest": outcome.output_digest,
                "revisions": [item.model_dump(mode="json") for item in ack.revisions],
                "next_actions": list(ack.next_actions),
                "note": "Submitted as a draft of your obligation; your own checks still decide it.",
            },
            "refusal": None,
        }


def _refusal(code: str, message: str) -> dict[str, object]:
    return {
        "tool": ADOPT_TOOL,
        "ok": False,
        "result": None,
        "refusal": {"code": code, "message": message},
    }


__all__ = ["ADOPT_TOOL", "LiveInvocationChildAdopter"]
