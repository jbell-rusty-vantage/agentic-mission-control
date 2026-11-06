"""FT-A5: the projected ``.mission/hooks/run.py`` adapts native hook payloads per lane."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.claude import hook_output as claude_output
from mission_control.adapters.codex import hook_output as codex_output
from mission_control.adapters.cursor import hook_output as cursor_output
from mission_control.application.agentic_components import hook_runner
from mission_control.application.agentic_components.projections import (
    HOOK_RUNNER_SCRIPT,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.projection import BundleFile, ResolvedCapability
from mission_control.domain.authoring.contracts import HookScriptDefinition
from mission_control.domain.capabilities.host_support import LaneProfile, all_profiles
from mission_control.domain.capabilities.pins import CapabilityPin

POLICY = Path(__file__).resolve().parents[3] / "scripts" / "hooks" / "policy_template" / "policy.py"


def _policy_row() -> ResolvedCapability:
    content = POLICY.read_bytes().replace(b"\r\n", b"\n")
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    definition = HookScriptDefinition.model_validate(
        {
            "logical_id": "hook.mc-policy-template",
            "title": "Policy template",
            "description": "Denies destructive commands.",
            "events": ["before_shell", "before_tool"],
            "fail_closed": True,
            "file_manifest": [{"path": "policy.py", "digest": digest, "size_bytes": len(content)}],
            "manifest_digest": digest,
            "entrypoint": "policy.py",
            "interpreter": "python",
            "host_support": all_profiles().model_dump(mode="json"),
        }
    )
    return ResolvedCapability(
        pin=CapabilityPin(capability_id="hook.mc-policy-template", version="1.0.0", digest=digest),
        definition=definition,
        files=(BundleFile(path="policy.py", content=content),),
    )


def _materialize(profile: LaneProfile, root: Path) -> None:
    projection = HOST_PROJECTORS.render((_policy_row(),), profile, "instructions")
    for item in projection.files:
        target = root / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.content)


def _run(root: Path, event: str, payload: dict[str, object]) -> tuple[dict[str, object], int]:
    completed = subprocess.run(
        [sys.executable, str(root / HOOK_RUNNER_SCRIPT), "hook.mc-policy-template", event],
        input=json.dumps(payload).encode(),
        capture_output=True,
        cwd=root,
        timeout=60,
        check=False,
    )
    return json.loads(completed.stdout), completed.returncode


@pytest.mark.parametrize("profile", [LaneProfile.CURSOR_LOCAL, LaneProfile.CURSOR_CLOUD])
def test_cursor_shell_deny_and_allow(profile: LaneProfile, tmp_path: Path) -> None:
    _materialize(profile, tmp_path)
    denied, code = _run(tmp_path, "before_shell", {"command": "rm -rf /", "cwd": "/w"})
    assert denied["permission"] == "deny" and code == 2
    assert "forbidden" in str(denied["agent_message"])
    allowed, code = _run(tmp_path, "before_shell", {"command": "pytest -q"})
    assert allowed == {"permission": "allow"} and code == 0


def test_the_lane_answer_module_leaves_no_bytecode_in_the_workspace(tmp_path: Path) -> None:
    _materialize(LaneProfile.CODEX, tmp_path)
    _run(tmp_path, "before_shell", {"tool_input": {"command": "pytest -q"}})
    assert not list((tmp_path / ".mission").rglob("__pycache__"))


@pytest.mark.parametrize("damage", ["missing", "corrupt", "broken"])
@pytest.mark.parametrize(
    "profile", [LaneProfile.CURSOR_LOCAL, LaneProfile.CLAUDE_AGENT_SDK, LaneProfile.CODEX]
)
def test_an_unusable_lane_answer_module_fails_closed(
    profile: LaneProfile, damage: str, tmp_path: Path
) -> None:
    """A missing, unparsable or failing `native_output.py` denies (exit 2), never a traceback."""

    _materialize(profile, tmp_path)
    native = tmp_path / ".mission" / "hooks" / "native_output.py"
    if damage == "missing":
        native.unlink()
    elif damage == "corrupt":
        native.write_text("def native_output(:" + chr(10), encoding="utf-8")
    else:
        native.write_text("def native_output(*_args):" + chr(10) + "    raise RuntimeError()")
    out, code = _run(tmp_path, "before_shell", {"command": "pytest -q", "cwd": "/w"})
    assert out == hook_runner.failed_closed("before_shell", hook_runner.FAILED_CLOSED_REASON)
    assert code == 2 and _refused_on(profile.value, out, code)


def test_claude_pre_tool_use_shape(tmp_path: Path) -> None:
    _materialize(LaneProfile.CLAUDE_AGENT_SDK, tmp_path)
    payload = {
        "session_id": "s1",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git push --force"},
    }
    out, code = _run(tmp_path, "before_shell", payload)
    specific = out["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny" and code == 0


def test_descriptor_and_runner_are_projected_for_file_lanes_only() -> None:
    cursor = HOST_PROJECTORS.render((_policy_row(),), LaneProfile.CURSOR_LOCAL, "x")
    descriptor = json.loads(cursor.file(".mission/hooks/hook.mc-policy-template/hook.json").content)
    assert descriptor["lane_profile"] == "cursor_local" and descriptor["fail_closed"] is True
    assert cursor.file(HOOK_RUNNER_SCRIPT).mode == 0o755
    deep = HOST_PROJECTORS.render((_policy_row(),), LaneProfile.DEEP_AGENTS, "x")
    assert HOOK_RUNNER_SCRIPT not in deep.paths()


def test_native_output_mapping_table() -> None:
    """Each lane package owns its answer shape (`adapters/<lane>/hook_output.py`, OC-R3)."""

    deny = {"decision": "deny", "reason": "no"}
    defer = {"decision": "defer", "reason": "ask"}
    assert cursor_output.native_output("before_tool", "cursor_local", defer)[0] == json.dumps(
        {"permission": "deny", "agent_message": "ask"}
    )
    claude, _ = claude_output.native_output("before_tool", "claude_agent_sdk", defer)
    assert json.loads(claude)["hookSpecificOutput"]["permissionDecision"] == "defer"
    codex, _ = codex_output.native_output("before_tool", "codex", defer)
    assert json.loads(codex)["hookSpecificOutput"]["permissionDecision"] == "deny"
    stop, code = claude_output.native_output("stop", "claude_agent_sdk", deny)
    assert json.loads(stop) == {"decision": "block", "reason": "no"} and code == 2
    context, _ = cursor_output.native_output(
        "after_tool", "cursor_local", {"decision": "allow", "additional_context": "note"}
    )
    assert json.loads(context) == {"additional_context": "note"}
    updated, _ = claude_output.native_output(
        "before_tool", "claude_agent_sdk", {"decision": "allow", "updated_input": {"a": 1}}
    )
    assert json.loads(updated)["hookSpecificOutput"]["updatedInput"] == {"a": 1}


def test_native_tool_normalization() -> None:
    cursor = hook_runner.build_input(
        "before_mcp",
        "cursor_local",
        {"tool_name": "pubmed_search", "tool_input": {"q": "x"}, "conversation_id": "c"},
        {"scope": {"installation_id": "i", "application_id": "biotech"}, "run_id": "r"},
    )
    assert cursor["tool"] == {"name": "pubmed_search", "input": {"q": "x"}}
    assert cursor["native_session_ref"] == "c" and cursor["run_id"] == "r"
    edit = hook_runner.build_input("after_file_edit", "cursor_local", {"file_path": "a.py"}, {})
    assert edit["tool"]["name"] == "edit_file"


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
