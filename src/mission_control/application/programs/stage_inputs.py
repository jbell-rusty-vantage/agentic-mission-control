"""Authored stage inputs of a manifest Stage Graph (MP-20, SPEC-02).

A manifest node's ``inputs[]`` entry ``{name, from: "<producer>.<output>", expand}`` names the
binding its consumer reads (``inputs/<name>/``) and the expansion tier of the producer's
accepted output. The lowered blueprint keeps its ``from:<producer>`` dependency slots, so the
digests of compiled definitions and blueprints never change; the authored name and tier travel
in the run input (``StageGraphRunInput.authored_inputs``) and reach the Context Packer with each
admission. Inputs that no sibling stage produces (an ``artifact`` or ``value`` input, or a
chain ``<mission>.<output>`` supply) are not dependency slots and are left out.

OVE-171: every ``from: <sibling>.<output>`` binding is delivered, whether or not the stage also
lists the producer in ``depends_on``: the lowering makes the binding its own dependency, so
there is no ``depends_on``-only side path. ``required: false`` travels as an optional input.
"""

from __future__ import annotations

from mission_control.domain.authoring.manifest import Behavior
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.programs.contracts import StageAuthoredInput


def stagegraph_authored_inputs(definition: MissionDefinition) -> tuple[StageAuthoredInput, ...]:
    """The authored inputs of every stage that a sibling stage's output delivers."""

    root = definition.program
    if root.behavior is not Behavior.STAGE_GRAPH:
        return ()
    children = root.nodes
    keys = {child.key for child in children}
    found: list[StageAuthoredInput] = []
    for child in children:
        for item in child.inputs:
            if item.source != "from" or item.ref is None:
                continue
            producer, _, output = item.ref.partition(".")
            if producer not in keys or producer == child.key or not output:
                continue
            found.append(
                StageAuthoredInput(
                    consumer_stage_id=child.key,
                    producer_stage_id=producer,
                    producer_output_slot_id=output,
                    name=item.name,
                    expand=item.expand.value,
                    required=item.required,
                )
            )
    return tuple(found)


__all__ = ["stagegraph_authored_inputs"]
