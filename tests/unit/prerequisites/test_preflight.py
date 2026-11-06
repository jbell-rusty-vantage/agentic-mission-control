"""Owner setup is checked before any provider launch, with transport parity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from mission_control.application.authoring.manifest_submit import ManifestSubmitService
from mission_control.application.prerequisites.catalog import account_prerequisites
from mission_control.application.prerequisites.preflight import (
    PrerequisitePreflight,
    PrerequisitesUnmet,
    StoredPrerequisiteLaunchGuard,
    scope_prerequisite,
)
from mission_control.application.prerequisites.service import (
    InMemoryOwnerPrerequisiteRepository,
    OwnerPrerequisiteService,
)
from mission_control.domain.authoring.manifest import (
    Environment,
    Lane,
    RepositoryWorkspace,
    WorkspaceSelection,
    load_manifest_yaml,
)
from mission_control.domain.authoring.manifest_v2 import AuthSelection, parse_manifest_any
from mission_control.domain.authoring.mission_definition import (
    EnvironmentSelections,
    manifest_to_definitions,
)
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.policies.contracts import ActorContext
from mission_control.domain.prerequisites import PrerequisiteStanding
from mission_control.interfaces.mcp.mission_tools import ScopedManifests
from tests.fixtures.provider_frames import SCOPE
from tests.unit.authoring.test_manifest_compile import MINIMAL, http_app
from tests.unit.authoring.test_manifest_interfaces import FakeLifecycle, manifests, principal


def definition(lane="claude_managed"):
    document = load_manifest_yaml(MINIMAL.read_text(encoding="utf-8"))
    manifest = parse_manifest_any(document)
    original = manifest_to_definitions(manifest, document)[0]

    def change(node):
        return node.model_copy(
            update={
                "lane": Lane(lane),
                "environment": node.environment.model_copy(update={"lane": Lane(lane)}),
                "nodes": tuple(change(child) for child in node.nodes),
            }
        )

    return original.model_copy(update={"program": change(original.program)})


async def test_fresh_managed_installation_lists_full_owner_steps_and_readiness():
    repository = InMemoryOwnerPrerequisiteRepository()
    preflight = PrerequisitePreflight(repository)
    report = await preflight.assess(SCOPE, (definition(),))
    assert not report.ready
    assert {item.prerequisite.title.split(":")[0] for item in report.items} == {
        "MA1",
        "MA2",
        "MA4",
        "MA5",
        "M1",
        "M2",
        "M3",
        "M4",
    }
    assert all(item.assessment.blocking and item.prerequisite.steps for item in report.items)
    assert report.readiness
    assert not (await repository.list("another-scope"))


async def test_actual_manifest_preflight_and_require_match_sealed_codex_identity(monkeypatch):
    from mission_control.application.authoring.manifest_service import MissionManifestService
    from mission_control.application.prerequisites.preflight import BoundCodexPrerequisiteIdentity
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
    yaml = example("codex", "stage-graph").read_text()
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
            if item.prerequisite.id.startswith(("codex.owner.x4.", "codex.owner.x6."))
        }

    assert len(select(report)) == 2
    assert select(report) == select(runtime)
    assert all(
        "Native Codex identity:" in item.prerequisite.why
        for item in report.items
        if item.prerequisite.id in select(report)
    )
    with pytest.raises(PrerequisitesUnmet) as caught:
        await preflight.require(SCOPE, definition)
    assert select(caught.value.report) == select(report)
    changed = bound.model_copy(
        update={
            "providers": bound.providers.model_copy(
                update={
                    "codex": bound.providers.codex.model_copy(
                        update={
                            "model_profiles": {
                                **bound.providers.codex.model_profiles,
                                "codex.default": bound.providers.codex.model_profiles[
                                    "codex.default"
                                ].model_copy(update={"model_id": "different-selected-model"}),
                            }
                        }
                    ),
                }
            )
        }
    )
    preflight._native_identity = BoundCodexPrerequisiteIdentity(changed)
    fresh = await service.preflight(
        yaml, actor_id="owner", permissions=frozenset({"mission.read", "catalog.read"})
    )
    assert select(fresh).keys().isdisjoint(select(report))
    mismatch = await preflight.assess(SCOPE, (definition,), templates=sealed)
    assert not mismatch.ready
    assert any("sealed native identity differs" in reason for reason in mismatch.blockers)


@pytest.mark.parametrize("missing", ["model", "auth", "host"])
def test_bound_codex_identity_never_falls_back_to_another_profile(missing):
    from mission_control.application.prerequisites.preflight import BoundCodexPrerequisiteIdentity
    from tests.unit.authoring.test_manifest_v2_launch import bindings, example

    document = load_manifest_yaml(example("codex", "goal-loop").read_text())
    node = manifest_to_definitions(parse_manifest_any(document), document)[0].program
    if missing == "model":
        node = node.model_copy(
            update={
                "environment": node.environment.model_copy(
                    update={
                        "model": node.environment.model.model_copy(update={"profile": "absent"}),
                    }
                )
            }
        )
    else:
        key = "auth" if missing == "auth" else "execution_environment"
        node = node.model_copy(
            update={
                "selections": node.selections.model_copy(
                    update={
                        key: getattr(node.selections, key).model_copy(update={"profile": "absent"}),
                    }
                )
            }
        )
    with pytest.raises(ValueError, match="exact deployment pins"):
        BoundCodexPrerequisiteIdentity(bindings())(node, False)


def test_bound_codex_identity_uses_goal_loop_verifier_selection():
    from mission_control.application.prerequisites.preflight import BoundCodexPrerequisiteIdentity
    from tests.unit.authoring.test_manifest_v2_launch import bindings, example

    document = load_manifest_yaml(example("codex", "goal-loop").read_text())
    node = manifest_to_definitions(parse_manifest_any(document), document)[0].program
    bound = bindings()
    lane = bound.providers.codex
    other = next(iter(lane.auth_profiles.values())).model_copy(update={"profile": "verifier-auth"})
    bound = bound.model_copy(
        update={
            "providers": bound.providers.model_copy(
                update={
                    "codex": lane.model_copy(
                        update={"auth_profiles": {**lane.auth_profiles, "verifier-auth": other}}
                    ),
                }
            )
        }
    )
    node = node.model_copy(
        update={
            "verifier_selections": node.selections.model_copy(
                update={
                    "auth": node.selections.auth.model_copy(update={"profile": "verifier-auth"}),
                }
            )
        }
    )
    resolve = BoundCodexPrerequisiteIdentity(bound)
    assert resolve(node, False)["auth"] != resolve(node, True)["auth"]


async def test_expired_owner_evidence_blocks_the_next_launch():
    repository = InMemoryOwnerPrerequisiteRepository()
    preflight = PrerequisitePreflight(repository)
    first = await preflight.assess(SCOPE, (definition(),))
    old = datetime.now(UTC) - timedelta(days=2)
    service = OwnerPrerequisiteService(repository, clock=lambda: old)
    for item in first.items:
        await service.attest(SCOPE, item.prerequisite.id, expires_at=old + timedelta(days=1))
    report = await preflight.assess(SCOPE, (definition(),))
    assert not report.ready
    assert all(item.assessment.standing is PrerequisiteStanding.EXPIRED for item in report.items)


async def test_launch_refuses_before_templates_subscriptions_or_temporal():
    preflight = PrerequisitePreflight(InMemoryOwnerPrerequisiteRepository())
    definitions = AsyncMock()
    definitions.run_subscriptions.return_value = {
        "definition": definition().model_dump(mode="json")
    }
    launches = AsyncMock()
    inputs = AsyncMock()
    subscriptions = AsyncMock()
    lifecycle = ManifestSubmitService(
        compiler=SimpleNamespace(),
        programs=SimpleNamespace(),
        run_control=SimpleNamespace(),
        submissions=definitions,
        request_scope=SCOPE,
        launches=launches,
        launch_inputs=inputs,
        subscriptions=subscriptions,
        prerequisites=preflight,
    )
    with pytest.raises(PrerequisitesUnmet) as caught:
        await lifecycle.start(
            "run-fixture",
            ActorContext(
                actor_id="owner",
                permissions=frozenset({"mission.start"}),
                authority_refs=frozenset(),
            ),
        )
    assert caught.value.code == "PREREQUISITES_UNMET"
    launches.launch.assert_not_called()
    inputs.family_input.assert_not_called()
    subscriptions.subscribe.assert_not_called()


async def test_deep_agents_does_not_require_unselected_provider_accounts():
    report = await PrerequisitePreflight(InMemoryOwnerPrerequisiteRepository()).assess(
        SCOPE, (definition("deep_agents"),)
    )
    assert report.ready and not report.items


async def test_installer_readiness_is_rechecked_on_every_preflight():
    check = AsyncMock(side_effect=[(), ("release attestation changed",)])
    preflight = PrerequisitePreflight(
        InMemoryOwnerPrerequisiteRepository(), installation_check=check
    )
    assert (await preflight.assess(SCOPE, (definition("deep_agents"),))).ready
    changed = await preflight.assess(SCOPE, (definition("deep_agents"),))
    assert not changed.ready and changed.blockers == ("release attestation changed",)
    assert check.await_count == 2


def test_knowledge_alias_repository_change_invalidates_scoped_evidence():
    from mission_control.domain.authoring.manifest_v2 import WorkspaceSelectionV2

    prerequisite = next(
        p for p in account_prerequisites(LaneProfile.CLAUDE_MANAGED) if p.scope == "repo"
    )
    selections = EnvironmentSelections(
        knowledge_workspace=WorkspaceSelectionV2.model_validate(
            {"kind": "knowledge", "repo": {"use": "application_knowledge_repo"}}
        )
    )

    def identity(repository):
        return scope_prerequisite(prerequisite, Environment(), selections, repository).id

    assert identity({"url": "https://github.com/owner/one"}) != identity(
        {"url": "https://github.com/owner/two"}
    )


async def test_direct_run_guard_uses_the_same_stored_definition_and_refusal():
    repository = InMemoryOwnerPrerequisiteRepository()
    preflight = PrerequisitePreflight(repository)
    lookup = AsyncMock(return_value={"definition": definition().model_dump(mode="json")})
    with pytest.raises(PrerequisitesUnmet) as caught:
        await StoredPrerequisiteLaunchGuard(lookup, preflight)(SCOPE, "run-1")
    lookup.assert_awaited_once_with(SCOPE, "run-1")
    assert caught.value.report == await preflight.assess(SCOPE, (definition(),))


def test_selected_account_and_repository_have_distinct_evidence_identities():
    prerequisite = next(
        p for p in account_prerequisites(LaneProfile.CURSOR_CLOUD) if p.scope == "repo"
    )

    def scoped(repo, auth):
        return scope_prerequisite(
            prerequisite,
            Environment(workspace=WorkspaceSelection(repo=RepositoryWorkspace(url=repo))),
            EnvironmentSelections(auth=AuthSelection(profile=auth)),
        ).id

    first = scoped("https://github.com/example/one", "account-one")
    assert first == scoped("https://github.com/example/one", "account-one")
    assert first != scoped("https://github.com/example/two", "account-one")
    assert first != scoped("https://github.com/example/one", "account-two")


async def test_http_and_mcp_preflight_return_the_same_list_and_http_refuses_launch():
    preflight = PrerequisitePreflight(InMemoryOwnerPrerequisiteRepository())
    report = await preflight.assess(SCOPE, (definition(),))

    class BlockedLifecycle(FakeLifecycle):
        async def start(self, *args, **kwargs):
            raise PrerequisitesUnmet(report)

    facade = await manifests(BlockedLifecycle())
    facade.prerequisites = preflight
    facade._compiler = SimpleNamespace(
        compile=AsyncMock(return_value=SimpleNamespace(ok=True, definitions=(definition(),)))
    )
    grants = frozenset({"workflow_run.read", "catalog.read", "workflow_run.start"})
    client = TestClient(http_app(facade, grants))
    response = client.post(
        "/v1/applications/biotech/missions:preflight", json={"manifest_yaml": "fixture"}
    )
    assert response.status_code == 422
    assert response.json() == report.model_dump(mode="json")
    started = client.post("/v1/applications/biotech/missions:start", json={"run_id": "run-1"})
    assert started.status_code == 422
    assert started.json()["detail"] == {"code": "PREREQUISITES_UNMET", "report": response.json()}
    assert (
        await ScopedManifests({SCOPE: facade}).preflight(principal(grants), "fixture")
        == response.json()
    )


def test_cli_preflight_returns_nonzero_and_preserves_owner_steps(monkeypatch, capsys, tmp_path):
    import httpx

    from mission_control.interfaces.cli import main as cli

    payload = {"ready": False, "items": [{"steps": ["Owner action required"]}]}
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(422, json=payload)

    original = httpx.Client
    monkeypatch.setattr(
        cli.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    monkeypatch.setenv("MISSION_CONTROL_TOKEN", "fixture-token")
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION_ID", "biotech")
    path = tmp_path / "mission.yml"
    path.write_text("manifest: mission/v2", encoding="utf-8")
    assert cli.main(["preflight", str(path), "--json"]) == 2
    assert "Owner action required" in capsys.readouterr().out
    assert requests[0].url.path.endswith("/missions:preflight")


async def test_actual_manifest_preflight_and_require_match_sealed_claude_agent_sdk_identity(
    monkeypatch,
):
    from mission_control.application.authoring.manifest_service import MissionManifestService
    from mission_control.application.prerequisites.preflight import BoundClaudePrerequisiteIdentity
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
    lane = bound.providers.claude_agent_sdk
    bound = bound.model_copy(
        update={
            "providers": bound.providers.model_copy(
                update={
                    "claude_agent_sdk": lane.model_copy(
                        update={
                            "auth_profiles": {
                                key: pin.model_copy(update={"billing_mode": "api"})
                                for key, pin in lane.auth_profiles.items()
                            }
                        }
                    )
                }
            )
        }
    )
    yaml = example("claude_agent_sdk", "stage-graph").read_text()
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
            if item.prerequisite.id.startswith(("claude_agent_sdk.owner.a8.",))
        }

    assert len(select(report)) == 1
    assert select(report) == select(runtime)
    assert all(
        "Native Claude host identity:" in item.prerequisite.why
        for item in report.items
        if item.prerequisite.id in select(report)
    )
    with pytest.raises(PrerequisitesUnmet) as caught:
        await preflight.require(SCOPE, definition)
    assert select(caught.value.report) == select(report)
    changed = bound.model_copy(
        update={
            "providers": bound.providers.model_copy(
                update={
                    "claude_agent_sdk": bound.providers.claude_agent_sdk.model_copy(
                        update={
                            "model_profiles": {
                                **bound.providers.claude_agent_sdk.model_profiles,
                                "claude.default": bound.providers.claude_agent_sdk.model_profiles[
                                    "claude.default"
                                ].model_copy(update={"model_id": "different-selected-model"}),
                            }
                        }
                    ),
                }
            )
        }
    )
    preflight._native_identity = BoundClaudePrerequisiteIdentity(changed)
    fresh = await service.preflight(
        yaml, actor_id="owner", permissions=frozenset({"mission.read", "catalog.read"})
    )
    assert select(fresh).keys().isdisjoint(select(report))
    mismatch = await preflight.assess(SCOPE, (definition,), templates=sealed)
    assert not mismatch.ready
    assert any("sealed native identity differs" in reason for reason in mismatch.blockers)


async def test_claude_host_proof_refuses_subscription_before_observer():
    from mission_control.application.prerequisites.preflight import BoundClaudePrerequisiteIdentity
    from mission_control.domain.execution.data_class import DEFAULT_DATA_CLASS_POLICY
    from tests.unit.authoring.test_manifest_v2_launch import SCOPE, _compile, bindings, example

    bound = bindings()
    compilation = await _compile(
        example("claude_agent_sdk", "stage-graph").read_text(), SCOPE, DEFAULT_DATA_CLASS_POLICY
    )
    lane = bound.providers.claude_agent_sdk
    name, auth = next(iter(lane.auth_profiles.items()))
    changed = bound.model_copy(
        update={
            "providers": bound.providers.model_copy(
                update={
                    "claude_agent_sdk": lane.model_copy(
                        update={
                            "auth_profiles": {
                                name: auth.model_copy(update={"billing_mode": "subscription"})
                            }
                        }
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError, match="API-key route"):
        BoundClaudePrerequisiteIdentity(changed)(compilation.definitions[0].program.nodes[0], False)
