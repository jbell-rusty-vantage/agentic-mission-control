"""MO-73: a session resumes on a fresh worker process with no lost turns.

Every phase is its own Python process (`resume_worker.py`) driving the lane's harness with the
real pinned `ClaudeSDKClient`, `ExplicitEnvironmentCliTransport` and `StateRootSessionStore`
against the FIXTURE stream-json CLI (`fake_cli.py`); no model is called. A resuming process
knows the session only from what earlier processes persisted under the lease.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from claude_agent_sdk import project_key_for_directory
from claude_agent_sdk.types import ClaudeAgentOptions

from mission_control.adapters.claude.session import LiveSession, SessionEnded
from mission_control.adapters.claude.workspace import config_dir, state_root
from tests.unit.claude.resume_worker import (
    FAKE_CLI,
    PROMPTS,
    fake_cli_factory,
    worker_environ,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _worker(workdir: Path, *args: str) -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "tests.unit.claude.resume_worker", args[0], str(workdir), *args[1:]],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-4_000:]
    progress: dict[str, Any] = json.loads((workdir / "progress.json").read_text(encoding="utf-8"))
    return progress


def _prompts(reply: str) -> list[str]:
    """The user prompts the CLI answered from (`fake_cli.py` lists the whole session)."""

    prompts: list[str] = json.loads(reply.split("prompts: ", 1)[1])
    return prompts


def _uuids(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["uuid"] for line in lines if line]


def test_a_fresh_worker_process_resumes_the_session_with_no_lost_turns(tmp_path: Path) -> None:
    started = _worker(tmp_path, "start")
    session_id = started["session_id"]
    assert _prompts(started["replies"][0]) == list(PROMPTS[:1])

    # A fresh process on the same host: the CLI's own transcript is still in the lease.
    resumed = _worker(tmp_path, "resume")
    assert resumed["resumed_session_id"] == session_id, "resumed, not a new session"
    assert _prompts(resumed["replies"][1]) == list(PROMPTS[:2])

    # A fresh process with only the leased state root (another host): the lane writes the
    # mirrored transcript into the CLI's config dir before `--resume=<id>`.
    moved = _worker(tmp_path, "resume", "--without-cli-copy")
    lease = Path(moved["lease_path"])
    project = project_key_for_directory(str(lease))
    assert moved["cli_files_at_resume"] == [f"{project}/{session_id}.jsonl"]
    assert moved["resumed_session_id"] == session_id
    assert _prompts(moved["replies"][2]) == list(PROMPTS), "no turn was lost"
    assert moved["replies"][2].startswith(f"turn 3 of {session_id}")

    # The CLI's transcript and the mirror agree entry for entry: nothing lost or duplicated.
    root = state_root(lease)
    cli_transcript = config_dir(root) / "projects" / project / f"{session_id}.jsonl"
    mirrored = root / "sessions" / project / f"{session_id}.jsonl"
    assert len(_uuids(cli_transcript)) == 2 * len(PROMPTS)
    assert _uuids(cli_transcript) == _uuids(mirrored)


async def test_a_resume_the_cli_refuses_ends_the_session_before_init(tmp_path: Path) -> None:
    # Neither the CLI's config dir nor a store holds the session: the CLI exits during
    # startup and `connect` fails; the lane reads that as a session that never started
    # (`harness.reattach` raises `NativeTurnLost` for it), not as a crash.
    options = ClaudeAgentOptions(cwd=str(tmp_path), cli_path=str(FAKE_CLI), resume=str(uuid4()))
    session = LiveSession(
        fake_cli_factory(),
        options,
        worker_environ(tmp_path),
        harness_execution_id="mo-73-refused-resume",
        generation=1,
        init_timeout_s=30.0,
    )
    with pytest.raises(SessionEnded, match="ended before init"):
        await session.start()
    assert session.ended and session.session_id is None
