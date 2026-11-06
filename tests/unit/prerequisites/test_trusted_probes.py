from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import asyncpg
import httpx
import pytest

from mission_control.adapters.prerequisites.probes import ProviderOwnerProbeExecutor
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.prerequisites.catalog import account_prerequisites
from mission_control.application.prerequisites.probes import (
    ConfiguredOwnerProbes,
    OwnerProbeBinding,
    OwnerProbeConfiguration,
    ProbeObservation,
)
from mission_control.application.prerequisites.setup import ProbeUnavailable
from mission_control.application.secrets.broker import SecretBroker
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord


def record_for(profile: str, code: str) -> OwnerPrerequisiteRecord:
    prerequisite = next(
        item for item in account_prerequisites(LaneProfile(profile)) if item.id.endswith("." + code)
    )
    return OwnerPrerequisiteRecord.of(prerequisite)


def configured(record: OwnerPrerequisiteRecord, operation: str, handler: object):
    binding = OwnerProbeBinding.model_validate(
        {
            "request_scope": "scope-a",
            "prerequisite_id": record.prerequisite.id,
            "definition_digest": record.definition_digest,
            "operation": operation,
            "credentials": [{"provider": "environment", "key": "PROBE_KEY"}],
        }
    )
    broker = SecretBroker(environment=WorkerEnvironmentSource({"PROBE_KEY": "private-test-value"}))
    executor = ProviderOwnerProbeExecutor(
        broker,
        cast(asyncpg.Pool, None),
        transport=httpx.MockTransport(handler),
    )
    return ConfiguredOwnerProbes(OwnerProbeConfiguration(bindings=(binding,)), executor)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "code", "operation", "header"),
    [
        ("claude_managed", "ma1", "managed_agents_access", "x-api-key"),
        ("codex_agents", "oa1", "agents_api_access", "authorization"),
    ],
)
async def test_provider_access_is_read_only_scoped_and_returns_no_credentials(
    profile: str,
    code: str,
    operation: str,
    header: str,
) -> None:
    record = record_for(profile, code)
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET" and request.url.path == "/v1/agents"
        assert "private-test-value" in request.headers[header]
        return httpx.Response(200, json={"data": [], "has_more": False})

    probes = configured(record, operation, handle)
    proof = await probes.verify("scope-a", record)
    assert proof.method == record.prerequisite.verify.method
    assert "private-test-value" not in proof.model_dump_json()
    assert proof.expires_at is not None and proof.expires_at > datetime.now(UTC)
    with pytest.raises(ProbeUnavailable, match="scoped prerequisite"):
        await probes.verify("scope-b", record)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_stale_or_wrong_probe_never_issues_verified_evidence() -> None:
    record = record_for("claude_managed", "ma1")

    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call provider")

    probes = configured(record, "managed_agents_access", forbidden)
    changed = record.prerequisite.model_copy(update={"title": "changed setup"})
    with pytest.raises(ProbeUnavailable, match="stale"):
        await probes.verify("scope-a", OwnerPrerequisiteRecord.of(changed))
    wrong = configured(record, "agents_api_access", forbidden)
    with pytest.raises(ProbeUnavailable, match="does not prove"):
        await wrong.verify("scope-a", record)


@pytest.mark.asyncio
async def test_provider_failure_redacts_response_body_and_never_follows_redirect() -> None:
    record = record_for("codex_agents", "oa1")
    calls = []

    def redirect(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            302, headers={"Location": "https://untrusted.invalid/key"}, text="private-test-value"
        )

    with pytest.raises(ProbeUnavailable) as error:
        await configured(record, "agents_api_access", redirect).verify("scope-a", record)
    assert "private-test-value" not in str(error.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_reverification_cannot_extend_old_receipt_freshness() -> None:
    record = record_for("claude_managed", "ma2")
    binding = OwnerProbeBinding(
        request_scope="scope-a",
        prerequisite_id=record.prerequisite.id,
        definition_digest=record.definition_digest,
        operation="signed_webhook",
        run_key="probe-run",
        binding_digest="sha256:" + "1" * 64,
        max_age_seconds=3600,
    )
    at = datetime.now(UTC) - timedelta(minutes=59)
    executor = SimpleNamespace(check=AsyncMock(return_value=ProbeObservation("receipt:1", at)))
    probes = ConfiguredOwnerProbes(OwnerProbeConfiguration(bindings=(binding,)), executor)
    first = await probes.verify("scope-a", record)
    second = await probes.verify("scope-a", record)
    assert first.expires_at == second.expires_at == at + timedelta(hours=1)
    executor.check.return_value = ProbeObservation("receipt:old", at - timedelta(hours=2))
    with pytest.raises(ProbeUnavailable, match="stale"):
        await probes.verify("scope-a", record)
