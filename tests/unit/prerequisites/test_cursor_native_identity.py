from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mission_control.application.prerequisites.preflight import PrerequisitesUnmet
from mission_control.domain.execution.lanes import CursorExecutionBinding
from tests.fixtures.lane_bindings import lane_fields
from tests.unit.prerequisites.test_preflight import InMemoryOwnerPrerequisiteRepository


async def test_actual_manifest_preflight_and_require_match_sealed_cursor_local_identity(
    monkeypatch,
):
    from mission_control.application.authoring.manifest_service import MissionManifestService
    from mission_control.application.prerequisites.preflight import BoundCursorPrerequisiteIdentity
    from mission_control.bootstrap import prerequisites as composition
    from mission_control.domain.execution.data_class import DEFAULT_DATA_CLASS_POLICY
    from tests.unit.authoring.test_manifest_v2_launch import (
        SCOPE,
        _compile,
        bindings,
        example,
        templates_of,
    )

    bound = bindings()
    lane = bound.providers.cursor_local
    bound = bound.model_copy(
        update={
            "providers": bound.providers.model_copy(
                update={
                    "cursor_local": lane.model_copy(
                        update={
                            "lease_root": "/tmp/cursor-leases",
                            "auth_profiles": {
                                key: pin.model_copy(update={"billing_mode": "api"})
                                for key, pin in lane.auth_profiles.items()
                            },
                        }
                    )
                }
            )
        }
    )
    yaml = example("cursor_local", "stage-graph").read_text()
    compilation = await _compile(yaml, SCOPE, DEFAULT_DATA_CLASS_POLICY)
    assert compilation.ok, [(i.pointer, i.message) for i in compilation.report.blockers]
    repository = InMemoryOwnerPrerequisiteRepository()
    monkeypatch.setattr(composition, "PostgresOwnerPrerequisiteRepository", lambda pool: repository)
    monkeypatch.setattr(composition.ManifestLaunchBindings, "load", lambda path: bound)
    monkeypatch.setattr(composition, "configured_network_hosts", lambda settings: None)
    monkeypatch.setattr(composition, "compose_bundle_materializer", lambda settings: None)
    preflight = composition.compose_prerequisite_preflight(
        None,
        binding=None,
        settings=SimpleNamespace(
            manifest_launch_bindings_path="reviewed.json",
            mission_control_catalog_scope=SCOPE.rsplit("/", 1)[0] + "/catalog",
        ),
    )
    preflight._installation_check = None
    compiler = SimpleNamespace(compile=AsyncMock(return_value=compilation))
    service = MissionManifestService(
        compiler=compiler, request_scope=SCOPE, prerequisites=preflight
    )
    report = await service.preflight(
        yaml, actor_id="owner", permissions=frozenset({"mission.read", "catalog.read"})
    )
    definition = compilation.definitions[0]
    sealed = templates_of(compilation.programs[0], definition, bound)
    runtime = await preflight.assess(SCOPE, (definition,), templates=sealed)

    def select(result):
        return {
            item.prerequisite.id: item.prerequisite.digest
            for item in result.items
            if item.prerequisite.id.startswith(("cursor_local.owner.c9.",))
        }

    assert len(select(report)) == 1
    assert select(report) == select(runtime)
    assert all(
        "Native Cursor host identity:" in item.prerequisite.why
        for item in report.items
        if item.prerequisite.id in select(report)
    )
    with pytest.raises(PrerequisitesUnmet) as caught:
        await preflight.require(SCOPE, definition)
    assert select(caught.value.report) == select(report)
    for drift in ({"lane_profile": "cursor_cloud"}, {"hook_callback": None}):
        malformed = {
            key: template.model_copy(
                update={
                    **lane_fields(
                        CursorExecutionBinding.carried_by(template).model_copy(update=drift)
                        if CursorExecutionBinding.carried_by(template) is not None
                        else None
                    )
                }
            )
            for key, template in sealed.items()
        }
        # OC-R2: a drifted binding no longer decodes from its sealed bytes; the lane's
        # decode refuses it before any identity comparison (fail closed).
        with pytest.raises(ValueError, match="CursorExecutionBinding"):
            await preflight.assess(SCOPE, (definition,), templates=malformed)
    changed = bound.model_copy(
        update={
            "providers": bound.providers.model_copy(
                update={
                    "cursor_local": bound.providers.cursor_local.model_copy(
                        update={
                            "model_profiles": {
                                **bound.providers.cursor_local.model_profiles,
                                "cursor.default": bound.providers.cursor_local.model_profiles[
                                    "cursor.default"
                                ].model_copy(update={"model_id": "different-selected-model"}),
                            }
                        }
                    ),
                }
            )
        }
    )
    preflight._native_identity = BoundCursorPrerequisiteIdentity(changed)
    fresh = await service.preflight(
        yaml, actor_id="owner", permissions=frozenset({"mission.read", "catalog.read"})
    )
    assert select(fresh).keys().isdisjoint(select(report))
    mismatch = await preflight.assess(SCOPE, (definition,), templates=sealed)
    assert not mismatch.ready
    assert any("sealed native identity differs" in reason for reason in mismatch.blockers)


async def test_selected_subscription_refused_before_any_host_observation():
    from mission_control.application.prerequisites.preflight import BoundCursorPrerequisiteIdentity
    from mission_control.domain.execution.data_class import DEFAULT_DATA_CLASS_POLICY
    from tests.unit.authoring.test_manifest_v2_launch import SCOPE, _compile, bindings, example

    bound = bindings()
    lane = bound.providers.cursor_local
    lane = lane.model_copy(update={"lease_root": "/tmp/cursor-leases"})
    bound = bound.model_copy(
        update={"providers": bound.providers.model_copy(update={"cursor_local": lane})}
    )
    compilation = await _compile(
        example("cursor_local", "stage-graph").read_text(), SCOPE, DEFAULT_DATA_CLASS_POLICY
    )
    with pytest.raises(ValueError, match="API-key route"):
        BoundCursorPrerequisiteIdentity(bound)(compilation.definitions[0].program.nodes[0], False)
