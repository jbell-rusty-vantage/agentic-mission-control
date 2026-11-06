"""Proof orchestration must not turn failure, timeout or missing targets into a pass."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "foundation_proof", Path(__file__).resolve().parents[2] / "scripts/report_source_proof.py"
)
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)


@pytest.mark.parametrize(("failure", "expected"), [(7, 7), ("timeout", 124), ("missing", 127)])
def test_failure_preserves_exit_and_marks_remaining_unrun(tmp_path, monkeypatch, failure, expected):
    monkeypatch.setenv("LOCAL_FIXTURE_DSN", "postgresql://fixture@127.0.0.1:55433/postgres")
    monkeypatch.setenv("UNRELATED_API_KEY", "must-not-reach-child")
    monkeypatch.setattr(proof.shutil, "which", lambda _: "corepack")
    monkeypatch.setattr(
        proof.subprocess,
        "check_output",
        lambda command, **_: "head\n" if "rev-parse" in command else "",
    )
    calls = []

    def child(command, **kwargs):
        calls.append(command)
        assert "UNRELATED_API_KEY" not in kwargs["env"]
        assert kwargs["env"]["LANGSMITH_TRACING"] == "false"
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, 1)
        if failure == "missing":
            raise FileNotFoundError
        return SimpleNamespace(returncode=failure)

    monkeypatch.setattr(proof.subprocess, "run", child)
    out = tmp_path / "proof"
    assert proof.run(out, "LOCAL_FIXTURE_DSN", timeout=1) == 1
    matrix = json.loads((out / "matrix.json").read_text())
    assert len(calls) == 1
    assert matrix["steps"][0]["exit_code"] == expected
    assert all(step["status"] == "unrun" for step in matrix["steps"][1:])
    assert matrix["qualified"] is False


@pytest.mark.parametrize("dsn", ["", "postgresql://fixture@example.com/db"])
def test_unknown_or_remote_target_is_refused_before_output(tmp_path, monkeypatch, dsn):
    monkeypatch.setenv("LOCAL_FIXTURE_DSN", dsn)
    out = tmp_path / "proof"
    with pytest.raises(ValueError, match="loopback"):
        proof.run(out, "LOCAL_FIXTURE_DSN")
    assert not out.exists()
