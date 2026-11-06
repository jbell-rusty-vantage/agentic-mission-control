import asyncio
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import agentjob  # noqa: E402
from adapters.common import Frames  # noqa: E402


def job(tmp_path, **changes):
    path = tmp_path / "job.yaml"
    path.write_text(json.dumps({"id": "test-job", "cli": "codex", "goal": "Complete task", **changes}))
    return agentjob.load_job(path)


@pytest.mark.parametrize("changes", [{"unknown_option": True}, {"id": "../escape"}, {"budget": {"max_iterations": 0}}, {"model": {"bogus": "x"}}])
def test_closed_schema(tmp_path, changes):
    with pytest.raises(jsonschema.ValidationError):
        job(tmp_path, **changes)


@pytest.mark.parametrize("changes", [{"host": "wsl"}, {"cli": "cursor", "model": {"effort": "high"}}, {"budget": {"max_usd": 1}}, {"permissions": "edit", "worktree": {"mode": "none"}}])
def test_unsupported_before_spawn(tmp_path, monkeypatch, changes):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("spawned"))
    with pytest.raises(ValueError):
        job(tmp_path, **changes)


@pytest.mark.parametrize("cli", ["claude", "codex", "cursor"])
@pytest.mark.parametrize("profile", ["read-only", "edit", "full"])
@pytest.mark.parametrize("windows", [True, False])
def test_argv_profile_resume_default(tmp_path, cli, profile, windows):
    value = job(tmp_path, cli=cli, permissions=profile)
    value["schema_path"] = "report.json"
    adapter = importlib.import_module("adapters." + cli)
    initial = adapter.build_argv(value, windows=windows)
    resumed = adapter.build_argv(value, "abc", windows)
    assert "--model" not in initial
    assert "--printenv" not in initial
    assert "abc" in resumed
    if cli == "codex":
        assert resumed[-3:] == ["resume", "abc", "-"]
        assert "--ignore-user-config" in initial
        assert '-a' not in initial
        for argv in (initial, resumed):
            assert ("features.prefer_mxc=true" in argv) == windows
            assert ('windows.sandbox="elevated"' in argv) == windows
            assert ("--dangerously-bypass-approvals-and-sandbox" in argv) == (profile == "full")
            if profile != "full":
                assert argv[argv.index("-s") + 1] == {"read-only": "read-only", "edit": "workspace-write"}[profile]
    elif cli == "cursor":
        assert ("--force" in initial) == (profile != "read-only")
    else:
        assert "--permission-mode" in initial
        assert "--bare" not in initial


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_explicit_config_survives_resume(tmp_path, cli):
    value = job(tmp_path, cli=cli, model={"name": "owner-model", "effort": "high"})
    value["schema_path"] = "schema.json"
    adapter = importlib.import_module("adapters." + cli)
    for session in (None, "known-session"):
        argv = adapter.build_argv(value, session)
        assert "owner-model" in argv
        assert any("high" in part for part in argv)


def test_env_scrub_and_redaction(tmp_path):
    source = {"PATH": "bin", "OPENAI_API_KEY": "sentinel-secret", "ANTHROPIC_API_KEY": "sentinel-other", "CURSOR_API_KEY": "cursor-secret", "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "DATABASE_URL": "private", "APPDATA": "app"}
    env = agentjob.child_env(job(tmp_path), source)
    assert env == {"PATH": "bin", "APPDATA": "app"}
    assert "sentinel-secret" not in agentjob.redact(json.dumps(source), source)
    assert "sk-abc123" not in agentjob.redact("sk-abc123 bearer xyz123")


def test_windows_bootstrap_keeps_only_existing_platform_directories(tmp_path):
    directories = {
        "SystemDrive": "C:", "ProgramFiles": "programs", "ProgramFiles(x86)": "programs-x86",
        "ProgramW6432": "programs-64", "CommonProgramFiles": "common",
        "CommonProgramFiles(x86)": "common-x86",
    }
    source = directories | {
        "OPENAI_API_KEY": "unselected-key", "DATABASE_URL": "private-database",
        "UNRELATED_DIRECTORY": "private-location", "CLAUDE_CODE_OAUTH_TOKEN": "other-provider-token",
    }
    assert agentjob.child_env(job(tmp_path), source) == directories
    assert agentjob.child_env(job(tmp_path), {}) == {}


def test_auth_guard_scrubs_before_probe(tmp_path, monkeypatch):
    value = job(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sentinel-secret")
    monkeypatch.setattr(agentjob, "resolve_binary", lambda cli: ["fake"])
    calls = []
    def probe(argv, env, cwd):
        assert "OPENAI_API_KEY" not in env
        calls.append(argv)
        if "--help" in argv:
            return "--ignore-user-config --output-schema --json"
        if "status" in argv:
            return "Logged in using API key"
        return "codex 0.162.1"
    monkeypatch.setattr(agentjob, "probe", probe)
    with pytest.raises(ValueError, match="ChatGPT"):
        agentjob.preflight(value, tmp_path)
    assert len(calls) == 3


@pytest.mark.parametrize("fixture", sorted((ROOT / "tests/fixtures").rglob("*.jsonl")))
def test_fixture_shapes(fixture):
    frames = Frames(fixture.parent.name)
    for line in fixture.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if "__fake__" not in event:
            frames.parse_event(event)
    if fixture.name in {"success.jsonl", "success-structured.jsonl"}:
        assert frames.report["status"] == "done"
        assert frames.terminal
    if fixture.name == "max-turns.jsonl":
        assert frames.failure == "error_max_turns"


def prepared(cli="codex"):
    return {"cli": cli, "version": "SYNTHETIC", "binary": [sys.executable], "host": "native", "requested_model": None, "requested_effort": None, "observed_model": None, "model_selection": "native_default", "auth": "subscription", "permissions": "read-only", "configuration_sources": ["synthetic test"]}


@pytest.mark.parametrize("fixture,expected", [("success-structured.jsonl", "done"), ("sandbox-denied.jsonl", "blocked"), ("turn-failed-quota.jsonl", "failed")])
def test_fake_runner_worktree(tmp_path, monkeypatch, fixture, expected):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
    command = ('& ' if os.name == 'nt' else '') + f'"{sys.executable}" -c "assert True"'
    value = job(tmp_path, repo=str(repo), verify=[command])
    fixture_path = ROOT / "tests/fixtures/codex" / fixture
    monkeypatch.setattr(agentjob.codex, "build_argv", lambda *a: [str(ROOT / "tests/fake_cli.py"), str(fixture_path)])
    result = asyncio.run(agentjob.run_job(value, live=True, prepared=([sys.executable], agentjob.child_env(value), prepared())))
    assert result["status"] == expected
    assert result["usage"]["cost_usd"] is None
    assert not result["worktree_retained"]
    assert (repo / ".tmp/agent-jobs/test-job/result.json").exists()


def test_default_off(tmp_path):
    with pytest.raises(ValueError, match="default-off"):
        asyncio.run(agentjob.run_job(job(tmp_path)))


@pytest.mark.parametrize("cancel", [True, False])
def test_fake_timeout_cancel(tmp_path, cancel):
    marker = tmp_path / "cancel"
    if cancel:
        marker.touch()
    argv = [sys.executable, str(ROOT / "tests/fake_cli.py"), str(ROOT / "tests/fixtures/common/hang.jsonl")]
    code, reason = asyncio.run(agentjob.execute(argv, "", tmp_path, dict(os.environ), time.monotonic() + .2, marker, io.StringIO(), Frames("cursor")))
    assert reason == ("cancelled" if cancel else "timeout")
    assert code != 0


def test_wsl_explicit_config_env_and_custody(tmp_path, monkeypatch):
    configuration = {"distro": "Ubuntu-fixture", "repo": "/home/test/repo", "worktree_root": "/home/test/jobs", "home": "/home/test", "path": "/usr/bin:/bin", "binary": "/home/test/bin/codex"}
    value = job(tmp_path, host="wsl", wsl=configuration)
    host = agentjob.WslHost(configuration, "codex")
    calls = []
    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert "WSLENV" not in kwargs["env"]
        assert "OPENAI_API_KEY" not in kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    host.write("/home/test/jobs/schema.json", "{}")
    argv, cancel, cleanup = host.launch([configuration["binary"], "exec", "-"], "/home/test/jobs/a")
    assert argv[:5] == ["wsl.exe", "-d", "Ubuntu-fixture", "-e", "env"]
    assert "-i" in argv and "setsid" in argv
    assert "HOME=/home/test" in argv
    assert "PATH=/usr/bin:/bin" in argv
    assert argv[-3:] == [configuration["binary"], "exec", "-"]
    cancel()
    cleanup()
    assert any("kill -KILL" in part for part in calls[-1][0])
    assert value["host"] == "wsl"
    with pytest.raises(ValueError, match="ext4"):
        agentjob.WslHost(configuration | {"worktree_root": "/mnt/c/jobs"}, "codex")


@pytest.mark.parametrize("ending", ["continue", "done"])
def test_fake_resume_and_budget(tmp_path, monkeypatch, ending):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-sentinel-key-987654")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
    value = job(tmp_path, repo=str(repo), budget={"max_iterations": 2}, model={"name": "owner-model", "effort": "high"})
    fixtures = []
    for index, status in enumerate(["continue", ending]):
        path = tmp_path / f"turn-{index}.jsonl"
        report = {"status": status, "summary": "fixture-sentinel-key-987654", "handoff": "sealed state", "blockers": []}
        path.write_text('\n'.join(json.dumps(e) for e in [{"type":"thread.started","thread_id":"session"},{"type":"item.completed","item":{"type":"agent_message","text":json.dumps(report)}},{"type":"turn.completed"}]))
        fixtures.append(path)
    seen = []
    def argv(job, session, windows):
        seen.append((session, dict(job["model"])))
        return [str(ROOT / "tests/fake_cli.py"), str(fixtures[len(seen)-1])]
    monkeypatch.setattr(agentjob.codex, "build_argv", argv)
    result = asyncio.run(agentjob.run_job(value, live=True, prepared=([sys.executable], agentjob.child_env(value), prepared())))
    assert result["status"] == ("done" if ending == "done" else "budget_exhausted")
    assert seen == [(None, value["model"]), ("session", value["model"])]
    assert result["iterations"] == 2
    artifact = repo / ".tmp/agent-jobs/test-job"
    for name in ("run.jsonl", "result.json"):
        assert "fixture-sentinel-key-987654" not in (artifact / name).read_text(encoding="utf-8")


def test_cursor_context_error_detection():
    frames = Frames("cursor")
    frames.parse_event({"type":"error","message":"context_length_exceeded"})
    assert frames.context_error


def test_cursor_context_error_sealed_recovery(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
    value = job(tmp_path, cli="cursor", repo=str(repo), budget={"max_iterations": 3})
    sessions = []
    prompts = []
    def argv(job, session, windows):
        sessions.append(session)
        return ["synthetic"]
    async def execute(argv, prompt, cwd, env, deadline, cancel, log, frames, remote_cancel):
        prompts.append(prompt)
        if len(prompts) == 2:
            frames.parse_event({"type": "error", "message": "compaction failed"})
            return 1, None
        frames.parse_event({"type":"system","subtype":"init","session_id":"cursor-session","apiKeySource":"login"})
        frames.parse_event({"type":"assistant","message":{"content":[{"type":"text","text":json.dumps({"status":"continue" if len(prompts)==1 else "done","summary":"fixture","handoff":"sealed fixture state","blockers":[]})}]}})
        frames.parse_event({"type":"result","is_error":False})
        return 0, None
    monkeypatch.setattr(agentjob.cursor, "build_argv", argv)
    monkeypatch.setattr(agentjob, "execute", execute)
    result = asyncio.run(agentjob.run_job(value, live=True, prepared=(["synthetic"], agentjob.child_env(value), prepared("cursor"))))
    assert result["status"] == "done"
    assert sessions == [None, "cursor-session", None]
    assert "sealed fixture state" in prompts[-1]


def test_windows_direct_launch_resolution(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    folder = tmp_path / "cursor-agent/versions/2026.10.fixture"
    folder.mkdir(parents=True)
    (folder / "node.exe").touch()
    (folder / "index.js").touch()
    assert agentjob.resolve_binary("cursor", windows=True) == [str(folder / "node.exe"), str(folder / "index.js")]
    monkeypatch.setenv("APPDATA", str(tmp_path))
    folder = tmp_path / "npm/node_modules/@openai/codex/vendor/bin"
    folder.mkdir(parents=True)
    (folder / "codex.exe").touch()
    assert agentjob.resolve_binary("codex", windows=True) == [str(folder / "codex.exe")]


@pytest.mark.parametrize("cli,source", [("claude", "ANTHROPIC_API_KEY"), ("claude", "apiKeyHelper"), ("cursor", "env")])
def test_in_run_auth_guard(cli, source):
    frames = Frames(cli)
    frames.parse_event({"type":"system","subtype":"init","apiKeySource":source})
    assert frames.failure == "auth_route_mismatch"
    api = Frames(cli, "api")
    api.parse_event({"type":"system","subtype":"init","apiKeySource":source})
    assert api.failure is None


def test_wsl_preflight_storage_and_identity(tmp_path, monkeypatch):
    configuration = {"distro": "Ubuntu-fixture", "repo": "/home/test/repo", "worktree_root": "/home/test/jobs", "home": "/home/test", "path": "/usr/bin:/bin", "binary": "/home/test/bin/codex"}
    value = job(tmp_path, host="wsl", wsl=configuration)
    def run(host, argv, *args, **kwargs):
        if argv[0] == "stat":
            return "ext2/ext3"
        if "--help" in argv:
            return "--ignore-user-config --output-schema --json"
        if "status" in argv:
            return "Logged in using ChatGPT"
        return "codex SYNTHETIC"
    monkeypatch.setattr(agentjob.WslHost, "run", run)
    binary, env, identity = agentjob.preflight(value, tmp_path)
    assert binary == [configuration["binary"]]
    assert identity["host"] == "wsl"
    assert "wsl distro=Ubuntu-fixture" in identity["configuration_sources"]


@pytest.mark.parametrize("unknown", [False, True])
def test_claude_whole_job_cost_ceiling(tmp_path, monkeypatch, unknown):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
    value = job(tmp_path, cli="claude", repo=str(repo), budget={"max_iterations": 3, "max_usd": 1.0})
    ceilings = []
    def argv(job, session, windows):
        ceilings.append(job["budget"]["max_usd"])
        return ["synthetic"]
    async def execute(argv, prompt, cwd, env, deadline, cancel, log, frames, remote_cancel):
        turn = len(ceilings)
        frames.parse_event({"type":"system","subtype":"init","session_id":"same-session","apiKeySource":"none"})
        frames.parse_event({"type":"result","structured_output":{"status":"done" if turn==3 else "continue","summary":"fixture","handoff":"state","blockers":[]},"total_cost_usd":None if unknown and turn==2 else turn*.2,"usage":{"input_tokens":turn*10,"output_tokens":0}})
        return 0, None
    monkeypatch.setattr(agentjob.claude, "build_argv", argv)
    monkeypatch.setattr(agentjob, "execute", execute)
    result = asyncio.run(agentjob.run_job(value, live=True, prepared=(["synthetic"], agentjob.child_env(value), prepared("claude"))))
    assert ceilings == pytest.approx([1.0, .8] if unknown else [1.0, .8, .6])
    assert result["status"] == ("blocked" if unknown else "done")
    assert result["usage"]["cost_usd"] is None if unknown else result["usage"]["cost_usd"] == pytest.approx(.6)
    if not unknown:
        assert result["usage"]["tokens"] == 30


def test_cleanup_error_writes_failed_receipt(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
    value = job(tmp_path, repo=str(repo))
    original = agentjob.git
    def git(repo, *args):
        if args[0] == "diff":
            raise OSError("fixture cleanup failure")
        return original(repo, *args)
    monkeypatch.setattr(agentjob, "git", git)
    monkeypatch.setattr(agentjob.codex, "build_argv", lambda *a: [str(ROOT / "tests/fake_cli.py"), str(ROOT / "tests/fixtures/codex/success-structured.jsonl")])
    result = asyncio.run(agentjob.run_job(value, live=True, prepared=([sys.executable], agentjob.child_env(value), prepared())))
    assert result["status"] == "failed"
    assert result["reason"].startswith("cleanup_liability:")
    assert (repo / ".tmp/agent-jobs/test-job/result.json").exists()
    assert json.loads((repo / ".tmp/agent-jobs/test-job/status.json").read_text())["status"] == "failed"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell platform behavior")
def test_powershell_cmdlet_errors_fail(tmp_path):
    argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "$ErrorActionPreference='Stop'; Get-Item -LiteralPath 'absent-fixture-path'; if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }"]
    code, reason = asyncio.run(agentjob.execute(argv, "", tmp_path, dict(os.environ), time.monotonic()+5, tmp_path / "cancel", io.StringIO()))
    assert code != 0 and reason is None


def test_expired_deadline_refuses_before_spawn(tmp_path, monkeypatch):
    async def spawn(*args, **kwargs):
        pytest.fail("expired job spawned a subprocess")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    code, reason = asyncio.run(agentjob.execute(["not-launched"], "", tmp_path, {}, time.monotonic()-1, tmp_path/"cancel", io.StringIO()))
    assert code is None and reason == "timeout"


@pytest.mark.parametrize("path", ["schema:$.items[*].done", "schema:$.x[?(@.a)]", "schema:$.x[-1]", "schema:$.x()"])
def test_selector_invalid_refuses_before_spawn(tmp_path, monkeypatch, path):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("spawned"))
    with pytest.raises((ValueError, jsonschema.ValidationError)):
        job(tmp_path, done_when=path, output_schema={"type":"object"})


@pytest.mark.parametrize("ready,expected", [(True,"done"), (False,"budget_exhausted"), (None,"budget_exhausted"), ("true","failed")])
def test_schema_completion_requires_valid_exact_true(tmp_path, monkeypatch, ready, expected):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
    output_schema = {"type":"object","properties":{"criteria":{"type":"object","properties":{"ready":{"type":"boolean"}}}}}
    value = job(tmp_path, repo=str(repo), done_when="schema:$.criteria.ready", output_schema=output_schema, budget={"max_iterations":1})
    report = {"status":"done","summary":"fixture","handoff":"state","blockers":[],"criteria":{}}
    if ready is not None:
        report["criteria"]["ready"] = ready
    fixture = tmp_path / "selector.jsonl"
    fixture.write_text('\n'.join(json.dumps(event) for event in [{"type":"thread.started","thread_id":"session"},{"type":"item.completed","item":{"type":"agent_message","text":json.dumps(report)}},{"type":"turn.completed"}]))
    monkeypatch.setattr(agentjob.codex, "build_argv", lambda *a: [str(ROOT / "tests/fake_cli.py"), str(fixture)])
    result = asyncio.run(agentjob.run_job(value, live=True, prepared=([sys.executable], agentjob.child_env(value), prepared())))
    assert result["status"] == expected
    if ready is True:
        assert result["report"]["criteria"]["ready"] is True


def test_selector_array_index_and_strict_boolean():
    assert agentjob.selector_done({"checks":[{"passed":True}]}, "$.checks[0].passed")
    assert not agentjob.selector_done({"checks":[{"passed":1}]}, "$.checks[0].passed")
    assert not agentjob.selector_done({"checks":[]}, "$.checks[0].passed")
