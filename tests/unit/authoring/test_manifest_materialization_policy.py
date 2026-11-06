"""MO-02: the manifest's ``materialization.conflicts`` policy reaches the sealed lane bindings.

Declared on the mission environment, it compiles into the node selections and the launch
author seals it on every ``mc.execution_binding.v2`` and ``mc.cursor_binding.v2`` it writes,
where the lane's layering reads it. Undeclared, it is absent from the bindings' dumps and
digests (every binding sealed before it keeps its bytes).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mission_control.domain.agentic_components.layering import (
    ConflictPolicy,
    MaterializationPolicy,
)
from mission_control.domain.authoring.manifest_v2 import manifest_v2_json_schema
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.lanes import CursorExecutionBinding
from tests.unit.authoring.test_manifest_v2_launch import (
    EXAMPLES,
    blockers,
    compile_yaml,
    compiled_ok,
    edited,
    example,
    templates_of,
)

CURSOR_LOCAL = EXAMPLES / "cursor-local.stage-graph.mission.yml"


def _declare(conflicts: str) -> Any:
    def change(document: dict[str, Any]) -> None:
        document["mission"]["environment"]["materialization"] = {"conflicts": conflicts}

    return change


def _bindings(text: str) -> list[Any]:
    compilation = compiled_ok(text)
    found: list[Any] = []
    for definition, program in zip(compilation.definitions, compilation.programs, strict=True):
        for template in templates_of(program, definition, None).values():
            binding = ProviderExecutionBinding.carried_by(
                template
            ) or CursorExecutionBinding.carried_by(template)
            if binding is not None:
                found.append(binding)
    assert found
    return found


@pytest.mark.parametrize(
    "path",
    [example("claude_agent_sdk", "stage-graph"), example("codex", "goal-loop"), CURSOR_LOCAL],
)
def test_the_declared_policy_is_sealed_on_every_lane_binding(path: Path) -> None:
    for binding in _bindings(edited(path, _declare("mission_wins"))):
        assert binding.materialization == MaterializationPolicy(
            conflicts=ConflictPolicy.MISSION_WINS
        )
        assert binding.binding_digest == binding.computed_digest()
        assert binding.model_dump(mode="json")["materialization"] == {"conflicts": "mission_wins"}


@pytest.mark.parametrize("path", [example("claude_agent_sdk", "stage-graph"), CURSOR_LOCAL])
def test_an_undeclared_policy_leaves_the_binding_bytes_unchanged(path: Path) -> None:
    for binding in _bindings(path.read_text(encoding="utf-8")):
        assert binding.materialization is None
        assert "materialization" not in binding.model_dump(mode="json")


def test_an_unknown_conflict_policy_is_a_pointed_blocker() -> None:
    text = edited(example("claude_agent_sdk", "stage-graph"), _declare("overwrite"))
    found = blockers(compile_yaml(text))
    assert any(pointer.startswith("/mission/environment/materialization") for pointer in found)


def test_the_published_schema_declares_the_policy() -> None:
    definitions = manifest_v2_json_schema()["$defs"]
    assert "materialization" in definitions["EnvironmentV2"]["properties"]
    assert "conflicts" in definitions["MaterializationPolicy"]["properties"]
    assert definitions["ConflictPolicy"]["enum"] == ["refuse", "mission_wins", "repo_wins"]
