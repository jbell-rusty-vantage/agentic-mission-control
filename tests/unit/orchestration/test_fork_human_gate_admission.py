"""Loop iter-3 (live run 2d5dc74f): a fork-derived manifest run's human gate is a noncognitive
control admission, verified against the fork's own binding and the source run's committed
definition. Before it the gate reserved a cognitive slot whose liability never closed, and the
family failed `stagegraph_blocked` right after the review was approved."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from mission_control.adapters.temporal.workflows.stagegraph import _noncognitive_gate_keys
from mission_control.application.programs import control_admission
from mission_control.application.programs.control_admission import (
    ManifestStageGraphHumanGateProvider,
)
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.programs.human_gate import HumanGateSpec

SCOPE = "tenant-1"
SOURCE, DERIVED, FORK = "run-source", "run-derived", "fork-req-1"
CONFIG = "sha256:" + "c" * 64
GATE = HumanGateSpec(
    gate_key="review", prompt="Review", reviewers=("owner",), packet_sources=("a.notes",)
)
BLUEPRINT = {"stages": ["review"]}


@dataclass(frozen=True)
class Source:
    fork_request_id: str
    source_run_id: str


class Forks:
    async def fork_source(self, request_scope: str, run_id: str) -> Source | None:
        return Source(FORK, SOURCE) if run_id == DERIVED else None


class Definitions:
    def __init__(self) -> None:
        self.read: list[str] = []

    async def run_subscriptions(self, request_scope: str, run_key: str) -> dict[str, Any] | None:
        self.read.append(run_key)
        if run_key == SOURCE:
            return {"definition": {"kind": "manifest"}}
        return {"definition": {"contract": "mc.run-request-definition/1"}}


class Runs:
    async def get_run(self, request_scope: str, run_id: str) -> Any:
        return SimpleNamespace(effective_configuration_digest=CONFIG)


class Configurations:
    async def retrieve_for_admission(self, digest: str) -> Any:
        return SimpleNamespace(digest=CONFIG, selected_blueprint=BLUEPRINT)


class Templates:
    async def get_template(self, **kwargs: Any) -> Any:
        return SimpleNamespace(request_scope=SCOPE, effective_configuration_digest=CONFIG)


def admission(run_id: str, binding_ref: str) -> Any:
    return SimpleNamespace(
        run_id=run_id,
        request_scope=SCOPE,
        semantic_input_binding_ref=binding_ref,
        effective_configuration_digest=CONFIG,
        blueprint=BLUEPRINT,
        proposal=SimpleNamespace(operation_request_key="review"),
        control_gate_keys=("review",),
        human_gate=GATE,
    )


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Definitions]:
    monkeypatch.setattr(
        control_admission, "MissionDefinition", SimpleNamespace(model_validate=lambda raw: raw)
    )
    monkeypatch.setattr(
        control_admission,
        "stagegraph_human_gates",
        lambda definition: (GATE,) if definition == {"kind": "manifest"} else (),
    )
    monkeypatch.setattr(
        control_admission,
        "StageGraphBlueprint",
        SimpleNamespace(model_validate=lambda raw: raw),
    )
    monkeypatch.setattr(control_admission, "sha256_digest", sha256_digest)
    definitions = Definitions()
    return (
        ManifestStageGraphHumanGateProvider(
            definitions, Configurations(), Runs(), Templates(), fork_sources=Forks()
        ),  # type: ignore[arg-type]
        definitions,
    )


@pytest.mark.asyncio
async def test_a_fork_derived_gate_is_verified_against_the_fork_binding_and_source(
    provider: tuple[Any, Definitions],
) -> None:
    gates, definitions = provider
    assert await gates.verify(admission(DERIVED, f"semantic-input:fork:{FORK}")) == (GATE,)
    assert definitions.read == [SOURCE]  # the source's committed definition governs
    with pytest.raises(ValueError, match="admitted semantic configuration"):
        await gates.verify(admission(DERIVED, f"semantic-input:manifest:{DERIVED}"))
    with pytest.raises(ValueError, match="admitted semantic configuration"):
        await gates.verify(admission(DERIVED, "semantic-input:fork:another-fork"))


@pytest.mark.asyncio
async def test_a_manifest_run_is_verified_as_before(provider: tuple[Any, Definitions]) -> None:
    gates, definitions = provider
    assert await gates.verify(admission(SOURCE, f"semantic-input:manifest:{SOURCE}")) == (GATE,)
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
