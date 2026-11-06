"""MO-41: the Telemetry Hook Pack script (`.mission/hooks/signal`) as a provider runs it.

Each case places the rendered `cursor_cloud` (or `codex`) projection in a temporary workspace
and runs the projected hook commands as subprocesses with a native payload on stdin, against
a stdlib HTTP listener on 127.0.0.1 that stands in for the Signal Ingress route and records
every batch. The real ingress is exercised in
tests/integration/postgres/test_telemetry_pack_ingress_postgres.py.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from mission_control.application.agentic_components import signal_hook
from mission_control.application.agentic_components.telemetry import (
    SIGNAL_CLI,
    SIGNAL_HOOK_TIMEOUT_SECONDS,
    SIGNAL_SCRIPT,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.capabilities.host_support import LaneProfile
from tests.fixtures.projections.rows import INSTRUCTION, fixture_rows

TOKEN = "mct_" + "s" * 43
STATE = Path(".mission/state/signals")


def test_signal_bearer_never_follows_a_redirect(ingress: Ingress) -> None:
    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(307)
            self.send_header("Location", ingress.url)
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status = signal_hook.post(
            f"http://127.0.0.1:{server.server_address[1]}/redirect", TOKEN, []
        )
        assert status == 307
        assert ingress.headers == [], "the redirect destination received no bearer"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_signal_bearer_refuses_remote_cleartext_transport() -> None:
    assert signal_hook.post("http://public.example/signals", TOKEN, []) == 0


@dataclass
class Ingress:
    """Records each POSTed batch; answers `statuses` in turn, then 202, or 422 to any batch
    holding a signal whose type is in `refuse` (one invalid item refuses its whole batch)."""

    statuses: list[int] = field(default_factory=list)
    refuse: set[str] = field(default_factory=set)
    batches: list[list[dict[str, Any]]] = field(default_factory=list)
    headers: list[dict[str, str]] = field(default_factory=list)
    url: str = ""

    @property
    def signals(self) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for batch in self.batches:
            for signal in batch:
                seen.setdefault(signal["signal_id"], signal)
        return list(seen.values())


@pytest.fixture
def ingress() -> Iterator[Ingress]:
    recorder = Ingress()
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            with lock:
                status = recorder.statuses.pop(0) if recorder.statuses else 202
                if any(signal["type"] in recorder.refuse for signal in body["signals"]):
                    status = 422
                recorder.headers.append(dict(self.headers))
                if status == 202:
                    recorder.batches.append(body["signals"])
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"accepted": 0, "duplicates": 0}')

        def log_message(self, *args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    recorder.url = f"http://127.0.0.1:{server.server_address[1]}/v1/ingress/biotech/signals"
    try:
        yield recorder
    finally:
        server.shutdown()
        server.server_close()


def workspace(root: Path, lane: LaneProfile = LaneProfile.CURSOR_CLOUD) -> Path:
    projection = HOST_PROJECTORS.render(fixture_rows(), lane, INSTRUCTION, None, ())
    for item in projection.files:
        target = root / item.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.content)
    return root


def env(ingress: Ingress | None, **extra: str) -> dict[str, str]:
    base = {
        key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TEMP", "TMP") if key in os.environ
    }
    if ingress is not None:
        base.update(MC_SIGNAL_URL=ingress.url, MC_SIGNAL_TOKEN=TOKEN)
    return {**base, **extra}


def hook(
    root: Path, key: str, payload: dict[str, Any], environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, SIGNAL_SCRIPT, "hook", key],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=root,
        env=environment,
        timeout=60,
        check=False,
    )


def spooled(root: Path) -> list[dict[str, Any]]:
    lines = (root / STATE / "spool.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def state(root: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((root / STATE / "state.json").read_text("utf-8"))
    return loaded


PRE_TOOL = {
    "hook_event_name": "preToolUse",
    "conversation_id": "conv-1",
    "generation_id": "gen-1",
    "cursor_version": "3.5.0",
    "tool_name": "Shell",
    "tool_use_id": "call-1",
    "tool_input": {"command": "cat ~/.ssh/id_rsa"},
}


def test_the_first_hook_opens_the_session_and_reports_what_is_on_disk(
    tmp_path: Path, ingress: Ingress
) -> None:
    root = workspace(tmp_path)
    (root / ".mission/run.json").write_text('{"run_nonce": "nonce-1"}', encoding="utf-8")

    done = hook(root, "before_tool", PRE_TOOL, env(ingress))

    assert (done.returncode, json.loads(done.stdout)) == (0, {"permission": "allow"})
    (batch,) = ingress.batches
    assert [(item["type"], item["seq"]) for item in batch] == [
        ("session.started", 1),
        ("materialization.observed", 2),
        ("tool.started", 3),
    ]
    started, observed, tool = batch
    assert started["data"] == {
        "lane_profile": "cursor_cloud",
        "hook": "before_tool",
        "hook_event_name": "preToolUse",
        "conversation_id": "conv-1",
        "cursor_version": "3.5.0",
        "run_nonce": "nonce-1",
    }
    files = observed["data"]["files"]
    assert set(files) == {".cursor/hooks.json", ".cursor/rules/mc-mission.mdc"}
    for path, digest in files.items():
        assert digest == "sha256:" + hashlib.sha256((root / path).read_bytes()).hexdigest()
    assert observed["data"]["skills"] == ["agent-browser", "mc-signals"]
    # Only the allowlisted scalar fields travel; tool input never does.
    assert tool["data"]["tool_name"] == "Shell" and "tool_input" not in tool["data"]
    assert "id_rsa" not in json.dumps(ingress.batches)
    spool_id = state(root)["spool_id"]
    assert [item["signal_id"] for item in batch] == [f"{spool_id}-{n}" for n in (1, 2, 3)]
    assert ingress.headers[0]["Authorization"] == f"Bearer {TOKEN}"
    assert state(root)["sent"] == 3
    # The spool ignores itself, so an agent's `git add -A` never commits it.
    assert (root / STATE / ".gitignore").read_text(encoding="utf-8") == "*\n"


def test_hooks_batch_until_stop_flushes_in_order_without_gaps(
    tmp_path: Path, ingress: Ingress
) -> None:
    root = workspace(tmp_path)
    environment = env(ingress)
    hook(root, "before_tool", PRE_TOOL, environment)
    for key in ("after_tool", "subagent_start", "subagent_stop", "after_model"):
        done = hook(root, key, {"hook_event_name": key, "conversation_id": "conv-1"}, environment)
        assert done.returncode == 0
    assert len(ingress.batches) == 1, "observe-only hooks wait for a batch or a flush"

    hook(root, "stop", {"hook_event_name": "stop", "status": "completed"}, environment)

    types = [signal["type"] for signal in ingress.signals]
    assert types == [
        "session.started",
        "materialization.observed",
        "tool.started",
        "tool.completed",
        "subagent.started",
        "subagent.stopped",
        "agent.responded",
        "stop",
    ]
    assert [signal["seq"] for signal in ingress.signals] == list(range(1, 9))
    assert state(root)["sent"] == 8 and spooled(root)[-1]["data"]["status"] == "completed"


def test_a_hook_the_policy_does_not_name_records_nothing(tmp_path: Path, ingress: Ingress) -> None:
    root = workspace(tmp_path)
    done = hook(root, "before_shell", {"command": "ls"}, env(ingress))
    assert (done.returncode, done.stdout) == (0, "")
    assert not (root / STATE / "spool.jsonl").exists() and not ingress.batches


def test_an_unreachable_ingress_never_blocks_and_the_stop_flush_delivers_later(
    tmp_path: Path, ingress: Ingress
) -> None:
    root = workspace(tmp_path)
    down = env(None, MC_SIGNAL_URL="http://127.0.0.1:9/v1/ingress/biotech/signals")
    down["MC_SIGNAL_TOKEN"] = TOKEN
    started = time.monotonic()
    done = hook(root, "before_tool", PRE_TOOL, down)
    assert done.returncode == 0 and json.loads(done.stdout) == {"permission": "allow"}
    assert time.monotonic() - started < 15
    failed = state(root)
    assert failed["sent"] == 0 and failed["failures"] == 1 and failed["retry_at"] > time.time()
    # Inside the backoff window an observe-only hook does not try again.
    hook(root, "after_tool", {"hook_event_name": "postToolUse"}, env(ingress))
    assert not ingress.batches

    hook(root, "stop", {"hook_event_name": "stop"}, env(ingress))

    assert [signal["seq"] for signal in ingress.signals] == [1, 2, 3, 4, 5]
    assert state(root)["failures"] == 0 and state(root)["sent"] == 5


def test_a_flush_retries_transient_failures_with_backoff(tmp_path: Path, ingress: Ingress) -> None:
    root = workspace(tmp_path)
    ingress.statuses = [503, 429]
    done = hook(root, "stop", {"hook_event_name": "stop"}, env(ingress))
    assert done.returncode == 0
    assert len(ingress.headers) == 3, "two transient refusals, then the batch lands"
    assert [signal["type"] for signal in ingress.signals] == [
        "session.started",
        "materialization.observed",
        "stop",
    ]


def test_a_refused_signal_is_isolated_and_only_it_is_skipped(
    tmp_path: Path, ingress: Ingress
) -> None:
    root = workspace(tmp_path)
    hook(root, "before_tool", PRE_TOOL, env(None))
    emit(root, "bad", "an item the ingress refuses", environment=env(None))
    for n in range(3):
        hook(root, "after_tool", {"tool_use_id": f"c-{n}"}, env(None))
    ingress.refuse = {"bad"}

    hook(root, "stop", {"hook_event_name": "stop"}, env(ingress))

    assert [signal["seq"] for signal in ingress.signals] == [1, 2, 3, 5, 6, 7, 8]
    refused = state(root)
    assert refused["sent"] == 8 and refused["rejected"] == 1 and refused["last_error"] == 422
    assert refused["failures"] == 0


def test_an_unauthorized_ingress_keeps_the_spool_for_a_later_call(
    tmp_path: Path, ingress: Ingress
) -> None:
    root = workspace(tmp_path)
    ingress.statuses = [401]
    hook(root, "stop", {"hook_event_name": "stop"}, env(ingress))
    refused = state(root)
    assert len(ingress.headers) == 1, "a refused credential is not retried at once"
    assert refused["sent"] == 0 and refused["failures"] == 1 and refused["last_error"] == 401

    hook(root, "stop", {"hook_event_name": "stop"}, env(ingress))

    assert [signal["seq"] for signal in ingress.signals] == [1, 2, 3, 4]
    assert state(root)["sent"] == 4 and "rejected" not in state(root)


def test_a_payload_that_breaks_the_parser_still_answers_and_records(
    tmp_path: Path, ingress: Ingress
) -> None:
    root = workspace(tmp_path)
    depth = 200_000
    raw = '{"tool_input": ' + "[" * depth + "]" * depth + "}"
    done = subprocess.run(
        [sys.executable, SIGNAL_SCRIPT, "hook", "before_tool"],
        input=raw,
        capture_output=True,
        text=True,
        cwd=root,
        env=env(ingress),
        timeout=60,
        check=False,
    )
    assert (done.returncode, json.loads(done.stdout)) == (0, {"permission": "allow"})
    assert [signal["type"] for signal in ingress.signals][-1] == "tool.started"


def test_a_busy_spool_lock_drops_the_signal_within_the_hook_timeout(
    tmp_path: Path, ingress: Ingress
) -> None:
    root = workspace(tmp_path)
    hook(root, "before_tool", PRE_TOOL, env(ingress))
    with (root / STATE / "spool.lock").open("a+b") as held:
        assert signal_hook._try_lock(held)
        started = time.monotonic()
        try:
            done = hook(root, "before_tool", PRE_TOOL, env(ingress))
        finally:
            signal_hook._unlock(held)
    waited = time.monotonic() - started
    assert (done.returncode, json.loads(done.stdout)) == (0, {"permission": "allow"})
    assert "TimeoutError" in done.stderr
    assert signal_hook.LOCK_WAIT_SECONDS <= waited < SIGNAL_HOOK_TIMEOUT_SECONDS
    assert [record["seq"] for record in spooled(root)] == [1, 2, 3], "never taken from a holder"

    hook(root, "stop", {"hook_event_name": "stop"}, env(ingress))
    assert [signal["seq"] for signal in ingress.signals] == [1, 2, 3, 4]


def test_a_writer_killed_mid_append_leaves_a_gap_never_a_repeat(
    tmp_path: Path, ingress: Ingress
) -> None:
    root = workspace(tmp_path)
    hook(root, "before_tool", PRE_TOOL, env(None))
    # What a writer killed after reserving seq 4 and writing half its line leaves behind.
    reserved = {**state(root), "seq": 4}
    (root / STATE / "state.json").write_text(json.dumps(reserved), encoding="utf-8")
    with (root / STATE / "spool.jsonl").open("ab") as handle:
        handle.write(b'{"seq": 4, "type": "tool.comp')

    hook(root, "stop", {"hook_event_name": "stop"}, env(ingress))

    assert [signal["seq"] for signal in ingress.signals] == [1, 2, 3, 5]
    assert state(root)["sent"] == 5


def test_the_lock_wait_and_upload_budget_fit_in_the_native_hook_timeout() -> None:
    worst = signal_hook.LOCK_WAIT_SECONDS + signal_hook.UPLOAD_SECONDS + signal_hook.TIMEOUT_SECONDS
    assert worst < SIGNAL_HOOK_TIMEOUT_SECONDS


# Standard-library names the script imports, each present since Python 3.8 (checked against
# the 3.8 library reference). A new import is checked the same way and added here.
PY38_FROM_IMPORTS = {
    "__future__": {"annotations"},
    "collections.abc": {"Iterator"},
    "contextlib": {"contextmanager", "suppress"},
    "datetime": {"datetime", "timezone"},
    "pathlib": {"Path"},
    "typing": {"IO", "Any"},
}
PY38_MODULES = {
    "fcntl",
    "hashlib",
    # The lane's native gate answer is loaded from beside the script (OC-R3).
    "importlib.util",
    "json",
    "msvcrt",
    "os",
    "re",
    "sys",
    "time",
    "urllib.error",
    "urllib.parse",
    "urllib.request",
    "uuid",
}


def test_the_script_runs_on_python_3_8_and_newer() -> None:
    """The workspace's interpreter may be older than Mission Control's (Ubuntu 22.04 ships
    3.10): the grammar and every import must exist in Python 3.8."""

    source = signal_hook.__file__
    tree = ast.parse(Path(source).read_text(encoding="utf-8"), feature_version=(3, 8))
    modules: set[str] = set()
    names: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            names.setdefault(node.module, set()).update(alias.name for alias in node.names)
    assert modules <= PY38_MODULES, modules - PY38_MODULES
    for module, imported in names.items():
        assert imported <= PY38_FROM_IMPORTS.get(module, set()), (module, imported)


OLDER_PYTHONS = [
    found
    for found in (shutil.which(f"python3.{minor}") for minor in (8, 9, 10))
    if found is not None
]


@pytest.mark.skipif(not OLDER_PYTHONS, reason="no Python 3.8-3.10 on PATH")
@pytest.mark.parametrize("python", OLDER_PYTHONS)
def test_an_older_interpreter_runs_the_hook(python: str, tmp_path: Path, ingress: Ingress) -> None:
    root = workspace(tmp_path)
    done = subprocess.run(
        [python, SIGNAL_SCRIPT, "hook", "before_tool"],
        input=json.dumps(PRE_TOOL),
        capture_output=True,
        text=True,
        cwd=root,
        env=env(ingress),
        timeout=60,
        check=False,
    )
    assert (done.returncode, json.loads(done.stdout)) == (0, {"permission": "allow"}), done.stderr
    assert [signal["seq"] for signal in ingress.signals] == [1, 2, 3]


def test_without_a_credential_signals_stay_spooled_until_one_is_present(
    tmp_path: Path, ingress: Ingress
) -> None:
    root = workspace(tmp_path)
    hook(root, "before_tool", PRE_TOOL, env(None))
    hook(root, "stop", {"hook_event_name": "stop"}, env(None))
    assert [record["seq"] for record in spooled(root)] == [1, 2, 3, 4]
    assert state(root)["sent"] == 0

    flushed = subprocess.run(
        [sys.executable, SIGNAL_SCRIPT, "flush"], cwd=root, env=env(ingress), check=False
    )

    assert flushed.returncode == 0
    assert [signal["seq"] for signal in ingress.signals] == [1, 2, 3, 4]


def test_concurrent_hooks_take_distinct_contiguous_sequence_numbers(
    tmp_path: Path, ingress: Ingress
) -> None:
    root = workspace(tmp_path)
    environment = env(ingress)
    payloads = [{"hook_event_name": "postToolUse", "tool_use_id": f"c-{n}"} for n in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda p: hook(root, "after_tool", p, environment), payloads))
    assert all(result.returncode == 0 for result in results)
    hook(root, "stop", {"hook_event_name": "stop"}, environment)
    records = spooled(root)
    assert [record["seq"] for record in records] == list(range(1, 12))
    assert len({record["signal_id"] for record in records}) == 11
    assert [signal["seq"] for signal in ingress.signals] == list(range(1, 12))


def emit(root: Path, *args: str, environment: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, SIGNAL_SCRIPT, "emit", *args],
        capture_output=True,
        text=True,
        cwd=root,
        env=environment,
        timeout=60,
        check=False,
    )


def test_mc_signal_emits_at_once_and_refuses_malformed_input(
    tmp_path: Path, ingress: Ingress
) -> None:
    root = workspace(tmp_path, LaneProfile.CODEX)
    done = emit(
        root, "milestone", "tests green", "--data", '{"passed": 412}', environment=env(ingress)
    )
    assert done.returncode == 0, done.stderr
    receipt = json.loads(done.stdout)
    assert receipt["seq"] == 3 and receipt["delivered"] is True
    started, _observed, milestone = ingress.signals
    assert started["data"] == {"lane_profile": "codex", "source": "cli"}
    assert milestone["type"] == "milestone"
    assert milestone["data"] == {"passed": 412, "message": "tests green", "source": "cli"}
    for args in (("Bad Type",), ("blocked", "--data", "[1]"), ("blocked", "--data"), ()):
        refused = emit(root, *args, environment=env(ingress))
        assert refused.returncode == 2 and refused.stderr
    assert len(spooled(root)) == 3


@pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")
def test_the_mc_signal_command_hands_off_to_the_script(tmp_path: Path, ingress: Ingress) -> None:
    root = workspace(tmp_path, LaneProfile.CODEX)
    sh = shutil.which("sh")
    assert sh is not None
    environment = env(ingress)
    environment["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), environment["PATH"]])
    done = subprocess.run(
        [sh, SIGNAL_CLI, "blocked", "need staging DB creds"],
        capture_output=True,
        text=True,
        cwd=root,
        env=environment,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["delivered"] is True
    assert ingress.signals[-1]["data"]["message"] == "need staging DB creds"
