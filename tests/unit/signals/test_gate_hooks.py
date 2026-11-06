"""Synchronous gate projection and native fail-closed decisions."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mission_control.adapters.claude import hook_output as claude_output
from mission_control.adapters.codex import hook_output as codex_output
from mission_control.adapters.cursor import hook_output as cursor_output
from mission_control.application.agentic_components import signal_hook
from mission_control.application.agentic_components.telemetry import telemetry_hooks
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.bootstrap.settings import Settings
from mission_control.bootstrap.signals import configured_network_hosts
from mission_control.domain.authoring.manifest_v2 import ObservationPolicy
from mission_control.domain.capabilities.gates import SignalGatePolicy
from mission_control.domain.capabilities.host_support import LaneProfile


@pytest.mark.parametrize("lane", ["cursor_cloud", "cursor_local", "claude_cloud", "codex"])
def test_gate_hooks_are_synchronous_and_use_native_closed_decisions(lane: str) -> None:
    projection = HOST_PROJECTORS.render(
        (), lane, "mission", kernel_hooks=(), gates=SignalGatePolicy()
    )
    files = {item.path: item.content for item in projection.files}
    hooks_path = (
        ".cursor/hooks.json"
        if lane.startswith("cursor")
        else (".codex/hooks.json" if lane == "codex" else ".claude/settings.json")
    )
    hooks = json.loads(files[hooks_path])["hooks"]
    entries = hooks["preToolUse" if lane.startswith("cursor") else "PreToolUse"]
    handler = entries[-1] if lane.startswith("cursor") else entries[-1]["hooks"][0]
    assert "gate" in str(handler) and handler.get("async") is not True
    if lane.startswith("cursor"):
        assert handler["failClosed"] is True
    if lane == "claude_cloud":
        assert handler["onFailure"] == "block"
    policy = json.loads(files[".mission/signal-policy.json"])
    assert policy["gates"]["before_tool"]["fail_closed"] is True


@pytest.mark.parametrize("lane", ["codex_cloud", "claude_managed", "deep_agents"])
def test_a_lane_without_native_gate_enforcement_is_refused(lane: str) -> None:
    with pytest.raises(ValueError):
        HOST_PROJECTORS.render((), lane, "mission", gates=SignalGatePolicy())


@pytest.mark.parametrize("closed", [True, False])
def test_unreachable_ingress_uses_the_declared_gate_policy(
    tmp_path: Path, monkeypatch, closed: bool
) -> None:
    monkeypatch.delenv("MC_SIGNAL_URL", raising=False)
    monkeypatch.delenv("MC_SIGNAL_TOKEN", raising=False)
    policy = {
        "lane_profile": "cursor_cloud",
        "signals": {},
        "gates": {"before_tool": {"fail_closed": closed}},
    }
    # The Cursor lane's projection places its answer module beside the script (OC-R3).
    native = tmp_path / ".mission" / "hooks" / "native_output.py"
    native.parent.mkdir(parents=True)
    native.write_bytes(Path(cursor_output.__file__).read_bytes())
    answer = json.loads(signal_hook.gate(tmp_path, policy, "before_tool", "{}"))
    assert answer["permission"] == ("deny" if closed else "allow")


def test_observation_off_cannot_disable_a_declared_gate() -> None:
    with pytest.raises(ValidationError):
        ObservationPolicy(in_environment="off", gates=SignalGatePolicy())


def test_native_stop_answers_block_without_requesting_another_turn() -> None:
    assert claude_output.native_gate_output("claude_cloud", "stop", "stop_fenced") == {
        "continue": False,
        "stopReason": "stop_fenced",
    }
    cursor = cursor_output.native_gate_output("cursor_cloud", "stop", "stop_fenced")
    assert cursor["permission"] == "deny" and "followup_message" not in cursor
    codex = codex_output.native_gate_output("codex", "stop", "stop_fenced")
    assert codex["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize(
    "origin",
    [
        "http://ingress.example",
        "https://user:secret@ingress.example",
        "https://ingress.example/path",
    ],
)
def test_signal_origin_requires_an_explicit_credential_free_https_origin(origin: str) -> None:
    with pytest.raises(ValueError):
        configured_network_hosts(
            Settings(_env_file=None, mission_control_signal_ingress_origin=origin)
        )


def test_preflight_and_launch_receive_the_configured_ingress_host() -> None:
    hosts = configured_network_hosts(
        Settings(_env_file=None, mission_control_signal_ingress_origin="https://ingress.example")
    )
    assert hosts.signal_ingress == "ingress.example"


@pytest.mark.parametrize("lane", ["cursor_cloud", "claude_cloud", "codex"])
@pytest.mark.parametrize("policy_bytes", [None, b"{malformed"])
def test_missing_or_malformed_policy_keeps_the_projected_native_deny_shape(
    tmp_path: Path, lane: str, policy_bytes: bytes | None
) -> None:
    policy = SignalGatePolicy()
    projection = HOST_PROJECTORS.render((), lane, "mission", kernel_hooks=(), gates=policy)
    for item in projection.files:
        path = tmp_path / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(item.content)
    policy_path = tmp_path / ".mission/signal-policy.json"
    if policy_bytes is None:
        policy_path.unlink()
    else:
        policy_path.write_bytes(policy_bytes)
    command = next(hook.command for hook in telemetry_hooks(LaneProfile(lane), policy) if hook.gate)
    result = subprocess.run(
        [sys.executable, *command[1:]],
        cwd=tmp_path,
        input="{}",
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
        env={
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP")
            if key in os.environ
        },
    )
    assert result.returncode == 0
    answer = json.loads(result.stdout)
    if lane == "cursor_cloud":
        assert answer["permission"] == "deny"
    else:
        assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"


def _gate(tmp_path: Path, lane: str) -> tuple[Path, list[str]]:
    policy = SignalGatePolicy()
    projection = HOST_PROJECTORS.render((), lane, "mission", kernel_hooks=(), gates=policy)
    for item in projection.files:
        path = tmp_path / item.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(item.content)
    command = next(hook.command for hook in telemetry_hooks(LaneProfile(lane), policy) if hook.gate)
    return tmp_path, list(command)


def _run_gate(tmp_path: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *command[1:]],
        cwd=tmp_path,
        input="{}",
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
        env={
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP")
            if key in os.environ
        },
    )


@pytest.mark.parametrize("lane", ["cursor_cloud", "claude_cloud", "codex"])
@pytest.mark.parametrize("damage", ["missing", "corrupt", "broken"])
def test_a_gate_without_a_usable_lane_answer_module_blocks(
    tmp_path: Path, lane: str, damage: str
) -> None:
    """The gate's own fallback cannot load the lane's answer either: it blocks (exit 2)."""

    root, command = _gate(tmp_path, lane)
    native = root / ".mission" / "hooks" / "native_output.py"
    if damage == "missing":
        native.unlink()
    elif damage == "corrupt":
        native.write_text("def native_gate_output(:" + chr(10), encoding="utf-8")
    else:
        native.write_text("def native_gate_output(*_args):" + chr(10) + "    raise RuntimeError()")
    result = _run_gate(root, command)
    answer = json.loads(result.stdout)
    assert result.returncode == 2 and _refused_on(lane, answer, result.returncode)
    assert answer["decision"] == "block" and answer["permission"] == "deny"
    assert not list((root / ".mission").rglob("__pycache__"))


def test_a_gate_leaves_no_bytecode_in_the_workspace(tmp_path: Path) -> None:
    root, command = _gate(tmp_path, "codex")
    assert _run_gate(root, command).returncode == 0
    assert not list((root / ".mission").rglob("__pycache__"))


def _refused_on(lane: str, out: dict[str, Any], code: int) -> bool:
    """How each lane reads a hook answer as a refusal: Cursor `permission: deny` (exit 2
    denies), Claude Code a blocking exit 2 with `decision: block`, Codex the PreToolUse deny
    shape of its pinned drill (`hookSpecificOutput.permissionDecision`)."""

    if lane.startswith("cursor"):
        return out.get("permission") == "deny" and code == 2
    if lane.startswith("claude"):
        return out.get("decision") == "block" and code == 2
    specific = out.get("hookSpecificOutput") or {}
    return (
        specific.get("hookEventName") == "PreToolUse"
        and specific.get("permissionDecision") == "deny"
        and bool(specific.get("permissionDecisionReason"))
    )
