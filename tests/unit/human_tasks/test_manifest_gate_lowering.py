"""MP-10: example Mission 1's `review` Human Gate lowers onto its compiled Stage Graph."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from temporalio.exceptions import ApplicationError

from mission_control.adapters.temporal.workflows.stagegraph import _human_gates
from mission_control.application.programs.human_gates import (
    goal_human_review,
    stagegraph_human_gates,
)
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.programs.contracts import StageGraphRunInput
from tests.support.manifests.launch_inputs import MISSION_2, compile_programs
from tests.unit.authoring.manifest_launch_fixture import deep_agents_chain

ROOT = Path(__file__).resolve().parents[3]
MISSION_1 = ROOT / "tests/fixtures/manifests/fast-track/01-research-ingestion-deep-agents.yml"


@pytest.fixture(scope="module")
def mission_1():  # type: ignore[no-untyped-def]
    definitions, programs = asyncio.run(compile_programs(MISSION_1.read_text(encoding="utf-8")))
    return definitions[0], programs[0]


def _run_input(blueprint: StageGraphBlueprint, gates: tuple) -> StageGraphRunInput:  # type: ignore[type-arg]
    return StageGraphRunInput(
        run_id="run-1",
        request_scope="tenant-1",
        effective_configuration_digest="sha256:" + "a" * 64,
        workflow_type_digest="sha256:" + "a" * 64,
        blueprint_digest="sha256:" + "a" * 64,
        blueprint=blueprint.model_dump(mode="json"),
        human_gates=gates,
    )


def test_mission_1_review_gate_lowers_without_invented_remediation(mission_1) -> None:  # type: ignore[no-untyped-def]
    definition, program = mission_1
    (gate,) = stagegraph_human_gates(definition)
    assert gate.gate_key == "review"
    assert gate.reviewers == ("owner",)
    assert gate.packet_sources == ("synthesize.claim_table", "synthesize.source_manifest")
    assert gate.on_timeout == "keep_waiting"
    assert gate.remediation_target is None
    assert gate.permitted_decisions(1) == ("approve", "deny")
    blueprint = program.configuration.selected_blueprint
    assert isinstance(blueprint, StageGraphBlueprint)
    assert set(_human_gates(_run_input(blueprint, (gate,)), blueprint)) == {"review"}
    # The Stage Graph root is not a Goal Loop: no goal review is derived from its criteria.
    assert goal_human_review(definition, reviewers=("owner",)) is None


def test_a_declared_remediation_needs_a_stage_and_a_cycle_policy(mission_1) -> None:  # type: ignore[no-untyped-def]
    definition, program = mission_1
    (gate,) = stagegraph_human_gates(definition, remediation={"review": ("synthesize", 2)})
    assert gate.remediation_target == "synthesize" and gate.max_review_rounds == 2
    with pytest.raises(ValueError, match="not a stage"):
        stagegraph_human_gates(definition, remediation={"review": ("nowhere", 2)})
    blueprint = program.configuration.selected_blueprint
    # The frozen manifest lowering emits no workflow cycle policy, so a remediation route
    # is refused at the family start rather than silently dropped.
    assert blueprint.workflow_cycle_policy is None
    with pytest.raises(ApplicationError, match="workflow cycle policy"):
        _human_gates(_run_input(blueprint, (gate,)), blueprint)


def test_the_production_launch_author_lowers_the_manifest_gates(mission_1) -> None:  # type: ignore[no-untyped-def]
    """The production `LaunchInputPort` (MP-02) carries MP-10 gates into the family input:
    `manifest_human_control` is what it applies to the run's committed definition."""

    from mission_control.application.authoring.manifest_launch_inputs import (
        manifest_human_control,
    )

    definition, _program = mission_1
    gates, review = manifest_human_control(definition, "StageGraph")
    assert [gate.gate_key for gate in gates] == ["review"] and review is None
    assert gates[0].reviewers == ("owner",)
    # Mission 1 is a Stage Graph: a GoalDirected start derives no review from it.
    assert manifest_human_control(definition, "GoalDirected") == ((), None)


def test_mission_2_ingestion_review_is_kept_and_assigned_to_the_owner_role() -> None:
    """Recovery 2026-10-09: the chain consumer's `acceptance.human` must start with a review.

    Mission 2's ingestion Goal Loop requires `human: approved` and (like every mission/v1
    Goal Loop) has nowhere to declare a reviewer. The production author must neither refuse
    the consumer nor drop the review: it lowers one goal review gated on the `owner` role.
    """

    from mission_control.application.authoring.manifest_launch_inputs import (
        manifest_human_control,
    )
    from mission_control.domain.programs.human_gate import is_reviewer

    definitions, _programs = asyncio.run(
        compile_programs(deep_agents_chain(MISSION_2.read_text(encoding="utf-8")))
    )
    by_key = {definition.mission_key: definition for definition in definitions}

    assert manifest_human_control(by_key["research"], "GoalDirected") == ((), None)
    gates, review = manifest_human_control(by_key["ingestion"], "GoalDirected")
    assert gates == () and review is not None
    assert review.reviewers == ("owner",) and review.remediation_target == "goal/executor"
    assert is_reviewer(review, "owner", frozenset())
    assert is_reviewer(review, "someone", frozenset({"reviewer:owner"}))
    assert not is_reviewer(review, "someone", frozenset({"reviewer:other"}))
