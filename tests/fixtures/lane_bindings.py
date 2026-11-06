"""Test helpers for OC-R2's one lane slot.

Production code seals a binding at the one place its lane produces it; a test that builds an
`OperationExecutionRequest` (or a payload or `model_copy` update for one) from a typed binding
spreads `**lane_fields(binding)` where it used to pass the removed typed slot. `LANE_REBINDERS`
is the families' rebind port as the worker composes it (`deployment_composition`).
"""

from __future__ import annotations

from typing import Any

from mission_control.adapters.deep_agents.binding import DEEP_AGENTS_LANE_BINDINGS
from mission_control.application.resolution.lane_bindings import LaneRebinders
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import (
    DEEP_AGENT_BINDING_SCHEMA,
    DeepAgentExecutionBinding,
)
from mission_control.domain.execution.lanes import CursorExecutionBinding, LaneDispatch

TypedLaneBinding = DeepAgentExecutionBinding | CursorExecutionBinding | ProviderExecutionBinding

LANE_REBINDERS = LaneRebinders({"deep_agents": DEEP_AGENTS_LANE_BINDINGS})


class FakeSealedBinding:
    """A unit test's stand-in typed binding (a `SimpleNamespace` of the fields a fake reads),
    carried as if sealed: the lane's decode hands the stand-in back unchanged."""

    digest = "sha256:" + "f" * 64

    def __init__(
        self,
        fake: Any,
        *,
        lane_profile: str = "deep_agents",
        schema_id: str = DEEP_AGENT_BINDING_SCHEMA,
    ) -> None:
        self._fake = fake
        self.lane_profile = lane_profile
        self.schema_id = schema_id

    def unseal(self, model: Any, *, schema_ids: Any) -> Any:
        del model, schema_ids
        return self._fake


def lane_fields(
    binding: TypedLaneBinding | Any | None,
    *,
    lane_profile: str = "deep_agents",
    schema_id: str = DEEP_AGENT_BINDING_SCHEMA,
) -> dict[str, Any]:
    """`lane_binding` and `lane_dispatch` for a typed binding (nothing for `None`).

    A `SimpleNamespace` stand-in (unit fakes; a Deep Agents binding unless another profile and
    schema are named) is carried by a `FakeSealedBinding` with the dispatch its fields imply.
    """

    if binding is None:
        return {}
    if isinstance(binding, TypedLaneBinding):
        return {"lane_binding": binding.seal(), "lane_dispatch": binding.lane_dispatch()}
    children = getattr(binding, "async_subagents", ())
    dispatch = LaneDispatch(
        task_queue=getattr(binding, "task_queue", None),
        execution_generation=getattr(binding, "execution_generation", 1),
        heartbeat_class="deep_agent_async_children" if children else "deep_agent",
    )
    if not hasattr(binding, "lane_dispatch"):
        # The stand-in states the dispatch it is carried with (`carried_by` compares them).
        binding.lane_dispatch = lambda *_generation: dispatch
    return {
        "lane_binding": FakeSealedBinding(binding, lane_profile=lane_profile, schema_id=schema_id),
        "lane_dispatch": dispatch,
    }


__all__ = ["LANE_REBINDERS", "FakeSealedBinding", "TypedLaneBinding", "lane_fields"]
