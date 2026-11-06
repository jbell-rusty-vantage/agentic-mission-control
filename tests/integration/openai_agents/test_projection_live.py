"""HL21 opt-in control-plane projection/readback proof; no inference or external credentials."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr
from tests.fixtures.projections.rows import skill_row
from tests.integration.anthropic_managed.test_approval_publication_live import (
    drill_pack as managed_pack,
)
from tests.integration.openai_agents.test_function_tools_live import drill_pack as agents_pack

from mission_control.adapters.anthropic_managed.client import ManagedAgentsClient
from mission_control.adapters.anthropic_managed.prepare import ClaudeManagedPrepare
from mission_control.adapters.openai_agents.client import AgentsApiClient
from mission_control.adapters.openai_agents.prepare import CodexAgentsPreparer
from mission_control.adapters.remote_session.projection import configuration, project
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.secrets.broker import SecretBroker

LIVE = os.environ.get("MC_HL21_PROJECTION_LIVE") == "1"
pytestmark = pytest.mark.skipif(
    not LIVE, reason="opt-in real hosted projection control-plane calls"
)


@pytest.mark.parametrize("profile", ["claude_managed", "codex_agents"])
async def test_projected_unchanged_pack_creates_zero_resources_on_readback(tmp_path, profile):
    stamp = uuid4().hex[:10]
    managed = profile == "claude_managed"
    original = managed_pack(tmp_path) if managed else agents_pack(tmp_path, stamp)[0]
    skill = skill_row()
    skill = skill.model_copy(
        update={
            "definition": skill.definition.model_copy(
                update={
                    "frontmatter": {
                        "name": "agent-browser",
                        "description": "Drive a real browser with agent-browser.",
                    }
                }
            )
        }
    )
    rows = (skill,)
    projected = project(profile, configuration(original), rows, installation_id="local")

    def digest(pack):
        return pack.materialization_digest if managed else pack.digest

    assert digest(projected) != digest(original)
    api = (
        ManagedAgentsClient(SecretStr(os.environ["ANTHROPIC_API_KEY"]))
        if managed
        else AgentsApiClient(SecretStr(os.environ["OPENAI_API_KEY"]))
    )
    created, writes, readbacks = [], [], []
    paths = {
        "/v1/agents": "agent",
        "/v1/skills": "skill",
        "/v1/environments": "environment",
        "/v1/agents/environments/templates": "template",
        "/v1/vaults": "vault",
    }

    async def observe(response):
        kind = paths.get(response.request.url.path)
        if response.request.method == "POST" and kind:
            writes.append(kind)
            if response.is_success:
                await response.aread()
                row = response.json()
                sent = json.loads(response.request.content) if kind != "skill" else {}
                readbacks.append(
                    {
                        "kind": kind,
                        "response_fields": sorted(row),
                        "name_matches": row.get("name") == sent.get("name"),
                        "metadata_matches": row.get("metadata") == sent.get("metadata"),
                    }
                )
                created.append((kind, row["id"]))

    api._client.event_hooks["response"].append(observe)
    record = {
        "profile": profile,
        "projection_driver": "production project()",
        "catalog_capability_pins": [row.definition.logical_id for row in rows],
        "catalog_scope": "controlled fixture skill; no execution",
        "vaults": 0,
        "network_hosts": [],
        "inference_calls": 0,
        "normal_deployment_bindings": "not_exercised",
        "cleanup": {},
    }
    evidence = Path(os.environ["MC_HL21_EVIDENCE_DIR"]) / (profile + "-projection-readback.json")
    assert evidence.parent.is_dir()
    preparer = (
        ClaudeManagedPrepare(
            api,
            SecretBroker(environment=WorkerEnvironmentSource({})),
            installation_id="local",
            labels={"mc_run": "run1-HL21-" + stamp},
        )
        if managed
        else CodexAgentsPreparer(
            api, WorkerEnvironmentSource({}), labels={"mc_run": "run1-HL21-" + stamp}
        )
    )
    try:
        await preparer.sync(projected)
        baseline = len(writes)
        second_projected = project(profile, configuration(original), rows, installation_id="local")
        assert digest(second_projected) == digest(projected)
        second = await preparer.sync(second_projected)
        record["first_resource_create_calls"] = baseline
        record["second_resource_create_calls"] = len(writes) - baseline
        record["unchanged_projection_digest"] = digest(projected)
        if managed:
            record["second_readback_actions"] = [second.agent.action, second.environment.action] + [
                skill.action for skill in second.skills
            ]
        else:
            record["second_readback_actions"] = [item.outcome for item in second.resources]
        assert record["second_resource_create_calls"] == 0
        assert all(action == "reused" for action in record["second_readback_actions"])
        record["passed"] = True
    except Exception as error:
        record["failure_type"] = type(error).__name__
        raise
    finally:
        for kind, resource in reversed(created):
            try:
                delete = (
                    {
                        "agent": api.archive_agent,
                        "environment": api.delete_environment,
                        "vault": api.delete_vault,
                        "skill": api.delete_skill,
                    }
                    if managed
                    else {
                        "agent": api.delete_agent,
                        "template": api.delete_environment_template,
                        "vault": api.delete_vault,
                    }
                )[kind]
                await delete(resource)
                record["cleanup"][resource] = (
                    "archived" if managed and kind == "agent" else "deleted"
                )
            except Exception as error:
                record["cleanup"][resource] = type(error).__name__
        record["cleanup_complete"] = all(
            value in {"deleted", "archived"} for value in record["cleanup"].values()
        )
        if not record["cleanup_complete"]:
            record["passed"] = False
        record["resource_readbacks"] = readbacks
        await asyncio.to_thread(evidence.write_text, json.dumps(record, indent=2, sort_keys=True))
        await api.aclose()
        assert all(value in {"deleted", "archived"} for value in record["cleanup"].values())
