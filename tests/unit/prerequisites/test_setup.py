"""Owner wizard evidence, authorization and shell rendering regressions."""

import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from mission_control.application.prerequisites.preflight import PrerequisitePreflight
from mission_control.application.prerequisites.service import InMemoryOwnerPrerequisiteRepository
from mission_control.application.prerequisites.setup import (
    AttestRequest,
    OwnerSetupService,
    ProbeResult,
    ProbeUnavailable,
)
from mission_control.domain.prerequisites import EvidenceRefused, VerificationMethod
from mission_control.interfaces.cli import main as cli
from mission_control.interfaces.cli.setup import render_wizard
from tests.fixtures.provider_frames import SCOPE
from tests.unit.authoring.test_manifest_compile import http_app
from tests.unit.authoring.test_manifest_interfaces import FakeLifecycle, manifests


async def setup_service():
    repository = InMemoryOwnerPrerequisiteRepository()
    service = OwnerSetupService(repository)
    plan = await service.plan(SCOPE, "claude_managed")
    return service, plan


async def test_only_trusted_probe_can_verify_and_definition_cannot_change():
    service, plan = await setup_service()
    prerequisite = plan.items[0].prerequisite
    request = AttestRequest(definition_digest=prerequisite.digest, value="env_public")
    attested = await service.attest(SCOPE, prerequisite.id, request, actor_id="human-owner")
    assert attested.state == "attested"
    assert attested.evidence.evidence_ref == "owner:human-owner"
    with pytest.raises(ProbeUnavailable):
        await service.verify(SCOPE, prerequisite.id, prerequisite.digest)
    probe = AsyncMock(
        return_value=ProbeResult(
            method=VerificationMethod.API_PROBE,
            evidence_ref="artifact:actual-provider-readback",
        )
    )
    service.probes = SimpleNamespace(verify=probe)
    with pytest.raises(EvidenceRefused):
        await service.verify(SCOPE, prerequisite.id, "sha256:" + "0" * 64)
    probe.assert_not_awaited()
    result = await service.verify(SCOPE, prerequisite.id, prerequisite.digest)
    assert result.state == "verified"
    assert result.evidence.evidence_ref == "artifact:actual-provider-readback"
    assert not await service.repository.list("another-tenant")


async def test_http_owner_permissions_and_forged_probe_refusal():
    service, plan = await setup_service()
    facade = await manifests(FakeLifecycle())
    facade.owner_setup = service
    facade.prerequisites = PrerequisitePreflight(service.repository)
    prerequisite = plan.items[0].prerequisite
    base = f"/v1/applications/biotech/prerequisites/{prerequisite.id}"
    denied = TestClient(http_app(facade, frozenset({"workflow_run.start", "catalog.read"})))
    assert (
        denied.post(base + ":attest", json={"definition_digest": prerequisite.digest}).status_code
        == 403
    )
    client = TestClient(
        http_app(
            facade, frozenset({"prerequisite.read", "prerequisite.attest", "prerequisite.verify"})
        )
    )
    assert (
        client.post(
            "/v1/applications/biotech/prerequisites:setup", json={"target": "claude_managed"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            base + ":verify", json={"definition_digest": prerequisite.digest, "success": True}
        ).status_code
        == 422
    )
    assert (
        client.post(base + ":verify", json={"definition_digest": prerequisite.digest}).status_code
        == 503
    )
    assert (
        client.post(
            base + ":attest",
            json={"definition_digest": prerequisite.digest, "value": "sk-live-secret"},
        ).status_code
        == 422
    )
    response = client.post(base + ":attest", json={"definition_digest": prerequisite.digest})
    assert response.status_code == 200 and response.json()["state"] == "attested"
    # Public owner acceptance must not stand in for the declared trusted probe.
    response = client.post(
        "/v1/applications/biotech/prerequisites:setup", json={"target": "claude_managed"}
    )
    item = next(
        item for item in response.json()["items"] if item["prerequisite"]["id"] == prerequisite.id
    )
    assert item["assessment"]["standing"] == "unmet"
    assert not response.json()["ready"]


def test_generated_wizard_preserves_library_and_quotes_server_text(tmp_path):
    _, plan = asyncio.run(setup_service())
    first = plan.items[0]
    malicious = first.prerequisite.model_copy(
        update={
            "title": "Owner's $(touch BAD) `touch BAD`",
            "steps": ("Do not execute $(touch BAD); paste 'literal'",),
        }
    )
    plan = plan.model_copy(
        update={"items": (first.model_copy(update={"prerequisite": malicious}),)}
    )
    script = render_wizard(plan, application="biotech", url="https://mc.example", manifest=None)
    from mission_control.interfaces.cli import setup

    library = Path(setup.__file__).with_name("wizard_library.sh").read_text(encoding="utf-8")
    original = Path(".agents/skills/wizard/template.sh").read_text(encoding="utf-8")
    assert library == original[: original.index("# STAGES: author this section.")]
    assert script.startswith(library)
    assert "confirm" in script and " prereq attest " in script and " prereq verify " in script
    assert "--definition-digest" in script
    assert "MISSION_CONTROL_TOKEN=" not in script
    bash = shutil.which("bash")
    assert bash, "Git Bash is required for the wizard syntax proof"
    path = tmp_path / "wizard.sh"
    path.write_text(script, encoding="utf-8", newline="\n")
    checked = subprocess.run([bash, "-n", str(path)], capture_output=True, check=False)
    assert checked.returncode == 0, checked.stderr
    assert not (tmp_path / "BAD").exists()


def test_cli_generates_reviewable_script_without_launching_browser(monkeypatch, tmp_path):
    _, plan = asyncio.run(setup_service())
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=plan.model_dump(mode="json"))

    original = httpx.Client
    monkeypatch.setattr(
        cli.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    monkeypatch.setenv("MISSION_CONTROL_TOKEN", "fixture-token")
    monkeypatch.setenv("MISSION_CONTROL_APPLICATION_ID", "biotech")
    target = tmp_path / "setup.sh"
    assert cli.main(["setup", "claude_managed", "--script", str(target)]) == 0
    assert requests[0].url.path.endswith("/prerequisites:setup")
    assert "fixture-token" not in target.read_text(encoding="utf-8")
    assert "open_url" in target.read_text(encoding="utf-8")


def test_wizard_captures_public_environment_id_with_current_definition_digest():
    from mission_control.application.prerequisites.generators import generate_owner_prerequisites
    from mission_control.domain.capabilities.host_support import LaneProfile
    from tests.fixtures.owner_prerequisites import inputs

    _, plan = asyncio.run(setup_service())
    prerequisite = next(
        p
        for p in generate_owner_prerequisites(LaneProfile.CLAUDE_CLOUD, inputs())
        if any(isinstance(step, str) and "Record the public identifier" in step for step in p.steps)
    )
    selected = plan.model_copy(
        update={
            "items": (plan.items[0].model_copy(update={"prerequisite": prerequisite}),),
        }
    )
    script = render_wizard(selected, application="biotech", url="https://mc.example", manifest=None)
    assert "ask OWNER_ENV_ID" in script
    assert '--value "$OWNER_ENV_ID"' in script
    assert f"--definition-digest {prerequisite.digest}" in script
    assert "current definition digest" in script
