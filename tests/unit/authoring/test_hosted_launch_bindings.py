"""Hosted launch routing uses reviewed deployment pins, placement and immutable git base."""

import copy

import pytest

from mission_control.application.authoring.provider_launch import ProviderLanes, required_pins
from mission_control.bootstrap.resolution import compose_manifest_launch_resolver
from tests.fixtures.applications import installed_applications
from tests.fixtures.models import bindings_catalog
from tests.unit.authoring.test_manifest_v2_launch import bindings


@pytest.mark.parametrize(
    ("profile", "provider"), [("claude_managed", "anthropic"), ("codex_agents", "openai")]
)
def test_hosted_provider_entry_requires_matching_wire_pins_and_projection(profile, provider):
    bound = bindings()
    lane = bound.providers.claude_agent_sdk.model_dump(mode="json")
    lane["provider_options"] = {
        "provider": profile,
        **({"max_list_cost_minor_units": 50} if profile == "claude_managed" else {}),
    }
    lane["host_profiles"] = {
        "hosted.reviewed": {
            "kind": "provider_hosted",
            "provider": provider,
            "environment_ref": "env-reviewed",
            "expected_revision": "v1",
        }
    }
    lane["pins"] = dict(required_pins(profile))
    lane["hosted_projection"] = {}
    providers = ProviderLanes.model_validate({profile: lane})
    assert providers.lane(profile).hosted_projection == {}
    broken = copy.deepcopy(lane)
    broken["pins"] = {}
    with pytest.raises(ValueError, match="adapter's version"):
        ProviderLanes.model_validate({profile: broken})
    del broken["hosted_projection"]
    with pytest.raises(ValueError, match="reviewed hosted_projection"):
        ProviderLanes.model_validate({profile: broken})


def test_hosted_provider_resolution_requires_a_reviewed_base_commit(monkeypatch):
    from mission_control.application.authoring.manifest_launch_inputs import (
        ManifestLaunchBindingError,
    )
    from mission_control.application.authoring.provider_launch import required_pins
    from mission_control.application.resolution.resolver import RuntimeResolver
    from mission_control.domain.authoring.mission_definition import DefinitionNode
    from tests.unit.authoring.test_manifest_v2_launch import compiled_ok, example, served

    # OC-R3: the hosted node is admitted through the resolution seam.
    admitted: list[str] = []
    admit = RuntimeResolver.admit

    def spy(self, admission):
        admitted.append(admission.lane_profile)
        return admit(self, admission)

    monkeypatch.setattr(RuntimeResolver, "admit", spy)

    compilation = compiled_ok(
        example("claude_agent_sdk", "stage-graph").read_text(encoding="utf-8")
    )
    # The hosted lane is not ZDR-eligible: compile requires a declared data class there, and
    # launch admission enforces it too (OC-R3, `RuntimeResolver.admit`).
    definition = compilation.definitions[0].model_copy(update={"data_class": "internal"})
    root = definition.program
    value = root.nodes[0].model_dump(mode="json")
    value["lane"] = "claude_managed"
    value["environment"]["lane"] = "claude_managed"
    value["selections"]["execution_environment"] = {
        "kind": "provider_hosted",
        "provider": "anthropic",
        "environment_ref": "env-reviewed",
        "expected_revision": "v1",
    }
    value["selections"]["workspace_policy"]["mode"] = "provider_workspace"
    node = DefinitionNode.model_validate(value)
    bound = bindings()
    lane = bound.providers.claude_agent_sdk.model_dump(mode="json")
    lane.update(
        provider_options={"provider": "claude_managed", "max_list_cost_minor_units": 50},
        hosted_projection={},
        pins=dict(required_pins("claude_managed")),
        host_profiles={
            "reviewed": {
                "kind": "provider_hosted",
                "provider": "anthropic",
                "environment_ref": "env-reviewed",
                "expected_revision": "v1",
            }
        },
    )
    hosted = ProviderLanes.model_validate({"claude_managed": lane})
    bound = bound.model_copy(update={"providers": hosted})
    resolver = compose_manifest_launch_resolver(
        bound,
        served(bound),
        applications=installed_applications(),
        models=bindings_catalog(bound),
        provider_secret_env={},
    )
    with pytest.raises(ManifestLaunchBindingError, match="repository_commits"):
        resolver.provider_node(
            definition,
            (root, node),
            verifier=False,
            operation_binding_refs=frozenset(),
            rows={},
            family="StageGraph",
        )
    repo = node.environment.workspace.repo
    lane["repository_commits"] = {f"{repo.url or repo.path}#{repo.ref}": "a" * 40}
    bound = bound.model_copy(
        update={"providers": ProviderLanes.model_validate({"claude_managed": lane})}
    )
    resolved = compose_manifest_launch_resolver(
        bound,
        served(bound),
        applications=installed_applications(),
        models=bindings_catalog(bound),
        provider_secret_env={},
    ).provider_node(
        definition,
        (root, node),
        verifier=False,
        operation_binding_refs=frozenset(),
        rows={},
        family="StageGraph",
    )
    assert resolved.binding_fields["repo_commit"] == "a" * 40
    assert resolved.binding_fields["environment"].kind == "provider_hosted"
    assert admitted == ["claude_managed"]
