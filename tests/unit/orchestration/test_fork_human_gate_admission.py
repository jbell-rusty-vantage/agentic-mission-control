"""Loop iter-3 (live run 2d5dc74f): a fork-derived manifest run's human gate is a noncognitive
control admission, verified against the fork's own binding and the source run's committed
definition. Before it the gate reserved a cognitive slot whose liability never closed, and the
family failed `stagegraph_blocked` right after the review was approved."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mission_control.adapters.temporal.workflows.stagegraph import _noncognitive_gate_keys
from mission_control.application.programs.control_admission import (
    ManifestStageGraphHumanGateProvider,
)
from mission_control.application.programs.human_gates import stagegraph_human_gates
from mission_control.domain.programs.human_gate import HumanGateSpec
from tests.support.manifests.launch_inputs import compile_programs

SCOPE = "tenant-1"
SOURCE, DERIVED, FORK = "run-source", "run-derived", "fork-req-1"
CONFIG = "sha256:" + "c" * 64
# A real compiled manifest whose Stage Graph declares one `review` Human Gate.
MISSION = (
    Path(__file__).resolve().parents[3]
    / "tests/fixtures/manifests/fast-track/01-research-ingestion-deep-agents.yml"
)
GATE = HumanGateSpec(
    gate_key="review", prompt="Review", reviewers=("owner",), packet_sources=("a.notes",)
)


@dataclass(frozen=True)
class Mission:
    definition: Any
    selected_blueprint: Any
    gate: HumanGateSpec


@pytest.fixture(scope="module")
def mission() -> Mission:
    definitions, programs = asyncio.run(compile_programs(MISSION.read_text(encoding="utf-8")))
    (gate,) = stagegraph_human_gates(definitions[0])
    return Mission(definitions[0], programs[0].configuration.selected_blueprint, gate)


@dataclass(frozen=True)
class Source:
    fork_request_id: str
    source_run_id: str


class Forks:
    async def fork_source(self, request_scope: str, run_id: str) -> Source | None:
        return Source(FORK, SOURCE) if run_id == DERIVED else None


class Definitions:
    def __init__(self, mission: Mission) -> None:
        self.read: list[str] = []
        self._definition = mission.definition

    async def run_subscriptions(self, request_scope: str, run_key: str) -> dict[str, Any] | None:
        self.read.append(run_key)
        if run_key == SOURCE:
            return {"definition": self._definition.model_dump(mode="json")}
        return {"definition": {"contract": "mc.run-request-definition/1"}}


class Runs:
    async def get_run(self, request_scope: str, run_id: str) -> Any:
        return SimpleNamespace(effective_configuration_digest=CONFIG)


class Configurations:
    def __init__(self, mission: Mission) -> None:
        self._blueprint = mission.selected_blueprint

    async def retrieve_for_admission(self, digest: str) -> Any:
        return SimpleNamespace(digest=CONFIG, selected_blueprint=self._blueprint)


class Templates:
    async def get_template(self, **kwargs: Any) -> Any:
        return SimpleNamespace(request_scope=SCOPE, effective_configuration_digest=CONFIG)


def admission(mission: Mission, run_id: str, binding_ref: str) -> Any:
    return SimpleNamespace(
        run_id=run_id,
        request_scope=SCOPE,
        semantic_input_binding_ref=binding_ref,
        effective_configuration_digest=CONFIG,
        blueprint=mission.selected_blueprint.model_dump(mode="json"),
        proposal=SimpleNamespace(operation_request_key="review"),
        control_gate_keys=("review",),
        human_gate=mission.gate,
    )


@pytest.fixture
def provider(mission: Mission) -> tuple[Any, Definitions]:
    definitions = Definitions(mission)
    return (
        ManifestStageGraphHumanGateProvider(
            definitions, Configurations(mission), Runs(), Templates(), fork_sources=Forks()
        ),  # type: ignore[arg-type]
        definitions,
    )


@pytest.mark.asyncio
async def test_a_fork_derived_gate_is_verified_against_the_fork_binding_and_source(
    provider: tuple[Any, Definitions], mission: Mission
) -> None:
    gates, definitions = provider
    fork = admission(mission, DERIVED, f"semantic-input:fork:{FORK}")
    assert await gates.verify(fork) == (mission.gate,)
    assert definitions.read == [SOURCE]  # the source's committed definition governs
    with pytest.raises(ValueError, match="admitted semantic configuration"):
        await gates.verify(admission(mission, DERIVED, f"semantic-input:manifest:{DERIVED}"))
    with pytest.raises(ValueError, match="admitted semantic configuration"):
        await gates.verify(admission(mission, DERIVED, "semantic-input:fork:another-fork"))


@pytest.mark.asyncio
async def test_a_manifest_run_is_verified_as_before(
    provider: tuple[Any, Definitions], mission: Mission
) -> None:
    gates, definitions = provider
    source = admission(mission, SOURCE, f"semantic-input:manifest:{SOURCE}")
    assert await gates.verify(source) == (mission.gate,)
    assert definitions.read == [SOURCE]


def test_the_workflow_selects_noncognitive_gates_for_forks_only_when_patched() -> None:
    gates = {"review": GATE}
    fork_input = SimpleNamespace(
        run_id=DERIVED, semantic_input_binding_ref=f"semantic-input:fork:{FORK}"
    )
    manifest_input = SimpleNamespace(
        run_id=SOURCE, semantic_input_binding_ref=f"semantic-input:manifest:{SOURCE}"
    )
    assert _noncognitive_gate_keys(fork_input, gates, enabled=True) == frozenset()  # type: ignore[arg-type]
    assert _noncognitive_gate_keys(fork_input, gates, enabled=True, forks=True) == {"review"}  # type: ignore[arg-type]
    assert _noncognitive_gate_keys(manifest_input, gates, enabled=True) == {"review"}  # type: ignore[arg-type]
    assert _noncognitive_gate_keys(manifest_input, gates, enabled=False, forks=True) == frozenset()  # type: ignore[arg-type]
