"""Fail closed at fresh launch when authored acceptance has no runtime evaluator.

Start applies ``completion_support_issues``. Compilation may still describe and preserve these
contracts, and reports the same refusals as ``start_blockers`` (``launch_acceptance_issues``,
root and nested bodies) with ``startable`` false, so a compile never hides a start refusal.
Provider completion,
JSON output, and an independent generic verifier are not substitutes for evaluation
of a pinned schema, assessment capability, or compound acceptance expression.
"""

from collections.abc import Mapping

from mission_control.domain.authoring.contracts import GoalDirectedBlueprint, StageGraphBlueprint
from mission_control.domain.authoring.manifest import Behavior, ManifestErrorCode, ManifestIssue
from mission_control.domain.authoring.manifest_lowering import lower_mission
from mission_control.domain.authoring.mission_definition import (
    AcceptanceExpression,
    DefinitionNode,
    MissionDefinition,
)
from mission_control.domain.authoring.nested_lowering import nested_definition_at
from mission_control.domain.programs.completion import OutputSchemaBinding
from mission_control.domain.programs.human_gate import resolution_action


def completion_support_issues(
    definition: MissionDefinition,
    blueprint: StageGraphBlueprint | GoalDirectedBlueprint | None = None,
) -> tuple[ManifestIssue, ...]:
    bound_stages = (
        {stage.stage_id: stage for stage in blueprint.stages}
        if isinstance(blueprint, StageGraphBlueprint)
        else {definition.program.key: blueprint}
        if blueprint is not None
        else {}
    )
    bound_criteria = {
        criterion.criterion_key: criterion
        for stage in bound_stages.values()
        for criterion in stage.schema_criteria
    }
    root = definition.program
    issues: list[ManifestIssue] = []
    children = root.nodes if root.behavior is Behavior.STAGE_GRAPH else (root,)
    goal_by_objective = {item.key: item.goal_key for item in definition.objectives}
    owners: dict[str, DefinitionNode] = {}
    for child in children:
        for objective in child.objectives:
            owners[goal_by_objective.get(objective, objective)] = child

    def human_action(node: DefinitionNode) -> str | None:
        if node is root and node.behavior is Behavior.GOAL_LOOP:
            return resolution_action("REVIEW", "approve")
        if node.behavior is Behavior.HUMAN_GATE:
            task = node.body.get("task", {})
            return resolution_action(task.get("kind", "REVIEW"), "approve")
        return None

    def check(
        expression: AcceptanceExpression, pointer: str, *, action: str | None, key: str
    ) -> None:
        if expression.op == "human" and action is not None and expression.decision == action:
            return
        criterion = bound_criteria.get(key)
        if (
            expression.op == "schema"
            and criterion is not None
            and criterion.schema_ref == expression.schema_ref
        ):
            return
        mismatch = (
            f" Human acceptance requires {expression.decision!r}; this task produces {action!r}."
            if expression.op == "human" and action is not None
            else ""
        )
        issues.append(
            ManifestIssue(
                code=ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                pointer=pointer,
                reason="completion_evaluator_unavailable",
                message=(
                    f"Acceptance operator {expression.op!r} has no qualified evaluator at this "
                    "location. The runtime cannot substitute provider success for this contract."
                    + mismatch
                ),
            )
        )

    for goal_index, goal in enumerate(definition.goals):
        owner = owners.get(goal.key, children[-1])
        for criterion_index, criterion in enumerate(
            item for item in definition.criteria if item.goal_key == goal.key
        ):
            check(
                criterion.acceptance,
                f"{definition.manifest_pointer}/goals/{goal_index}/criteria/{criterion_index}/acceptance",
                action=human_action(root if root.behavior is Behavior.GOAL_LOOP else owner),
                key=f"{goal.key}.{criterion.key}",
            )

    def visit(node: DefinitionNode) -> None:
        stage = bound_stages.get(node.key)
        slots = {slot.output_slot_id: slot for slot in stage.output_slots} if stage else {}
        for index, output in enumerate(node.outputs):
            slot = slots.get(output.name)
            supported = (
                slot is not None
                and slot.validation_schema is not None
                and slot.validation_schema.schema_ref == output.schema_ref
            )
            if output.required and output.schema_ref is not None and not supported:
                issues.append(
                    ManifestIssue(
                        code=ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                        pointer=f"{node.pointer}/outputs/{index}/schema",
                        reason="output_schema_validator_unavailable",
                        message=(
                            f"Required output {output.name!r} declares schema "
                            f"{output.schema_ref!r}, "
                            "but no qualified artifact schema validator is bound. Capturing an "
                            "artifact does not establish output validity."
                        ),
                    )
                )
        if node.completion is not None:
            check(
                node.completion,
                f"{node.pointer}/completion/acceptance",
                action=human_action(node),
                key=f"node:{node.key}",
            )
        for child in node.nodes:
            visit(child)

    visit(root)
    return tuple(issues)


def launch_acceptance_issues(
    definition: MissionDefinition,
    blueprint: StageGraphBlueprint | GoalDirectedBlueprint,
    output_schemas: Mapping[str, OutputSchemaBinding] | None = None,
) -> tuple[ManifestIssue, ...]:
    """Every refusal a fresh start would apply to this program (``completion_support_issues``),
    for the root and for each nested body exactly as its own launch derives and checks it
    (``nested_definition_at`` + ``lower_mission`` at its position). Compile reports these as
    blockers so a compile ``ok`` is never refused at start."""

    issues = list(completion_support_issues(definition, blueprint))
    pending = list(blueprint.nested_bodies)
    while pending:
        body = pending.pop(0)
        derived = nested_definition_at(definition, body.position)
        nested = lower_mission(
            derived, output_schemas=output_schemas, position=body.position, depth=body.depth
        ).blueprint
        issues.extend(
            item for item in completion_support_issues(derived, nested) if item not in issues
        )
        pending.extend(nested.nested_bodies)
    return tuple(issues)
