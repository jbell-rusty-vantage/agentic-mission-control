"""OC-R3: every declared lane profile's launch path goes through the resolution seam.

A Deep Agents node is resolved (`RuntimeResolver.resolve`); a provider or Cursor node is admitted
(`RuntimeResolver.admit`: lane, application, declared vendor route, Data Class against the lane
policy and the application ceiling, family). The two provider-hosted products never launch: their
node is refused at its lane pointer before any admission (MP-18/19), which this suite pins too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mission_control.application.authoring.manifest_launch_inputs import (
    AdmittedLaunch,
    ManifestLaunchBindingError,
)
from mission_control.application.execution.harness.describe import DECLARED_LANES
from mission_control.application.resolution.registries import ApplicationRegistry
from mission_control.bootstrap.resolution import compose_manifest_launch_resolver
from mission_control.domain.authoring.mission_definition import DefinitionNode
from tests.fixtures.applications import installed_applications
from tests.support.manifests.v2_launch import (
    EXAMPLES,
    SCOPE,
    bindings,
    compiled_ok,
    example,
    resolver,
    served,
    templates_of,
)
from tests.support.model_catalog import bindings_catalog

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


# The examples' application (`ai-engineer`) admits `internal`; the seam's Data Class step
# refuses a mission declared `internal` once that application's ceiling is `public`.
CEILING_REFUSAL = "application ai-engineer admits data up to public"


def _lowered_ceiling() -> ApplicationRegistry:
    installed = installed_applications()
    return ApplicationRegistry(
        installed.get(app).model_copy(update={"data_class_ceiling": "public"})
        if app == "ai-engineer"
        else installed.get(app)
        for app in installed.applications()
    )


def _launcher(applications: ApplicationRegistry) -> Any:
    bound = bindings()
    return compose_manifest_launch_resolver(
        bound,
        served(bound),
        applications=applications,
        models=bindings_catalog(bound),
        provider_secret_env={"openai": "OPENAI_API_KEY"},
    )


def _launch(program: Any, definition: Any, applications: ApplicationRegistry) -> dict[str, Any]:
    admitted = AdmittedLaunch.from_configuration(SCOPE, "run-v2", program.configuration)
    target = _launcher(applications)
    if program.lowered.family == "StageGraph":
        return dict(target.stage_templates(definition, admitted))
    return dict(target.goal_templates(definition, admitted))


def _declared_internal(definition: Any) -> Any:
    return definition.model_copy(update={"data_class": "internal"})


def test_the_suite_accounts_for_every_declared_profile() -> None:
    assert {*LAUNCHED, *HOSTED_API, *LAUNCH_BLOCKED} == set(DECLARED_LANES)


@pytest.mark.parametrize("profile", sorted(LAUNCHED))
def test_a_launched_node_goes_through_the_seam(profile: str) -> None:
    compilation = compiled_ok(LAUNCHED[profile].read_text(encoding="utf-8"))
    sealed: set[str] = set()
    for definition, program in zip(compilation.definitions, compilation.programs, strict=True):
        sealed |= {
            template.lane_binding.lane_profile
            for template in templates_of(program, definition, None).values()
        }
    # The launch seals a template for the profile's own lane binding...
    assert profile in sealed
    # ...and the seam's Data Class step governs it: the lowered application ceiling refuses.
    definition, program = compilation.definitions[0], compilation.programs[0]
    if profile == "deep_agents":
        root = definition.program
        (node,) = [item for item in root.nodes if item.lane == "deep_agents"]
        admitted = AdmittedLaunch.from_configuration(SCOPE, "run-v2", program.configuration)
        with pytest.raises(ManifestLaunchBindingError, match=CEILING_REFUSAL):
            _launcher(_lowered_ceiling()).deep_agents_node(
                _declared_internal(definition), (root, node), verifier=False, admitted=admitted
            )
    else:
        with pytest.raises(ManifestLaunchBindingError, match=CEILING_REFUSAL):
            _launch(program, _declared_internal(definition), _lowered_ceiling())


def test_the_seam_refusal_is_the_launch_refusal() -> None:
    """An admission refusal (here a lowered application ceiling) refuses the provider node."""

    compilation = compiled_ok(LAUNCHED["codex"].read_text(encoding="utf-8"))
    (definition,), (program,) = compilation.definitions, compilation.programs
    with pytest.raises(ManifestLaunchBindingError, match=CEILING_REFUSAL) as refused:
        _launch(program, _declared_internal(definition), _lowered_ceiling())
    assert refused.value.pointer == "/mission/data_class"
    # The same mission launches under the installed ceiling.
    assert _launch(program, _declared_internal(definition), installed_applications())


@pytest.mark.parametrize("profile", LAUNCH_BLOCKED)
def test_a_provider_hosted_node_is_refused_before_admission(profile: str) -> None:
    compilation = compiled_ok(example("claude_agent_sdk", "stage-graph").read_text("utf-8"))
    definition = compilation.definitions[0]
    root = definition.program
    value = root.nodes[0].model_dump(mode="json")
    value["lane"] = profile
    value["environment"]["lane"] = profile
    node = DefinitionNode.model_validate(value)
    # Refused even where admission would refuse too: the lane refusal comes first.
    for launcher in (resolver(), _launcher(_lowered_ceiling())):
        with pytest.raises(ManifestLaunchBindingError, match="evidence-blocked"):
            launcher.provider_node(
                _declared_internal(definition),
                (root, node),
                verifier=False,
                operation_binding_refs=frozenset(),
                rows={},
                family="StageGraph",
            )
