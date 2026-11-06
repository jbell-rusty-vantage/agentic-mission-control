"""Recursive composition: compiled nested family bodies (OVE-176, WI-13).

OUTPUT-CONTRACTS §9 and 00-EXECUTION_PROGRAM_MODEL §5: a Stage Graph stage whose node is itself a
Goal Loop or a Stage Graph, and a Goal Loop whose executor phase is a subprogram, execute
recursively with their own activation, governor, state and lineage. Flattening is insufficient.

A compiled blueprint carries each such boundary as one closed :class:`NestedBody`:

- ``host_id`` is the parent unit the body replaces: the stage id in a Stage Graph, ``executor``
  in a Goal Loop. The parent still admits that unit (its reservation is the body's allocated
  budget); the body then runs as its own child run, never as the parent's operation.
- ``position`` is the authored structural path (``<stage>/<nested>``), kept for inspection,
  control lineage and the body's own promise positions.
- ``definition_digest`` / ``blueprint_digest`` seal the derived sub-definition
  (``nested_lowering.nested_definition``) and its lowering: the runtime recompiles the body
  from the parent's committed definition and refuses when either digest differs.
- ``exports`` are the only outputs that cross the boundary. Every declared output of the
  composite node is exported (final by default); an ``early`` export is the one an independently
  accepted body output may still carry out of an incomplete or failed composite, without accepting
  the composite. Internal outputs of the body stay internal.

Recursion is bounded statically: ``depth`` counts composite ancestors (a body of the root program
has depth 1) and never exceeds ``max_depth`` (the mission's ``governors.depth`` within the
installation ceiling :data:`MAX_NESTING_DEPTH`). A body that needs a sibling's output from outside
itself, or a family this kernel cannot execute recursively, refuses at compile.

Extension (WI-14 Parallel Swarm, WI-15 Evaluator Optimizer): a new family adds its behavior to
:data:`RECURSIVE_BEHAVIORS` with its family name and a runtime implementation; the boundary,
identity, exports, governor and control propagation stay these.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.authoring.manifest import Behavior

NestedFamily = Literal["StageGraph", "GoalDirected"]
ExportTiming = Literal["final", "early"]
NESTED_BODY_SEMANTICS_V1: Final = "oc-nested-bodies-v1"
# The installation ceiling on nesting depth; a mission's `governors.depth` narrows it.
MAX_NESTING_DEPTH: Final = 4
# The parent unit a Goal Loop's executor-phase body replaces.
GOAL_EXECUTOR_HOST: Final = "executor"
# Behaviors that execute recursively as their own family, and the family each runs as.
RECURSIVE_BEHAVIORS: Final[dict[Behavior, NestedFamily]] = {
    Behavior.GOAL_LOOP: "GoalDirected",
    Behavior.STAGE_GRAPH: "StageGraph",
}


class NestedBodyError(ValueError):
    """A nested body that cannot execute recursively; ``reason`` is the typed refusal."""

    def __init__(self, pointer: str, reason: str, message: str) -> None:
        super().__init__(message)
        self.pointer = pointer
        self.reason = reason


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NestedExport(_Closed):
    """One output crossing the boundary: the body's ``source`` obligation (``<node>.<output>``)
    becomes the parent unit's ``output`` slot."""

    output: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=3, max_length=257, pattern=r"^[^.]+\.[^.]+$")
    timing: ExportTiming = "final"
    required: bool = True
    # The parent's named obligation an accepted export is adopted into (``<owner>.<output>``):
    # the composite stage's own promise, or the hosting Goal Loop's same-named promise; absent
    # when the parent promises nothing for it (the export then feeds the unit's refs only).
    adopt_into: str | None = Field(default=None, min_length=3, max_length=257)


class NestedBody(_Closed):
    semantics: Literal["oc-nested-bodies-v1"] = NESTED_BODY_SEMANTICS_V1
    host_id: str = Field(min_length=1, max_length=128)
    node_key: str = Field(min_length=1, max_length=128)
    position: str = Field(min_length=1, max_length=512)
    behavior: Literal["goal_loop", "stage_graph"]
    family: NestedFamily
    depth: int = Field(ge=1)
    max_depth: int = Field(ge=1, le=MAX_NESTING_DEPTH)
    definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    blueprint_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    exports: tuple[NestedExport, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def _bounded_and_exact(self) -> NestedBody:
        if self.depth > self.max_depth:
            raise ValueError("a nested body is deeper than its governor allows")
        if RECURSIVE_BEHAVIORS[Behavior(self.behavior)] != self.family:
            raise ValueError("a nested body's family differs from its behavior")
        outputs = [item.output for item in self.exports]
        if len(outputs) != len(set(outputs)):
            raise ValueError("a nested body exports each parent output once")
        return self
