"""Validate selected managed MCP credentials without retaining provider response bodies."""

from datetime import datetime

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.application.prerequisites.oauth import oauth_probe_identity
from mission_control.application.prerequisites.probes import OwnerProbeBinding, ProbeObservation
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord


async def validate_managed_oauth(
    client: ManagedAgentsClient, binding: OwnerProbeBinding, record: OwnerPrerequisiteRecord
) -> ProbeObservation:
    if record.prerequisite.verify.probe != oauth_probe_identity(binding.oauth_credentials):
        raise ProbeUnavailable("OAuth credentials do not cover the exact selected MCP servers")
    observed = []
    for credential in binding.oauth_credentials:
        metadata = await client.retrieve_credential(credential.vault_id, credential.credential_id)
        auth = metadata.get("auth", {})
        if (
            metadata.get("id") != credential.credential_id
            or metadata.get("vault_id") != credential.vault_id
            or metadata.get("archived_at") is not None
            or auth.get("type") != "mcp_oauth"
            or auth.get("mcp_server_url") != credential.server_url
        ):
            raise ProbeUnavailable(
                "provider credential does not match its exact selected OAuth MCP server"
            )
        response = await client.validate_mcp_oauth(credential.vault_id, credential.credential_id)
        if (
            response.get("status") != "valid"
            or response.get("credential_id") != credential.credential_id
            or response.get("vault_id") != credential.vault_id
        ):
            raise ProbeUnavailable("the selected MCP OAuth grant did not validate")
        when = datetime.fromisoformat(str(response.get("validated_at", "")).replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ProbeUnavailable("OAuth validation did not carry an aware observation time")
        observed.append(when)
    if not observed:
        raise ProbeUnavailable("OAuth validation needs exact selected credential bindings")
    return ProbeObservation("mcp-oauth:" + sha256_digest(binding.oauth_credentials), min(observed))
