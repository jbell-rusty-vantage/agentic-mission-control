from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from cursor_sdk._bridge import BridgeEndpoint
from cursor_sdk.errors import AuthenticationError, NetworkError, RateLimitError

from mission_control.adapters.cursor.bridge import (
    ProviderAccessDenied,
    ProviderTransient,
    host_gate,
    provider_error,
)
from mission_control.adapters.cursor.bridge_spawn import (
    DISCOVERY_FILE,
    _load_endpoint,
    _save_endpoint,
    launch_bridge_client,
)
from mission_control.adapters.cursor.cloud_api import _raise
from mission_control.application.execution.harness.dispatch import ProviderCapacityLimited


@pytest.mark.parametrize(
    ("native", "expected"),
    [
        (AuthenticationError("secret provider text", request_id="req-1"), ProviderAccessDenied),
        (NetworkError("secret provider text", request_id="req-1"), ProviderTransient),
        (
            RateLimitError("secret provider text", request_id="req-1", retry_after="13"),
            ProviderCapacityLimited,
        ),
    ],
)
def test_sdk_error_taxonomy_keeps_safe_identity(native, expected):
    error = provider_error(native)
    assert isinstance(error, expected) and error.request_id == "req-1"
    assert "secret provider text" not in str(error)
    if isinstance(error, ProviderCapacityLimited):
        assert error.signal.resets_at is not None


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, ProviderAccessDenied), (403, ProviderAccessDenied), (503, ProviderTransient)],
)
def test_cloud_error_taxonomy(status, expected):
    response = httpx.Response(
        status, json={"error": {"message": "private secret"}}, headers={"x-request-id": "req-2"}
    )
    with pytest.raises(expected) as caught:
        _raise(response, "fixture")
    assert caught.value.request_id == "req-2" and "private secret" not in str(caught.value)


def test_windows_requires_explicit_unqualified_switch():
    assert not host_gate(system="Windows", release="11", event_loop="SelectorEventLoop").supported
    assert host_gate(
        system="Windows", release="11", event_loop="SelectorEventLoop", windows_enabled=True
    ).supported


async def test_detached_endpoint_is_reused_and_client_does_not_own_process(
    tmp_path: Path, monkeypatch
):
    from mission_control.adapters.cursor import bridge_spawn

    state = tmp_path / "state"
    state.mkdir()
    endpoint = BridgeEndpoint("http://127.0.0.1:12345", "private-token", state_root=str(state))
    spawned = []

    def spawn(*args):
        spawned.append(args)
        return endpoint

    class Client:
        async def ping(self):
            return "pong"

        async def get_version(self):
            return {"version": "fixture", "schemaVersion": 1}

        async def aclose(self):
            pass

    client = Client()
    monkeypatch.setattr(bridge_spawn, "_spawn_endpoint", spawn)
    monkeypatch.setattr(bridge_spawn.AsyncClient, "connect", lambda *a, **kw: client)
    for _ in range(2):
        connected = await launch_bridge_client(
            None,
            workspace=tmp_path,
            state_root=state,
            environment={"PATH": "fixture"},
            discovery_timeout_s=1,
        )
        assert connected is client
        await connected.aclose()
    assert len(spawned) == 1
    assert (state / DISCOVERY_FILE).exists()
    assert _load_endpoint(state / DISCOVERY_FILE, tmp_path, state) == endpoint
    with pytest.raises(RuntimeError, match="workspace"):
        _load_endpoint(state / DISCOVERY_FILE, tmp_path / "other", state)


def test_discovery_rejects_remote_endpoint(tmp_path: Path):
    endpoint = BridgeEndpoint("https://example.org", "private-token")
    path = tmp_path / DISCOVERY_FILE
    _save_endpoint(path, endpoint, tmp_path, tmp_path)
    with pytest.raises(RuntimeError, match="loopback"):
        _load_endpoint(path, tmp_path, tmp_path)


def test_windows_selector_fixture_launch_send_observe_reconnect_shutdown(tmp_path, monkeypatch):
    import asyncio
    import json
    import os
    import signal
    import sys
    from types import SimpleNamespace

    from cursor_sdk.asyncio import AsyncAgent
    from pydantic import SecretStr

    from mission_control.adapters.cursor import bridge_spawn
    from mission_control.adapters.cursor.bridge import LocalAgentSpec, SdkBridgeLauncher

    if sys.platform != "win32":
        pytest.skip("exact Windows Selector fixture; other OS is not Windows evidence")
    state = tmp_path / "state"
    script = tmp_path / "fixture_bridge.py"
    script.write_text(
        "import json,os,sys,time\n"
        "print('cursor-sdk-bridge ready '+json.dumps({'schemaVersion':1,"
        "'transport':'tcp','protocol':'connect','url':'http://127.0.0.1:12345',"
        "'authToken':'fixture-token','pid':os.getpid()}),file=sys.stderr,flush=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    runs = []
    closed = []

    class Agent:
        agent_id = "fixture-agent"

        async def send(self, text, options=None, idempotency_key=None):
            runs.append((text, idempotency_key))
            return SimpleNamespace(id="fixture-run")

        async def close(self):
            closed.append(True)

    class Client:
        async def ping(self):
            return "pong"

        async def get_version(self):
            return {"schemaVersion": 1, "version": "fixture"}

        async def aclose(self):
            pass

        async def shutdown(self, grace_seconds=0):
            record = json.loads((state / DISCOVERY_FILE).read_text(encoding="utf-8"))
            os.kill(record["endpoint"]["pid"], signal.SIGTERM)

        async def observe_run(self, run_id, after_offset=None):
            yield SimpleNamespace(offset="1", kind="done", done={})

    client = Client()

    async def create(*args, **kwargs):
        return Agent()

    monkeypatch.setattr(AsyncAgent, "create", create)
    monkeypatch.setattr(bridge_spawn.AsyncClient, "connect", lambda *a, **kw: client)

    async def scenario():
        launcher = SdkBridgeLauncher(
            SecretStr("fixture-only"),
            bridge_command=[sys.executable, str(script)],
            windows_enabled=True,
        )
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR"}
        }
        try:
            bridge = await launcher.launch(
                workspace=tmp_path, state_root=state, environment=environment
            )
            agent = await bridge.create_agent(
                LocalAgentSpec(model="fixture", name="fixture", cwd=str(tmp_path))
            )
            run = await bridge.send(agent, "fixture prompt", idempotency_key="fixture-key")
            events = [event async for event in bridge.observe(run, after_offset=None)]
            assert len(events) == 1 and runs == [("fixture prompt", None)]
            await bridge.close_agent(agent)
            await bridge.aclose()
            endpoint_before = (state / DISCOVERY_FILE).read_bytes()
            again = await launcher.launch(
                workspace=tmp_path, state_root=state, environment=environment
            )
            assert (state / DISCOVERY_FILE).read_bytes() == endpoint_before
            await again.aclose()
            assert closed == [True]
        finally:
            await bridge_spawn.shutdown_bridge(state, workspace=tmp_path)

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(scenario())
    assert not (state / DISCOVERY_FILE).exists()


@pytest.mark.parametrize("force", [False, True])
async def test_local_send_uses_sdk_wire_without_cloud_only_idempotency_key(force):
    from types import SimpleNamespace
    from typing import Any, cast

    from cursor_sdk.asyncio import AsyncAgent

    from mission_control.adapters.cursor.bridge import SdkLocalBridge

    requests = []

    async def events():
        yield {
            "offset": "1",
            "result": {
                "result": {
                    "runId": "fixture-run",
                    "agentId": "fixture-agent",
                    "status": "completed",
                }
            },
        }

    async def stream(method, request, **kwargs):
        # Match the pinned bridge's local Send boundary, without starting a bridge.
        assert method == "Send"
        assert not request["idempotencyKey"]
        requests.append(request)
        return events()

    client = SimpleNamespace(_allow_api_key_env_fallback=False, _agent_stream=stream)
    agent = AsyncAgent(
        client=cast("Any", client),
        agent_id="fixture-agent",
        model=None,
        api_key="fixture-only",
    )
    bridge = SdkLocalBridge(client=client, api_key="fixture-only", agents={agent.agent_id: agent})

    run = await bridge.send(
        agent.agent_id, "fixture prompt", idempotency_key="execution:1:turn:1", force=force
    )

    assert run == "fixture-run"
    assert len(requests) == 1
    assert requests[0]["options"]["force"] is force
