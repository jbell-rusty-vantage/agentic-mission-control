"""W1 review S2: `mission-db tenant-*` recomputes the sealed binding digest of a deployment file
exactly as the runtime seals it (`ApplicationBinding`), without importing the runtime."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

from mission_control.application.installations.registry import (
    ApplicationBinding,
    HostedAgentApiTerms,
)
from mission_control_db_contract.errors import ContractError
from mission_control_db_contract.tenants import binding_digest

ROOT = Path(__file__).resolve().parents[3]


def _deployment_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sprint_oc_deployment_file", ROOT / "scripts" / "sprint_oc_deployment_file.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seal(**extra: object) -> dict[str, object]:
    binding = ApplicationBinding.seal(
        application_id="ai-engineer",
        installation_id=uuid4(),
        binding_version="sprint-oc-w1/1.8.0",
        supabase_project_ref="wkythqbofmckbuoothhn",
        database_secret_ref="MC_AIENG_DB_RUNTIME_DSN",
        accepted_issuers={"mission-control-operator/ai-engineer", "z-issuer", "a-issuer"},
        accepted_audiences={"mission-control/ai-engineer"},
        required_component_version="1.8.0",
        **extra,
    )
    return json.loads(binding.model_dump_json())


def test_parity_with_the_runtime_seal() -> None:
    plain = _seal()
    assert binding_digest(plain) == plain["binding_digest"]
    hosted = _seal(hosted_agent_apis=HostedAgentApiTerms(session_retention_seconds=60))
    assert "hosted_agent_apis" in hosted
    assert binding_digest(hosted) == hosted["binding_digest"]
    reordered = dict(plain, accepted_issuers=list(reversed(plain["accepted_issuers"])))
    assert binding_digest(reordered) == plain["binding_digest"]


@pytest.mark.parametrize("app", ["ai-engineer", "biotech"])
def test_parity_with_the_deployment_file_writer(app: str) -> None:
    document = _deployment_script().deployment_document(
        ROOT, app, component_version="1.8.0", namespace=f"mc-{app}", tenant=str(uuid4())
    )
    binding = json.loads(json.dumps(document["applications"][0]["authentication"]["binding"]))
    assert binding_digest(binding) == binding["binding_digest"]
    edited = dict(binding, required_component_version="1.7.0")
    assert binding_digest(edited) != binding["binding_digest"]


def test_unknown_binding_fields_refuse() -> None:
    with pytest.raises(ContractError) as refused:
        binding_digest(dict(_seal(), extra="x"))
    assert refused.value.code == "TENANT_DEPLOYMENT_INVALID"
