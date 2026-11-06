"""Conditional MA5 requirements derived from exact selected catalog MCP definitions."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import (
    MCPServerDefinition,
    MCPToolDefinition,
    PublishedDefinition,
)
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.capabilities.catalog_entry import capability_pin
from mission_control.domain.prerequisites import OwnerPrerequisite, Verification, VerificationMethod


class OAuthRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    server_pin: str = Field(min_length=1)
    server_url: str = Field(pattern=r"^https://[^\s]+$")


class OAuthCredentialBinding(OAuthRequirement):
    vault_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    credential_id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")


def oauth_probe_identity(requirements: tuple[OAuthRequirement, ...]) -> str:
    selected = sorted(
        ({"server_pin": item.server_pin, "server_url": item.server_url} for item in requirements),
        key=lambda item: item["server_pin"],
    )
    return "mcp_oauth_validate:" + sha256_digest(selected)


def require_oauth(
    prerequisite: OwnerPrerequisite, requirements: tuple[OAuthRequirement, ...]
) -> OwnerPrerequisite:
    return prerequisite.model_copy(
        update={
            "verify": Verification(
                method=VerificationMethod.API_PROBE, probe=oauth_probe_identity(requirements)
            ),
            "steps": (
                "Complete interactive OAuth grants for every exact selected MCP server:",
                *(f"{item.server_pin} at {item.server_url}" for item in requirements),
                "Mission Control validates every configured vault credential against "
                "its selected MCP server.",
            ),
        }
    )


class OAuthCatalog(Protocol):
    async def list_published_definitions(self) -> tuple[PublishedDefinition, ...]: ...


class CatalogOAuthRequirements:
    def __init__(self, definitions: OAuthCatalog, *, seed_urls: frozenset[str] = frozenset()):
        self._definitions = definitions
        self._seed_urls = seed_urls

    async def __call__(self, definition: MissionDefinition) -> tuple[OAuthRequirement, ...]:
        pins = []
        for item in definition.capabilities:
            if item.kind is None or item.kind.value in {"mcp_server", "mcp_tool"}:
                pin = item.resolved or item.pin
                if pin is None or pin.digest is None:
                    raise ValueError("OAuth applicability needs exact resolved MCP catalog pins")
                pins.append(f"{pin.capability_id}@{pin.version}#{pin.digest}")
        if not pins and not self._seed_urls:
            return ()
        rows = {
            capability_pin(row).render(): row
            for row in await self._definitions.list_published_definitions()
        }
        result = []
        known_urls = set()
        pending = sorted(set(pins))
        seen = set()
        while pending:
            pin_text = pending.pop(0)
            if pin_text in seen:
                continue
            seen.add(pin_text)
            row = rows.get(pin_text)
            if row is None or row.retired_at is not None:
                raise ValueError("selected MCP definition is missing, changed or retired")
            if isinstance(row.definition, MCPToolDefinition):
                server_ref = row.definition.server_ref
                server = next(
                    (
                        candidate
                        for candidate in rows.values()
                        if candidate.ref.logical_id == server_ref.logical_id
                        and candidate.ref.revision == server_ref.revision
                        and candidate.ref.digest == server_ref.digest
                    ),
                    None,
                )
                if server is None:
                    raise ValueError("selected MCP tool's exact server definition is unavailable")
                pending.append(capability_pin(server).render())
                continue
            if not isinstance(row.definition, MCPServerDefinition):
                continue
            if row.definition.endpoint is not None:
                known_urls.add(row.definition.endpoint)
            if row.definition.oauth is not None:
                if row.definition.transport != "streamable_http" or row.definition.endpoint is None:
                    raise ValueError(
                        "managed MCP OAuth requires an exact remote streamable HTTP endpoint"
                    )
                result.append(
                    OAuthRequirement(server_pin=pin_text, server_url=row.definition.endpoint)
                )
        if self._seed_urls - known_urls:
            raise ValueError(
                "hosted pack MCP servers lack selected catalog authentication metadata; "
                "OAuth applicability is unknown"
            )
        return tuple(sorted(result, key=lambda item: item.server_pin))
