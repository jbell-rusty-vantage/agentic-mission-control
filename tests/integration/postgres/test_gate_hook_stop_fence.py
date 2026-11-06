"""Projected remote gate blocks the first tool after a real persisted Stop Fence."""

import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from mission_control.adapters.postgres.run_control.stop_fence import PostgresStopFenceRepository
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.adapters.temporal.local_signals import RemoteSignalDelivery
from mission_control.application.secrets.broker import SecretBroker
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.capabilities.gates import SignalGatePolicy
from mission_control.domain.execution.network_policy import ResolvedNetworkPolicy
from mission_control.domain.policies.stop_fence import StopFence
from mission_control.interfaces.http.ingress import create_ingress_app
from tests.fixtures.lane_turns import cursor_binding, cursor_operation
from tests.fixtures.scoped_api_stack import serve_loopback
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_signal_ingress_postgres import (  # noqa: F401
    GATE_CONTEXT,
    Ingress,
    gate_body,
    ingress,
)

pytestmark = pytest.mark.common_db


def invoke(root: Path, env: dict[str, str], tool_id: str) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(root / ".mission/hooks/signal"),
            "gate",
            "cursor_cloud",
            "before_tool",
        ],
        cwd=root,
        input=json.dumps(
            {
                "tool_name": "Shell",
                "tool_call_id": tool_id,
                "tool_input": {"command": "echo private-command-must-not-cross-ingress"},
            }
        ),
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
        env={
            **{
                name: os.environ[name]
                for name in ("PATH", "SYSTEMROOT", "TEMP", "TMP")
                if name in os.environ
            },
            **env,
        },
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


async def test_cancel_fence_denies_the_very_next_projected_tool_call(
    ingress: Ingress,  # noqa: F811
    tmp_path: Path,
) -> None:
    token = await ingress.minter.mint("signal_token", ingress.binding, context=GATE_CONTEXT)
    projection = HOST_PROJECTORS.render(
        (), "cursor_cloud", "mission", kernel_hooks=(), gates=SignalGatePolicy()
    )
    for item in projection.files:
        path = tmp_path / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(item.content)
    async with serve_loopback(create_ingress_app([ingress.service])) as origin:
        env = {
            "MC_SIGNAL_URL": f"{origin}/v1/ingress/biotech/signals",
            "MC_SIGNAL_TOKEN": token.value,
        }
        allowed = await asyncio.to_thread(invoke, tmp_path, env, "tool-before-cancel")
        assert allowed["permission"] == "allow"
        assert await asyncio.to_thread(invoke, tmp_path, env, "tool-before-cancel") == allowed
        await PostgresStopFenceRepository(ingress.runtime).persist(
            StopFence(
                request_scope=ingress.scope,
                run_id=ingress.run_key,
                generation=1,
                command_id="cancel-gated",
                reason="operator stop",
                requested_at=datetime.now(UTC),
            )
        )
        blocked = await asyncio.to_thread(invoke, tmp_path, env, "tool-after-cancel")
        assert blocked == {"permission": "deny", "agent_message": "stop_fenced"}
    rows = await ingress.owner(
        "SELECT payload FROM mission_control.ingress_inbox WHERE kind='gate.decision'"
    )
    assert len(rows) == 2
    assert "private-command" not in json.dumps([dict(row) for row in rows])
    intents = await ingress.owner("SELECT intent_id FROM mission_control.hook_effect_intent")
    assert len(intents) == 1, "no Operation Intent for the blocked tool"


async def test_remote_delivery_mints_the_context_the_sql_gate_requires(
    ingress: Ingress,  # noqa: F811
) -> None:
    network = ResolvedNetworkPolicy(
        mode="allowlist", hosts=("ingress.example",), signal_ingress="ingress.example"
    )
    binding = cursor_binding("cursor_cloud", signal_gates=SignalGatePolicy(), network=network)
    operation = cursor_operation("cursor_cloud", binding=binding, request_scope=ingress.scope)
    identity = SimpleNamespace(
        request_scope=ingress.scope,
        run_key=ingress.run_key,
        activation_key=ingress.unit_key,
        attempt_no=1,
        lane_profile="cursor_cloud",
        harness_execution_id=GATE_CONTEXT["harness_execution_id"],
    )
    delivery = RemoteSignalDelivery(
        SecretBroker(environment=WorkerEnvironmentSource()),
        ingress.runtime,
        origin="https://ingress.example",
    )
    values = await delivery(operation, identity)
    assert values["MC_SIGNAL_URL"] == "https://ingress.example/v1/ingress/biotech/signals"
    answer = await ingress.service.gate(
        gate_body("remote-minted", "remote-effect"),
        {"authorization": f"Bearer {values['MC_SIGNAL_TOKEN']}"},
    )
    assert answer.decision == "allow", "the minted credential carried trusted harness context"
