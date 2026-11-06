"""Declared agent aliases cross the native shell boundary without provider credentials.

The pinned native policy itself is exercised separately with synthetic values and
command/exec plus thread/shellCommand, never provider inference. These tests verify
the production launch integration, declaration scope and redaction on relaunch.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tomllib
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.codex import launcher as launcher_module
from mission_control.adapters.codex.launcher import shell_environment_overrides
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.secrets.broker import SecretBroker
from mission_control.application.secrets.delivery import ProcessSecretDelivery
from tests.unit.codex.drive import started
from tests.unit.codex.support import admission, codex_binding, codex_operation, codex_stack


def _policy(overrides: tuple[str, ...]) -> dict[str, Any]:
    return tomllib.loads("\n".join(overrides))["shell_environment_policy"]


def _contains_secret(root: Path, secret: str) -> bool:
    return any(secret.encode() in file.read_bytes() for file in root.rglob("*") if file.is_file())


def test_exact_names_only_allowlist_excludes_provider_and_unrelated_values() -> None:
    env = {
        "PATH": "/bin",
        "HOME": "/home/test",
        "OPENAI_API_KEY": "synthetic-provider",
        "CODEX_API_KEY": "synthetic-other-provider",
        "CUSTOM_AUTH": "synthetic-custom-provider",
        "MCP_TOKEN": "synthetic-mcp",
        "MISSION_CONTROL_TOKEN": "synthetic-agent",
        "UNRELATED_TOKEN": "synthetic-unrelated",
        "UNRELATED_PLAIN": "synthetic-plain",
        "CODEX_HOME": "/private/codex",
    }
    overrides = shell_environment_overrides(
        env,
        admission("api_key", credential_ref="env:CUSTOM_AUTH"),
        agent_names=("MISSION_CONTROL_TOKEN",),
    )
    policy = _policy(overrides)
    assert policy == {
        "inherit": "all",
        "ignore_default_excludes": True,
        "include_only": ["HOME", "MISSION_CONTROL_TOKEN", "PATH"],
    }
    assert all(value not in "\n".join(overrides) for value in env.values())
    assert _policy(shell_environment_overrides(env, admission("api_key")))["include_only"] == [
        "HOME",
        "PATH",
    ]


@pytest.mark.parametrize("name", ["*", "TOKEN?", "TOKEN[0]", "A.B"])
def test_glob_patterns_cannot_widen_native_allowlist(name: str) -> None:
    with pytest.raises(ValueError, match="literal variable names"):
        shell_environment_overrides({name: "not-disclosed"}, admission(), agent_names=(name,))


@pytest.mark.parametrize("name", ["OPENAI_API_KEY", "codex_api_key", "CUSTOM_AUTH"])
def test_declared_alias_cannot_shadow_provider_credential(name: str) -> None:
    with pytest.raises(ValueError, match="provider credentials"):
        shell_environment_overrides(
            {name: "not-disclosed"},
            admission("api_key", credential_ref="env:CUSTOM_AUTH"),
            agent_names=(name,),
        )


async def test_agent_phase_delivery_and_redaction_survive_relaunch(
    tmp_path: Path, caplog: Any
) -> None:
    secret = "synthetic-observer-secret-for-native-shell"
    setup_secret = "synthetic-setup-only-secret"
    broker = SecretBroker(
        environment=WorkerEnvironmentSource(
            {"OBSERVER_SOURCE": secret, "SETUP_SOURCE": setup_secret}
        )
    )
    binding = codex_binding(
        environment={
            "kind": "local_workspace",
            "host_profile": "worker.linux.wsl",
            "secret_refs": (
                "MISSION_CONTROL_TOKEN=environment:OBSERVER_SOURCE;agent",
                "SETUP_ONLY_TOKEN=environment:SETUP_SOURCE;setup",
            ),
        }
    )
    stack = codex_stack(tmp_path, operation=codex_operation(binding))
    stack.harness._secrets = ProcessSecretDelivery(broker)
    try:
        await started(stack)
        session = stack.harness._sessions[stack.heid]
        await stack.harness._terminate(session)
        await stack.harness._launch(session)
        assert len(stack.launcher.launches) == 2
        for launch in stack.launcher.launches:
            spec = launch.spec
            assert spec.env["MISSION_CONTROL_TOKEN"] == secret
            assert "SETUP_ONLY_TOKEN" not in spec.env
            policy = _policy(tuple(v for v in spec.config_overrides if v.startswith("shell_")))
            assert "MISSION_CONTROL_TOKEN" in policy["include_only"]
            assert "OPENAI_API_KEY" not in policy["include_only"]
            assert "SETUP_ONLY_TOKEN" not in policy["include_only"]
            assert secret in spec.sensitive_values
            assert secret not in json.dumps(spec.config_overrides)
            stream = asyncio.StreamReader()
            stream.feed_data(f"native diagnostic {secret}\n".encode())
            stream.feed_eof()
            tail: list[str] = []
            with caplog.at_level(logging.DEBUG, logger=launcher_module.__name__):
                await launcher_module._drain_stderr(stream, tail, 10, spec.sensitive_values)
            assert tail == ["native diagnostic [REDACTED]"]
        assert secret not in caplog.text and setup_secret not in caplog.text
        assert not await asyncio.to_thread(_contains_secret, tmp_path, secret)
    finally:
        for session in stack.harness._sessions.values():
            await stack.harness._terminate(session)
        await stack.launcher.shutdown()
