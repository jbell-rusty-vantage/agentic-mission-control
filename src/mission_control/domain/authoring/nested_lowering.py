"""Deriving and lowering nested family bodies (OVE-176, WI-13); see ``nested_bodies``.

Pure: the parent's compile and the runtime launch of a nested body derive the same
sub-definition from the parent's committed definition, so the body's digests are sealed.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

from mission_control.domain.authoring.manifest import Behavior
from mission_control.domain.authoring.mission_definition import (
    DefinitionBudget,
    DefinitionNode,
    MissionDefinition,
)
from mission_control.domain.authoring.nested_bodies import (
    MAX_NESTING_DEPTH,
    RECURSIVE_BEHAVIORS,
    NestedBodyError,
    NestedExport,
)


def walk(node: DefinitionNode) -> Iterator[DefinitionNode]:
    yield node
    for child in node.nodes:
        yield from walk(child)


def composite(node: DefinitionNode) -> bool:
    """Whether a node below the root executes recursively as its own family."""

    return node.behavior in RECURSIVE_BEHAVIORS


def max_depth(definition: MissionDefinition) -> int:
    authored = definition.policies.governors.depth
    return MAX_NESTING_DEPTH if authored is None else min(authored, MAX_NESTING_DEPTH)


def _goal_of(definition: MissionDefinition, key: str) -> str | None:
    if any(goal.key == key for goal in definition.goals):
        return key
    return next((item.goal_key for item in definition.objectives if item.key == key), None)


def _served_keys(node: DefinitionNode) -> set[str]:
    keys: set[str] = set()
    for item in walk(node):
        keys.update(item.objectives)
        objective = item.body.get("objective")
        if isinstance(objective, str):
            keys.add(objective)
    return keys


def nested_definition(definition: MissionDefinition, node: DefinitionNode) -> MissionDefinition:
    """The sub-definition a nested body executes: the node as the program root, the goals its
    subtree serves, the criteria over its own outputs, the mission's policies and the node's
    own effective budget (what the hosting unit reserves for it, so the child spends nothing
    the parent did not charge).

    Pure and deterministic, so the parent's compile and the runtime launch derive the same body.
    A nested system pursues the enclosing mission's objectives; it introduces no goal.
    """

    served = {goal for key in _served_keys(node) if (goal := _goal_of(definition, key))}
    if not served:
        raise NestedBodyError(
            node.pointer,
            "nested_body_serves_no_goal",
            f"nested body {node.key} serves no objective of the mission",
        )
    outputs = {output.name for item in walk(node) for output in item.outputs}
    keys = {item.key for item in walk(node)}
    exported = tuple(output.name for output in node.outputs)
    criteria = []
    for criterion in definition.criteria:
        if criterion.goal_key not in served:
            continue
        evidence = tuple(name for name in criterion.evidence if name in outputs)
        if criterion.evidence and not evidence:
            # The criterion cites the enclosing program's evidence: within the body it is
            # judged on what the body exports for that goal.
            evidence = exported
        if criterion.evidence and not evidence:
            continue
        criteria.append(criterion.model_copy(update={"evidence": evidence}))
    goals = tuple(goal for goal in definition.goals if goal.key in served)
    return definition.model_copy(
        update={
            "mission_key": f"{definition.mission_key}.{node.key}",
            "title": f"{definition.title} / {node.key}",
            "manifest_pointer": node.pointer,
            "goals": goals,
            "objectives": tuple(item for item in definition.objectives if item.goal_key in served),
            "criteria": tuple(criteria),
            "inputs": tuple(item for item in definition.inputs if item.node_key in keys),
            "program": node,
            "budget": body_budget(definition, node),
            "completion_contract": definition.completion_contract.model_copy(
                update={
                    "goals": tuple(
                        item
                        for item in definition.completion_contract.goals
                        if item.goal_key in served
                    )
                }
            ),
        }
    )


def body_budget(definition: MissionDefinition, node: DefinitionNode) -> DefinitionBudget:
    """The node's effective budget (its environment inherits and narrows the mission's)."""

    budget = node.environment.budget
    if budget is None:
        return definition.budget
    return DefinitionBudget(
        usd=budget.usd,
        tokens=budget.tokens,
        wall_clock_seconds=budget.wall_clock,
        tool_calls=budget.tool_calls,
    )


def spend_reservation(budget: DefinitionBudget) -> dict[str, int]:
    """The spend dimensions a hosting unit reserves for its body (integers, no floats)."""

    found: dict[str, int] = {}
    if budget.tokens is not None:
        found["tokens.total"] = budget.tokens
    if budget.tool_calls is not None:
        found["tool.calls.total"] = budget.tool_calls
    if budget.usd is not None:
        found["currency.estimated_micros"] = int(
            (Decimal(budget.usd) * Decimal(1_000_000)).to_integral_value()
        )
    if budget.wall_clock_seconds is not None:
        found["time.elapsed_ms"] = budget.wall_clock_seconds * 1000
    return found


def nested_definition_at(definition: MissionDefinition, position: str) -> MissionDefinition:
    """The sub-definition at an absolute nested ``position``, derived level by level exactly as
    compile derived it (a segment naming the current root is that root, not a body)."""

    current = definition
    for segment in position.split("/"):
        if segment == current.program.key:
            continue
        node = next((item for item in walk(current.program) if item.key == segment), None)
        if node is None or node is current.program or not composite(node):
            raise NestedBodyError(
                current.program.pointer,
                "nested_body_position_unknown",
                f"no nested body {segment} at position {position}",
            )
        current = nested_definition(current, node)
    if current is definition:
        raise NestedBodyError(definition.program.pointer, "nested_body_position_unknown", position)
    return current


def nested_exports(node: DefinitionNode) -> tuple[NestedExport, ...]:
    """The exports of a composite node: each declared output of the node, final unless the
    node's ``exports`` marks it early, bound to the body obligation that produces it.

    A Goal Loop body produces its own outputs (``<node>.<output>``; its verifier accepts them,
    whatever executes its iterations). A Stage Graph body produces
    them from an inner stage, named by ``from: <stage>.<output>`` or, when unambiguous, by the one
    inner node that declares an output of the same name.
    """

    declared = {
        str(item.get("output")): item
        for item in node.body.get("exports") or ()
        if isinstance(item, dict)
    }
    unknown = sorted(set(declared) - {output.name for output in node.outputs})
    if unknown:
        raise NestedBodyError(
            f"{node.pointer}/exports",
            "nested_export_unknown_output",
            f"exports {unknown} are not declared outputs of {node.key}",
        )
    if not node.outputs:
        raise NestedBodyError(
            f"{node.pointer}/outputs",
            "nested_body_exports_nothing",
            f"nested body {node.key} declares no output to export to its parent",
        )
    inner = {
        f"{item.key}.{output.name}": output.name
        for item in walk(node)
        if item is not node
        for output in item.outputs
    }
    exports = []
    for output in node.outputs:
        entry = declared.get(output.name, {})
        source = entry.get("from")
        if node.behavior is Behavior.GOAL_LOOP:
            if source is not None:
                raise NestedBodyError(
                    f"{node.pointer}/exports",
                    "nested_export_source_unsupported",
                    f"a Goal Loop without a body exports its own output {output.name}",
                )
            source = output.key
        elif source is None:
            matches = [key for key, name in inner.items() if name == output.name]
            if len(matches) != 1:
                raise NestedBodyError(
                    f"{node.pointer}/exports",
                    "nested_export_unbound",
                    f"output {output.name} of {node.key} needs `from: <stage>.<output>` "
                    f"(inner producers: {sorted(matches)})",
                )
            source = matches[0]
        elif source not in inner:
            raise NestedBodyError(
                f"{node.pointer}/exports",
                "nested_export_unknown_source",
                f"export source {source} is not a declared output inside {node.key}",
            )
        timing = entry.get("timing", "final")
        exports.append(
            NestedExport(
                output=output.name,
                source=str(source),
                timing="early" if timing == "early" else "final",
                required=output.required,
            )
        )
    return tuple(exports)


def inherited_inputs(node: DefinitionNode) -> tuple[str, ...]:
    """Bindings inside the body that name a producer outside it (refused at compile until the
    parent's sealed inputs are delivered into the child run)."""

    keys = {item.key for item in walk(node)}
    found: list[str] = []
    for item in walk(node):
        for binding in item.inputs:
            if binding.source != "from" or binding.ref is None:
                continue
            producer = binding.ref.partition(".")[0]
            if producer not in keys:
                found.append(f"{item.key}.{binding.name}")
    return tuple(found)
