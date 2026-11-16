"""The local stack supervisor (``scripts/dev/local_stack.py``): it stops only what it started.

A recorded process is identified by its pid AND its creation time, so a pid the system reused
is never touched; a role's log tail is redacted before it is shown; and nothing starts from a
directory that holds no finished installation.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]


def _module(name: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "dev" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


installation = _module("local_installation")
script = _module("local_stack")


def _sleeper(tmp_path: Path) -> tuple[int, str]:
    process = script.spawn(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        installation.base_environment(),
        tmp_path / "logs" / "sleeper.log",
    )
    for _ in range(100):
        started = script.process_start(process.pid)
        if started is not None:
            return process.pid, started
        time.sleep(0.05)
    raise AssertionError("the sleeper did not start")


def _installation(directory: Path, **extra: object) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    state = {"application": "ai-engineer", "binding_digest": "sha256:" + "ab" * 32, **extra}
    (directory / installation.STATE).write_text(json.dumps(state), encoding="utf-8")


def test_a_live_process_has_one_stable_creation_token_and_a_missing_one_has_none() -> None:
    own = script.process_start(os.getpid())
    assert own is not None and own == script.process_start(os.getpid())
    assert script.process_start(0) is None
    assert script.process_start(2**22 + 12345) is None  # beyond any pid this host hands out


def test_only_the_recorded_process_is_stopped(tmp_path: Path) -> None:
    pid, started = _sleeper(tmp_path)
    try:
        # The same pid with another creation time is some other process: left alone.
        assert script.stop_process(pid, "another-creation-time") == "not running"
        assert script.process_start(pid) == started
        assert script.stop_process(pid, started) == "stopped"
        assert script.process_start(pid) is None
        # Stopping again is a no-op.
        assert script.stop_process(pid, started) == "not running"
    finally:
        script.stop_process(pid, started)


def test_down_stops_recorded_processes_and_ignores_a_stale_record(tmp_path: Path) -> None:
    directory = tmp_path / "ai-engineer"
    _installation(directory)
    pid, started = _sleeper(directory)
    stack = script.Stack(directory)
    try:
        stack.write_record(
            {
                "url": "http://127.0.0.1:1",
                "processes": [
                    {"role": "api", "pid": pid, "started": started, "log": "logs/sleeper.log"},
                    # A record left by an earlier boot: this pid now belongs to this test run.
                    {"role": "worker", "pid": os.getpid(), "started": "0", "log": "logs/w.log"},
                ],
            }
        )
        assert (directory / "run" / "api.pid").read_text(encoding="utf-8").strip() == str(pid)
        assert [item["role"] for item in stack.alive(stack.record())] == ["api"]
        assert stack.status()["processes"] == {
            "api": {"pid": pid, "alive": True},
            "worker": {"pid": os.getpid(), "alive": False},
        }
        result = stack.down()
        assert result["processes"] == {
            "worker": {"pid": os.getpid(), "outcome": "not running"},
            "api": {"pid": pid, "outcome": "stopped"},
        }
        assert script.process_start(pid) is None
        assert script.process_start(os.getpid()) is not None
        assert not list((directory / "run").iterdir())
        # Nothing recorded: down is a no-op that stops nothing.
        assert stack.down()["processes"] == {}
    finally:
        script.stop_process(pid, started)


def test_nothing_starts_without_a_finished_installation(tmp_path: Path) -> None:
    with pytest.raises(script.StackError, match="no finished installation"):
        script.Stack(tmp_path / "absent")
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / installation.STATE).write_text('{"application": "ai-engineer"}', encoding="utf-8")
    with pytest.raises(script.StackError, match="no finished installation"):
        script.Stack(partial)
    finished = tmp_path / "finished"
    _installation(finished)
    with pytest.raises(script.StackError, match="missing or incomplete"):
        script.Stack(finished).environment()


def test_up_refuses_a_port_in_use_and_a_running_stack(tmp_path: Path) -> None:
    import socket

    directory = tmp_path / "ai-engineer"
    _installation(directory)
    stack = script.Stack(directory)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with pytest.raises(script.StackError, match="is in use"):
            stack.up("127.0.0.1", port, "off")
    assert not stack.record_path.exists()
    pid, started = _sleeper(directory)
    try:
        stack.write_record(
            {"url": "u", "processes": [{"role": "api", "pid": pid, "started": started, "log": "l"}]}
        )
        with pytest.raises(script.StackError, match="already running"):
            stack.up("127.0.0.1", port, "off")
        assert script.process_start(pid) == started  # the running stack was not touched
    finally:
        script.stop_process(pid, started)


@pytest.mark.parametrize(
    ("recorded", "mode", "expected"),
    [
        ({"ready": True}, "auto", True),
        ({"ready": False, "missing": ["PIN_UNAVAILABLE: x"]}, "auto", False),
        ({}, "auto", False),
        ({"ready": False}, "on", True),
        ({"ready": True}, "off", False),
    ],
)
def test_auto_starts_the_worker_only_when_its_prerequisites_are_recorded(
    recorded: dict[str, object], mode: str, expected: bool
) -> None:
    assert script.worker_wanted(mode, recorded) is expected


def test_a_log_tail_never_shows_a_credential(tmp_path: Path) -> None:
    log = tmp_path / "api.log"
    token = "eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiJsb2NhbC1vcGVyYXRvciJ9.c2lnbmF0dXJlLWJ5dGVz"
    log.write_text(
        "connecting postgresql://mcl_runtime:s3cretpw@127.0.0.1:55434/mc_local_ai_engineer\n"
        f"Authorization: Bearer {token}\n"
        "OPENAI_API_KEY=sk-live-abc password: hunter2\n"
        "INFO: Application startup complete.\n",
        encoding="utf-8",
    )
    shown = script.redacted_tail(log)
    for secret in ("s3cretpw", token, "sk-live-abc", "hunter2"):
        assert secret not in shown
    assert "<dsn>" in shown and "<token>" in shown and "Application startup complete." in shown
