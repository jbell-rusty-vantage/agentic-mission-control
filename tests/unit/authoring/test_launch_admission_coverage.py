"""OC-R3: every declared lane profile's launch path goes through the resolution seam.

A Deep Agents node is resolved (`RuntimeResolver.resolve`); a provider or Cursor node is admitted
(`RuntimeResolver.admit`: lane, application, declared vendor route, Data Class against the lane
policy and the application ceiling, family). The two provider-hosted products never launch: their
node is refused at its lane pointer before any admission (MP-18/19), which this suite pins too.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mission_control.application.authoring.manifest_launch_inputs import (
    ManifestLaunchBindingError,
)
from mission_control.application.execution.harness.describe import DECLARED_LANES
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.domain.authoring.mission_definition import DefinitionNode
from mission_control.domain.resolution.resolved import ResolutionRefused
from tests.unit.authoring.test_manifest_v2_launch import (
    EXAMPLES,
    compiled_ok,
    example,
    resolver,
    templates_of,
)

# Profile -> the checked example whose launch reaches it.
LAUNCHED: dict[str, Path] = {
    # Its Stage Graph runs a `deep_agents` verifier stage beside the Claude stages.
    "deep_agents": example("claude_agent_sdk", "stage-graph"),
    "claude_agent_sdk": example("claude_agent_sdk", "stage-graph"),
    "codex": example("codex", "goal-loop"),
    "cursor_local": EXAMPLES / "cursor-local.stage-graph.mission.yml",
    "cursor_cloud": EXAMPLES / "cursor-cloud.goal-loop.mission.yml",
}
# Hosted agent APIs: launched through `provider_node` with hosted placement.
HOSTED_API = ("claude_managed", "codex_agents")
# Compile structurally, refused at the lane pointer before admission (evidence-blocked).
LAUNCH_BLOCKED = ("claude_cloud", "codex_cloud")


@pytest.fixture
def seam(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[tuple[str, str]]]:
    calls: list[tuple[str, str]] = []
    resolve, admit = RuntimeResolver.resolve, RuntimeResolver.admit

    def spy_resolve(self: RuntimeResolver, selection: Any) -> Any:
        calls.append(("resolve", selection.lane_profile))
        return resolve(self, selection)

    def spy_admit(self: RuntimeResolver, admission: Any) -> Any:
        calls.append(("admit", admission.lane_profile))
        return admit(self, admission)

    monkeypatch.setattr(RuntimeResolver, "resolve", spy_resolve)
    monkeypatch.setattr(RuntimeResolver, "admit", spy_admit)
    return calls


def test_the_suite_accounts_for_every_declared_profile() -> None:
    assert {*LAUNCHED, *HOSTED_API, *LAUNCH_BLOCKED} == set(DECLARED_LANES)


@pytest.mark.parametrize("profile", sorted(LAUNCHED))
def test_a_launched_node_goes_through_the_seam(profile: str, seam: list[tuple[str, str]]) -> None:
    compilation = compiled_ok(LAUNCHED[profile].read_text(encoding="utf-8"))
    for definition, program in zip(compilation.definitions, compilation.programs, strict=True):
        templates_of(program, definition, None)
    method = "resolve" if profile == "deep_agents" else "admit"
    assert (method, profile) in seam


def test_the_seam_refusal_is_the_launch_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An admission refusal (here a lowered application ceiling) refuses the provider node."""

    def refuse(self: RuntimeResolver, admission: Any) -> ResolutionRefused:
        return ResolutionRefused(
            code="DATA_CLASS_NOT_ADMITTED",
            pointer="/data_class",
            lane_profile=admission.lane_profile,
            reason="application ceiling below the mission's data class",
            remedy="lower the data class",
        )

    monkeypatch.setattr(RuntimeResolver, "admit", refuse)
    compilation = compiled_ok(LAUNCHED["codex"].read_text(encoding="utf-8"))
    (definition,), (program,) = compilation.definitions, compilation.programs
    with pytest.raises(ManifestLaunchBindingError, match="application ceiling"):
        templates_of(program, definition, None)


@pytest.mark.parametrize("profile", LAUNCH_BLOCKED)
def test_a_provider_hosted_node_is_refused_before_admission(
    profile: str, seam: list[tuple[str, str]]
) -> None:
    compilation = compiled_ok(example("claude_agent_sdk", "stage-graph").read_text("utf-8"))
    definition = compilation.definitions[0]
    root = definition.program
    value = root.nodes[0].model_dump(mode="json")
    value["lane"] = profile
    value["environment"]["lane"] = profile
    node = DefinitionNode.model_validate(value)
    with pytest.raises(ManifestLaunchBindingError, match="evidence-blocked"):
        resolver().provider_node(
            definition,
            (root, node),
            verifier=False,
            operation_binding_refs=frozenset(),
            rows={},
            family="StageGraph",
        )
    assert seam == []
