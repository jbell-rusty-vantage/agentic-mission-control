"""MO-03 drill: the real `codex app-server` enforces Mission Control's kernel `before_tool` deny.

Opt-in (`MC_CODEX_HOOK_DRILL=1`, `MC_CODEX_BINARY` = a codex CLI; the R21 pin 0.162.1, so the
0.162.0 schema pin is overridden explicitly). No provider is called and nothing is paid: the
model is a LOCAL mock of the Responses API (`model_providers.mc_mock` in the isolated
`CODEX_HOME`) that asks for one `exec_command` per turn. Everything else is production code:
the codex harness over a git worktree lease, `SubprocessAppServerLauncher`, the projected
`.codex/hooks.json` with the hash trust the lane records (checked through `hooks/list`),
`.mission/hooks/kernel.py` with its context and task token, and the hook callback app on a
loopback listener. Codex itself runs the kernel hooks.

Turn 1: the shell call is allowed and its Operation Intent recorded. Then a Stop Fence is
persisted; turn 2: Codex blocks the shell call with the kernel's reason ("Command blocked by
PreToolUse hook: run is stop-fenced ..."). A live-model drill remains the owner's S0 item.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.codex.harness import CodexLocalHarness
from mission_control.adapters.codex.launcher import (
    LaunchedAppServer,
    LaunchSpec,
    SubprocessAppServerLauncher,
)
from mission_control.adapters.cursor.workspace import GitWorktreeLeaser
from mission_control.application.agentic_components.materialization import projection_digest
from mission_control.application.execution.auth_admission import AuthAdmission
from mission_control.application.execution.child_environment import provider_child_environment
from mission_control.application.execution.harness.leases import InMemoryWorkspaceLeaseStore
from mission_control.domain.execution.lanes import LaneFrame
from mission_control.domain.policies.stop_fence import StopFence
from tests.fixtures.lane_turns import lane_stack
from tests.unit.codex.drive import observed, sent, started
from tests.unit.codex.support import (
    CodexStack,
    MemoryArtifacts,
    StaticAuth,
    StaticProjectionSource,
    codex_binding,
    codex_operation,
    fixture_settings,
)
from tests.unit.codex.test_kernel_hooks import HookRig, hook_rig, kernel_projection  # noqa: F401
from tests.unit.workspaces.workspace_fixtures import commit, git

pytestmark = pytest.mark.skipif(
    os.environ.get("MC_CODEX_HOOK_DRILL") != "1",
    reason="opt-in: set MC_CODEX_HOOK_DRILL=1 and MC_CODEX_BINARY (a local codex CLI)",
)
SHELL_COMMAND = "echo mission-control-drill"
_USAGE = {
    "input_tokens": 1,
    "output_tokens": 1,
    "total_tokens": 2,
    "input_tokens_details": {"cached_tokens": 0},
    "output_tokens_details": {"reasoning_tokens": 0},
}


class MockResponses(BaseHTTPRequestHandler):
    """LOCAL mock of `POST /v1/responses` (SSE): a function call to `exec_command`, then,
    once the call's output is in the input, a final message. Records every tool output."""

    outputs: list[str]
    calls: int

    def log_message(self, *args: Any) -> None:
        del args

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        items = body.get("input") or []
        last = items[-1] if items else {}
        server = type(self)
        if last.get("type") == "function_call_output":
            server.outputs.append(str(last.get("output")))
            item: dict[str, Any] = {
                "type": "message",
                "id": f"msg_{len(server.outputs)}",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "done", "annotations": []}],
            }
        else:
            server.calls += 1
            item = {
                "type": "function_call",
                "id": f"fc_{server.calls}",
                "call_id": f"call_drill_{server.calls}",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": SHELL_COMMAND}),
            }
        events = [
            {"type": "response.created", "response": {"id": "resp"}},
            {"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": "resp", "usage": _USAGE}},
        ]
        data = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def mock_model() -> Iterator[tuple[str, type[MockResponses]]]:
    handler = type("Mock", (MockResponses,), {"outputs": [], "calls": 0})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1", handler
    finally:
        server.shutdown()


def _repository(root: Path) -> Path:
    root.mkdir(parents=True)
    git("init", "--quiet", "--initial-branch=main", cwd=root)
    (root / "README.md").write_text("# drill target\n", encoding="utf-8")
    git("add", "--all", cwd=root)
    commit(root, "base")
    return root


def drill_environment(
    environ: Mapping[str, str],
    admission: AuthAdmission | None,
    *,
    declared: Iterable[str] = (),
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The MO-04 allowlist, plus `PATHEXT` on a Windows host: without it Codex's PowerShell
    hook shell cannot resolve `python` and every hook fails (production codex workers are
    Linux/WSL, where the allowlist suffices)."""

    env = provider_child_environment(environ, admission, declared=declared, extra=extra)
    if sys.platform == "win32" and "PATHEXT" in environ:
        env["PATHEXT"] = environ["PATHEXT"]
    return env


class MockModelLauncher(SubprocessAppServerLauncher):
    """The production launcher, with the isolated home pointed at the local mock model (the
    provider's top-level key precedes the trust tables the lane wrote)."""

    def __init__(self, binary: str, base_url: str) -> None:
        super().__init__(binary, allow_version_mismatch=True)
        self._provider = (
            'model_provider = "mc_mock"\n'
            f'[model_providers.mc_mock]\nname = "mc_mock"\nbase_url = "{base_url}"\n'
            'wire_api = "responses"\nrequires_openai_auth = false\n\n'
        )

    async def launch(self, spec: LaunchSpec) -> LaunchedAppServer:
        config = spec.codex_home / "config.toml"
        text = config.read_text(encoding="utf-8")
        if not text.startswith(self._provider):
            config.write_text(self._provider + text, encoding="utf-8")
        return await super().launch(spec)


def hook_statuses(frames: list[LaneFrame]) -> set[str]:
    """How Codex reports the kernel hook runs of one turn (`hook/completed`)."""

    return {
        str(frame.body["run"]["status"]) for frame in frames if frame.raw_kind == "hook/completed"
    }


async def test_real_codex_enforces_the_kernel_before_tool_deny(
    tmp_path: Path,
    hook_rig: HookRig,  # noqa: F811
    mock_model: tuple[str, type[MockResponses]],
) -> None:
    base_url, model = mock_model
    projection = kernel_projection()
    repository = _repository(tmp_path / "repo")
    operation = codex_operation(
        codex_binding(
            materialization_digest=projection_digest(projection),
            repo_url=str(repository),
            repo_ref="main",
            provider_options={
                "provider": "codex_app_server",
                "approval_policy": "never",
                "sandbox_mode": "danger-full-access",
                "app_server_schema_version": "v2@0.162.0",
            },
        )
    )
    artifacts = MemoryArtifacts()
    harness = CodexLocalHarness(
        launcher=MockModelLauncher(os.environ.get("MC_CODEX_BINARY", "codex"), base_url),
        leaser=GitWorktreeLeaser(
            InMemoryWorkspaceLeaseStore(), lease_root=tmp_path / "leases", artifacts=artifacts
        ),
        projections=StaticProjectionSource(projection),
        artifacts=artifacts,
        auth=StaticAuth(),
        settings=fixture_settings(
            tmp_path, worker_environ=os.environ, hook_callback_base_url=hook_rig.url
        ),
        child_environment=drill_environment,
        hooks=hook_rig.service,
    )
    # The drill drives the real app-server: there is no FIXTURE launcher or leaser.
    stack = CodexStack(
        harness=harness,
        launcher=None,  # type: ignore[arg-type]
        leaser=None,  # type: ignore[arg-type]
        artifacts=artifacts,
        auth=StaticAuth(),
        rig=None,
        operation=operation,
        lanes=lane_stack(harness, operation=operation),
    )
    session = await started(stack)
    assert int(session.native_details["hooks_trusted"]) > 0

    turn = await sent(stack, session, key="turn:1", turn_no=1)
    assert hook_statuses(await observed(stack, turn)) == {"completed"}
    assert len(model.outputs) == 1 and "mission-control-drill" in model.outputs[0]
    (intent,) = hook_rig.intents.intents()
    assert intent.effect_ref == "tool_use:call_drill_1" and intent.lane_profile == "codex"

    identity = stack.identity
    await hook_rig.fences.persist(
        StopFence(
            request_scope=identity.request_scope,
            run_id=identity.run_key,
            generation=1,
            command_id="cancel-mo-03-drill",
            reason="operator stop",
            requested_at=datetime.now(UTC),
        )
    )
    turn = await sent(stack, session, key="turn:2", turn_no=2)
    assert "blocked" in hook_statuses(await observed(stack, turn))
    assert len(model.outputs) == 2
    blocked = model.outputs[1]
    assert blocked.startswith("Command blocked by PreToolUse hook:")
    assert "run is stop-fenced by immediate cancel cancel-mo-03-drill" in blocked
    assert "mission-control-drill\n" not in blocked
    assert [intent.effect_ref for intent in hook_rig.intents.intents()] == ["tool_use:call_drill_1"]
