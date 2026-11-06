"""Alternatives compile their exact environment and never change a sealed lane."""

from types import SimpleNamespace

from mission_control.application.prerequisites.preflight import PrerequisitePreflight
from mission_control.application.prerequisites.service import (
    InMemoryOwnerPrerequisiteRepository,
    OwnerPrerequisiteService,
)
from mission_control.application.workspaces.preferences import FreshPlacementEligibility
from mission_control.domain.authoring.manifest_v2 import EnvironmentV2
from tests.fixtures.provider_frames import SCOPE
from tests.unit.authoring.test_manifest_compile import minimal, scope, service, text
from tests.unit.prerequisites.test_preflight import definition


async def test_rejected_primary_recompiles_valid_secondary_before_sealing():
    compiler, _, _ = await service()
    document = minimal()
    document["manifest"] = "mission/v2"
    environment = document["mission"]["environment"]
    environment.update(
        {
            "lanes": ["cursor_cloud", "deep_agents"],
            "placement": "prefer_cloud",
            "lane_environments": {
                "cursor_cloud": {
                    "lane": "cursor_cloud",
                    "execution_environment": {
                        "kind": "provider_hosted",
                        "provider": "cursor",
                        "environment_ref": "env-primary",
                    },
                },
                "deep_agents": {"lane": "deep_agents"},
            },
        }
    )
    checked = []

    async def eligible(request_scope, definitions):
        assert request_scope == scope().request_scope
        lane = definitions[0].program.lane.value
        checked.append(lane)
        return lane == "deep_agents"

    compiler.configure_placement_eligibility(eligible)
    compiled = await compiler.compile(text(document), scope())
    assert compiled.ok, compiled.report.blockers
    assert checked == ["cursor_cloud", "deep_agents"]
    assert compiled.definitions[0].program.lane.value == "deep_agents"
    assert all(item.definition.program.lane.value == "deep_agents" for item in compiled.programs)
    # A repeat checks eligibility again, rather than trusting cached readiness.
    await compiler.compile(text(document), scope())
    assert checked == ["cursor_cloud", "deep_agents"] * 2

    async def unavailable(request_scope, definitions):
        return False

    compiler.configure_placement_eligibility(unavailable)
    rejected = await compiler.compile(text(document), scope())
    assert not rejected.ok
    assert rejected.report.manifest_digest == compiled.report.manifest_digest


async def test_uncomposed_eligibility_never_admits_preferences():
    compiler, _, _ = await service()
    document = minimal()
    document["manifest"] = "mission/v2"
    document["mission"]["environment"].update(
        {
            "lanes": ["deep_agents"],
            "lane_environments": {"deep_agents": {"lane": "deep_agents"}},
        }
    )
    result = await compiler.compile(text(document), scope())
    assert not result.ok
    assert result.report.blockers[0].reason == "placement_unavailable"


def test_default_environment_preserves_old_dump():
    assert "lanes" not in EnvironmentV2(lane="deep_agents").model_dump(mode="json")


async def test_production_eligibility_requires_qualification_and_fresh_scoped_proof():
    repository = InMemoryOwnerPrerequisiteRepository()
    prerequisites = PrerequisitePreflight(repository)
    registry = SimpleNamespace(
        profiles=lambda: ("claude_managed",),
        describe=lambda profile: SimpleNamespace(qualified=True),
        allow_unqualified=True,
    )
    eligible = FreshPlacementEligibility(registry, prerequisites)
    definitions = (definition(),)
    assert not await eligible(SCOPE, definitions)
    report = await prerequisites.assess(SCOPE, definitions)
    recorder = OwnerPrerequisiteService(repository)
    for item in report.items:
        prerequisite = item.prerequisite
        if prerequisite.verify.method.verifies:
            await recorder.verify(
                SCOPE,
                prerequisite.id,
                method=prerequisite.verify.method,
                evidence_ref="artifact:unit-test-provider-readback",
            )
        else:
            await recorder.attest(SCOPE, prerequisite.id)
    assert await eligible(SCOPE, definitions)
    assert not await eligible(SCOPE + "-other", definitions)
    registry.describe = lambda profile: SimpleNamespace(qualified=False)
    assert not await eligible(SCOPE, definitions)
