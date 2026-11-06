"""Conditional OAuth and exact provider validation with no credential response disclosure."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.adapters.prerequisites.oauth import validate_managed_oauth
from mission_control.application.prerequisites.catalog import account_prerequisites
from mission_control.application.prerequisites.oauth import (
    CatalogOAuthRequirements,
    OAuthCredentialBinding,
    OAuthRequirement,
    require_oauth,
)
from mission_control.application.prerequisites.preflight import PrerequisitePreflight
from mission_control.application.prerequisites.probes import OwnerProbeBinding
from mission_control.application.prerequisites.service import InMemoryOwnerPrerequisiteRepository
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    MCPOAuthRefs,
    MCPServerDefinition,
    MCPToolDefinition,
)
from mission_control.domain.authoring.manifest import CapabilityKind
from mission_control.domain.authoring.mission_definition import CapabilityPin, DefinitionCapability
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord
from tests.fixtures.catalog.fast_track_catalog import fast_track_catalog
from tests.fixtures.provider_frames import SCOPE
from tests.unit.prerequisites.test_preflight import definition


def oauth_record():
    prerequisite = next(
        item
        for item in account_prerequisites(LaneProfile.CLAUDE_MANAGED)
        if item.id.endswith(".ma5")
    )
    requirement = OAuthRequirement(
        server_pin="mcp.example@1#sha256:" + "1" * 64, server_url="https://mcp.example.test"
    )
    record = OwnerPrerequisiteRecord.of(require_oauth(prerequisite, (requirement,)))
    binding = OwnerProbeBinding(
        request_scope=SCOPE,
        prerequisite_id=prerequisite.id,
        definition_digest=record.definition_digest,
        operation="managed_mcp_oauth",
        credentials=({"provider": "environment", "key": "API_KEY"},),
        oauth_credentials=(
            OAuthCredentialBinding(
                **requirement.model_dump(), vault_id="vlt_1", credential_id="vcrd_1"
            ),
        ),
    )
    return record, binding


@pytest.mark.parametrize("status", ["valid", "invalid"])
async def test_oauth_validates_exact_server_and_ids_without_returning_provider_body(status):
    record, binding = oauth_record()
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "id": "vcrd_1",
                    "vault_id": "vlt_1",
                    "archived_at": None,
                    "auth": {"type": "mcp_oauth", "mcp_server_url": "https://mcp.example.test"},
                },
            )
        assert request.method == "POST" and request.url.path.endswith("/mcp_oauth_validate")
        return httpx.Response(
            200,
            json={
                "credential_id": "vcrd_1",
                "vault_id": "vlt_1",
                "status": status,
                "validated_at": datetime.now(UTC).isoformat(),
                "mcp_probe": {"http_response": {"body": "private-response"}},
            },
        )

    client = ManagedAgentsClient(SecretStr("unit-test-key"), transport=httpx.MockTransport(handler))
    try:
        if status == "invalid":
            with pytest.raises(ProbeUnavailable):
                await validate_managed_oauth(client, binding, record)
        else:
            proof = await validate_managed_oauth(client, binding, record)
            assert "private-response" not in proof.evidence_ref
    finally:
        await client.aclose()
    assert len(calls) == 2


async def test_unknown_seed_mcp_auth_never_becomes_not_applicable():
    catalog = SimpleNamespace(list_published_definitions=lambda: None)

    async def empty():
        return ()

    catalog.list_published_definitions = empty
    resolver = CatalogOAuthRequirements(
        catalog, seed_urls=frozenset({"https://unknown.example.test"})
    )
    with pytest.raises(ValueError, match="applicability is unknown"):
        await resolver(definition().model_copy(update={"capabilities": ()}))


async def test_only_proven_empty_selection_omits_ma5_and_unknown_requires_probe():
    async def no_oauth(definition):
        return ()

    repository = InMemoryOwnerPrerequisiteRepository()
    report = await PrerequisitePreflight(repository, oauth_requirements=no_oauth).assess(
        SCOPE, (definition(),)
    )
    assert not any(item.prerequisite.id.endswith(".ma5") for item in report.items)
    unknown = await PrerequisitePreflight(repository).assess(SCOPE, (definition(),))
    ma5 = next(item for item in unknown.items if item.prerequisite.id.endswith(".ma5"))
    assert ma5.prerequisite.verify.method == "api_probe"
    assert ma5.assessment.blocking


async def test_managed_pack_oauth_unknown_does_not_block_other_selected_lanes():
    resolver = AsyncMock(side_effect=ValueError("unrepresented managed pack MCP"))
    preflight = PrerequisitePreflight(
        InMemoryOwnerPrerequisiteRepository(), oauth_requirements=resolver
    )
    native = await preflight.assess(SCOPE, (definition("deep_agents"),))
    assert native.ready
    resolver.assert_not_awaited()
    managed = await preflight.assess(SCOPE, (definition(),))
    assert not managed.ready
    assert "unrepresented managed pack MCP" in managed.blockers


async def test_explicit_mcp_tool_follows_its_exact_oauth_server_instead_of_claiming_na():
    catalog, _ = await fast_track_catalog()
    rows = await catalog.list_published_definitions()
    tool = next(row for row in rows if isinstance(row.definition, MCPToolDefinition))
    server = next(row for row in rows if row.ref.digest == tool.definition.server_ref.digest)
    assert isinstance(server.definition, MCPServerDefinition)
    server_definition = server.definition.model_copy(
        update={
            "oauth": MCPOAuthRefs(client_id_ref="CLIENT_ID"),
            "secret_refs": ("CLIENT_ID",),
            "transport": "streamable_http",
            "endpoint": "https://mcp.example.test",
        }
    )
    server = server.model_copy(
        update={
            "definition": server_definition,
            "ref": server.ref.model_copy(update={"digest": sha256_digest(server_definition)}),
        }
    )
    tool_definition = tool.definition.model_copy(update={"server_ref": server.ref})
    tool = tool.model_copy(
        update={
            "definition": tool_definition,
            "ref": tool.ref.model_copy(update={"digest": sha256_digest(tool_definition)}),
        }
    )

    async def published():
        return (tool, server)

    pin = capability_pin(tool)
    exact = CapabilityPin(capability_id=pin.capability_id, version=pin.version, digest=pin.digest)
    selected = definition().model_copy(
        update={
            "capabilities": (
                DefinitionCapability(
                    pointer="/mission/environment/capabilities/0",
                    role="capability",
                    kind=CapabilityKind.MCP_TOOL,
                    pin=exact,
                    resolved=exact,
                ),
            )
        }
    )
    requirements = await CatalogOAuthRequirements(
        SimpleNamespace(list_published_definitions=published)
    )(selected)
    assert len(requirements) == 1
    assert requirements[0].server_pin == capability_pin(server).render()
