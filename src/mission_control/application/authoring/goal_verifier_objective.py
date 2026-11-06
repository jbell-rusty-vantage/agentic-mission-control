"""The Goal Loop verifier's own objective, derived from the authored goal (OVE-169 L1-06).

The verifier template used to carry the executor's objective line, and the context packet the
goal text, which is addressed to the executor. With no rubric, no decision procedure and no
named inputs, a live verifier re-read and searched until the in-turn budget stop (E1 11c9369d,
E4 2a6bc6a7). This objective states what to judge (the executor's declared outputs and where
they arrive), the inputs the executor received and what the verifier cannot read, a rubric from
the goal's criteria and objectives, a decision procedure that ends at one verdict, and the
exact ``GoalVerifierObservation`` fields the reconciler and the convergence policy read
(``GoalDirectedService._parsed``: ``output_contract_ref`` among the frozen contracts;
``GoalDirectedExecution``: a verified completion needs every required obligation accepted).

It is admitted input, like every manifest-authored segment: a privileged segment needs a
published Prompt source in the accepted configuration (``operation_execution.py``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from mission_control.domain.authoring.contracts import GoalDirectedBlueprint
from mission_control.domain.authoring.mission_definition import (
    AcceptanceExpression,
    DefinitionOutput,
    MissionDefinition,
)
from mission_control.domain.context.transfer_builders import subject_input_name
from mission_control.domain.programs.goal_directed_runtime import GoalVerifierObservation

# The run-budget dimensions an in-turn stop enforces (D41), in the order the objective names.
_TURN_DIMENSIONS = ("tool.calls.total", "tokens.total")


def goal_verifier_objective(
    definition: MissionDefinition,
    blueprint: GoalDirectedBlueprint,
    *,
    plan_subjects: Sequence[tuple[str, str]],
    budget_limits: Mapping[str, int],
) -> str:
    """The verifier template's objective text.

    ``plan_subjects`` are the ``(position, output key)`` subjects the verifier's sealed
    transfer plan delivers (empty when its executor cannot submit named outputs, so the
    subject is the packet's ``executor_outputs``).
    """

    outputs = definition.program.outputs
    sections = [
        f"Mission {definition.mission_key} Goal Loop verifier: {blueprint.objective_contract}",
        "You are the independent verifier of one executor iteration: you judge its declared "
        "outputs against the rubric below and return one typed verdict. You never perform the "
        "executor's work. The goal text in the packet's goals_and_criteria is the executor's "
        "instruction: read it as the specification its outputs must meet, not as steps for you. "
        "You cannot submit outputs, register records or change the subject.",
        _subject(outputs, plan_subjects),
        _inputs(definition),
        "## What you cannot read\n"
        "The executor's reasoning, handoff, workspace and scratch files, and anything outside "
        "inputs/ and .mission/ under your role root. A packet row marked unresolved, or one that "
        "names a missionctl command, is not reachable from this sandbox: treat it as "
        "unavailable and do not search for it.",
        _rubric(definition),
        _procedure(budget_limits),
        _verdict(definition, blueprint),
    ]
    return "\n\n".join(sections)


def _output_line(output: DefinitionOutput, binding: str | None) -> str:
    parts = [output.form.value, output.enforcement.value]
    if output.media_type:
        parts.append(output.media_type)
    line = f"- {output.name} ({', '.join(parts)})"
    if binding is not None:
        line += f": binding {binding}, files under inputs/{binding}/"
    validators = [item.validator for item in output.requirements if item.required]
    if validators:
        line += (
            "; host-run requirement "
            + ", ".join(validators)
            + " (Mission Control runs it after your verdict; you do not)"
        )
    return line


def _subject(outputs: Sequence[DefinitionOutput], plan_subjects: Sequence[tuple[str, str]]) -> str:
    planned = {key for _position, key in plan_subjects}
    lines = [
        _output_line(output, subject_input_name(output.key) if output.key in planned else None)
        for output in outputs
    ]
    where = (
        "Each subject is inline in the context packet below or a file it lists (exact paths "
        "in the packet index and .mission/inputs.json). An output with no binding reaches you "
        "only through the packet's executor_outputs rows, when the executor registered it."
    )
    return "## Subject\nThe executor's declared outputs of this iteration, read-only:\n" + (
        "\n".join(lines) + "\n" + where
    )


def _inputs(definition: MissionDefinition) -> str:
    inputs = definition.program.inputs
    if not inputs:
        return (
            "## Inputs the executor received\n"
            "None: this goal has no program or chain inputs. The goal text and the subject are "
            "all there is to read."
        )
    lines = []
    for item in inputs:
        if item.source == "from":
            lines.append(
                f"- {item.name}: chain supply from {item.ref}, delivered to you read-only as "
                "in the executor's first packet (a chain_supply row; its file under inputs/)."
            )
        else:
            lines.append(
                f"- {item.name}: authored {item.source} input; a Goal Loop delivers it to "
                "neither role, so it is not readable."
            )
    return "## Inputs the executor received\n" + "\n".join(lines)


def _acceptance(expression: AcceptanceExpression | None) -> str:
    if expression is None:
        return "your verdict"
    if expression.op == "human":
        return (
            f"human {expression.decision} (a separate held review after your verdict; your "
            "acceptance does not replace it)"
        )
    if expression.op == "assessment":
        return f"assessment {expression.capability_pointer} >= {expression.threshold} (host-run)"
    if expression.op == "schema":
        return f"schema {expression.schema_ref} (host-checked)"
    joined = f" {expression.op} ".join(_acceptance(item) for item in expression.operands)
    return f"({joined})"


def _rubric(definition: MissionDefinition) -> str:
    lines = ["## Rubric"]
    for goal in definition.goals:
        lines.append(f"Obligation {goal.key}:")
        for criterion in definition.criteria:
            if criterion.goal_key != goal.key:
                continue
            evidence = ", ".join(criterion.evidence) or "the subject"
            lines.append(
                f"- criterion {criterion.key}: {criterion.description}. Evidence: {evidence}. "
                f"Acceptance: {_acceptance(criterion.acceptance)}."
            )
        for objective in definition.objectives:
            if objective.goal_key == goal.key:
                lines.append(f"- objective {objective.key}: {objective.description}.")
    required = [item.name for item in definition.program.outputs if item.required]
    expected = [
        item.name for item in definition.program.outputs if item.enforcement.value == "expected"
    ]
    if required:
        lines.append("Required outputs: " + ", ".join(required) + ".")
    if expected:
        lines.append(
            "Expected outputs: "
            + ", ".join(expected)
            + " (a missing expected output is a finding, not a rejection)."
        )
    return "\n".join(lines)


def _procedure(budget_limits: Mapping[str, int]) -> str:
    budget = ", ".join(
        f"{key} {budget_limits[key]}" for key in _TURN_DIMENSIONS if key in budget_limits
    )
    text = (
        "## Decision procedure\n"
        "1 Read each subject once: inline values in the packet first, then each file the "
        "packet lists for it (one read per file). Read an input only when a criterion compares "
        "an output with it.\n"
        "2 Decide each rubric criterion met or unmet from what you read. Do not re-read, list, "
        "glob or grep for more: a missing or unreadable subject makes its obligation unmet.\n"
        "3 Return the verdict at once as your structured answer, GoalVerifierObservation. One "
        "verdict ends your turn; do not re-verify."
    )
    if budget:
        text += (
            f"\nRun budget (executor and verifier together): {budget}. The turn stops at the "
            "cap and the run fails without your verdict."
        )
    return text


def _verdict(definition: MissionDefinition, blueprint: GoalDirectedBlueprint) -> str:
    schema = GoalVerifierObservation.model_fields["schema_version"].default
    obligations = json.dumps(sorted(blueprint.required_obligation_refs))
    contracts = ", ".join(sorted(blueprint.required_output_contracts))
    required = [item.name for item in definition.program.outputs if item.required]
    default = (
        f"output:{required[0]}" if required else sorted(blueprint.required_output_contracts)[0]
    )
    return (
        f"## Verdict: GoalVerifierObservation ({schema})\n"
        '- decision: "accepted" when every criterion is met; "repair_required" when a named '
        'output can be fixed in the next iteration (say what in findings); "rejected" when it '
        'cannot. Do not use "revision_required": it needs a digest-bound Goal Revision only '
        "the host can build.\n"
        "- progress_made: true when the outputs move any criterion closer.\n"
        f"- accepted_obligation_refs: on accepted exactly {obligations}; otherwise [].\n"
        '- unmet_obligations: "output:<name>" for each required output that fails a '
        "criterion; [] on accepted.\n"
        '- findings: one line per criterion, "<criterion key>: met|unmet - <reason citing the '
        'output>".\n'
        "- evidence_refs: the refs or digests of the subjects you read.\n"
        f"- output_contract_ref: exactly one of {contracts} - the output your verdict is "
        f"about (the first unmet one, else {default}).\n"
        "Leave every other field at its default."
    )


__all__ = ["goal_verifier_objective"]
