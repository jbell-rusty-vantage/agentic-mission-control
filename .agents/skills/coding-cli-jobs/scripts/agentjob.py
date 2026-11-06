# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6,<7", "jsonschema>=4,<5"]
# ///
"""Local CLI jobs. Live launches require an explicit per-invocation opt-in."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

import jsonschema
import yaml

from adapters import claude, codex, cursor
from adapters.common import Frames, REPORT_SCHEMA
from wsl_host import WslHost

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = {"claude": claude, "codex": codex, "cursor": cursor}
ENV_NAMES = {
    "PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TEMP", "TMP", "CODEX_HOME",
    "CLAUDE_CONFIG_DIR", "APPDATA", "LOCALAPPDATA", "COMSPEC", "PATHEXT", "WINDIR",
    "PROGRAMDATA", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS", "LANG",
    "SYSTEMDRIVE", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432",
    "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
}


def child_env(job, source=None):
    source = os.environ if source is None else source
    names = set(ENV_NAMES)
    if job["cli"] == "cursor" and job["auth"] == "api":
        names.add("CURSOR_API_KEY")
    if job["cli"] == "claude":
        names.add("CLAUDE_CODE_OAUTH_TOKEN" if job["auth"] == "subscription" else "ANTHROPIC_API_KEY")
    if job["cli"] == "codex" and job["auth"] == "api":
        names.add("OPENAI_API_KEY")
    return {k: v for k, v in source.items() if k.upper() in names}


def redact(text, source=None):
    source = os.environ if source is None else source
    for key, value in source.items():
        if value and len(value) >= 4 and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            text = text.replace(value, "[REDACTED]")
    return re.sub(r"(?i)(?:\b(?:sk-|key_)[A-Za-z0-9_\-]+|\bbearer\s+[A-Za-z0-9._~+/=\-]+)", "[REDACTED]", text)


def write_json(path, value):
    temporary = path.with_suffix(".new")
    temporary.write_text(redact(json.dumps(value, indent=2, allow_nan=False)), encoding="utf-8")
    temporary.replace(path)


def load_job(path):
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    jsonschema.validate(value, json.loads((ROOT / "schemas/job.schema.json").read_text()))
    defaults = {
        "repo": ".", "host": "auto", "permissions": "read-only", "auth": "subscription",
        "model": {"name": None, "effort": None}, "allow_commands": [], "verify": [],
        "context_files": [], "output_schema": None, "resume_id": None,
        "done_when": "verify_pass_and_agent_done",
        "worktree": {"mode": "git", "base": "HEAD", "keep": "on_change"},
        "budget": {"max_iterations": 4, "max_turns_per_iteration": 40, "wall_clock_min": 45, "max_usd": None},
    }
    for key, default in defaults.items():
        if isinstance(default, dict):
            value[key] = default | value.get(key, {})
        else:
            value.setdefault(key, default)
    value["new_session_id"] = str(uuid.uuid4())
    validate_options(value)
    return value


def validate_options(job):
    if job["done_when"].startswith("schema:"):
        selector_tokens(job["done_when"].removeprefix("schema:"))
        if job["output_schema"] is None:
            raise ValueError("schema completion requires an explicit output_schema")
    if job["host"] == "wsl":
        if job["cli"] != "codex" or not job.get("wsl"):
            raise ValueError("WSL requires explicit Codex distro/repo/ext4 workspace/binary/home/path")
        if job["auth"] != "subscription":
            raise ValueError("WSL API delivery is unsupported; use an explicit Linux subscription home")
        WslHost(job["wsl"], job["cli"])
    if job["worktree"]["mode"] == "native":
        raise ValueError("native worktree mode unsupported; use git")
    if job["permissions"] != "read-only" and job["worktree"]["mode"] != "git":
        raise ValueError("edit/full require an isolated git worktree")
    if job["cli"] == "cursor" and job["model"]["effort"] is not None:
        raise ValueError("Cursor effort unsupported")
    if job["cli"] == "claude" and job["model"]["effort"] == "minimal":
        raise ValueError("Claude minimal effort unsupported")
    if job["cli"] != "claude" and job["budget"]["max_usd"] is not None:
        raise ValueError("CLI cannot enforce max_usd; omit rather than silently degrade")
    if job["resume_id"] and job["cli"] == "claude":
        uuid.UUID(job["resume_id"])


def selector_tokens(path):
    """Closed JSONPath subset: dot members and nonnegative array indexes only."""
    if not re.fullmatch(r"\$(?:\.[A-Za-z_][A-Za-z0-9_-]*|\[(?:0|[1-9][0-9]*)\])+", path):
        raise ValueError("completion selector supports only $.member and [nonnegative-index]")
    return [name if name else int(index) for name, index in re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)|\[([0-9]+)\]", path)]


def selector_done(report, path):
    value = report
    for token in selector_tokens(path):
        if isinstance(token, str) and isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(token, int) and isinstance(value, list) and token < len(value):
            value = value[token]
        else:
            return False
    return value is True


def resolve_binary(cli, windows=None):
    windows = os.name == "nt" if windows is None else windows
    if windows and cli == "cursor":
        root = Path(os.environ.get("LOCALAPPDATA", "")) / "cursor-agent/versions"
        candidates = sorted(root.glob("*/node.exe"), reverse=True)
        for node in candidates:
            entry = node.with_name("index.js")
            if entry.is_file():
                return [str(node), str(entry)]
    if windows and cli == "codex":
        root = Path(os.environ.get("APPDATA", "")) / "npm/node_modules/@openai"
        candidates = list(root.glob("**/codex.exe"))
        if len(candidates) == 1:
            return [str(candidates[0])]
    binary = shutil.which({"claude": "claude", "codex": "codex", "cursor": "agent"}[cli])
    if not binary or (windows and Path(binary).suffix.lower() != ".exe"):
        raise ValueError(f"direct {cli} binary unavailable; install/setup is a separate action")
    return [binary]


def probe(argv, env, cwd):
    result = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=15, check=False)
    if result.returncode:
        raise ValueError("CLI preflight refused: " + redact(result.stderr[-1500:]))
    return (result.stdout + result.stderr).strip()


def preflight(job, cwd):
    validate_options(job)
    host = WslHost(job["wsl"], job["cli"]) if job["host"] == "wsl" else None
    binary = [job["wsl"]["binary"]] if host else resolve_binary(job["cli"])
    if host:
        filesystem = host.run(["stat", "-f", "-c", "%T", job["wsl"]["worktree_root"]])
        if filesystem != "ext2/ext3":
            raise ValueError("WSL worktree root is not verified ext4/ext-family storage")
        host.run(["test", "-x", "/usr/bin/setsid"])
        host.run(["test", "-x", "/bin/kill"])
    env = child_env(job)
    def check(argv):
        return host.run(argv) if host else probe(argv, env, cwd)
    version = check(binary + ["--version"])
    help_args = ["exec", "--help"] if job["cli"] == "codex" else ["--help"]
    help_text = check(binary + help_args)
    required = {"claude": ["--permission-mode", "--json-schema", "--setting-sources"],
                "codex": ["--ignore-user-config", "--output-schema", "--json"],
                "cursor": ["--trust", "--sandbox", "--output-format"]}[job["cli"]]
    if job["model"]["name"]:
        required.append("--model")
    if job["model"]["effort"] and job["cli"] == "claude":
        required.append("--effort")
    missing = [flag for flag in required if flag not in help_text]
    if missing:
        raise ValueError("installed CLI lacks required options: " + ", ".join(missing))
    if job["auth"] == "api":
        key = {"claude": "ANTHROPIC_API_KEY", "codex": "OPENAI_API_KEY", "cursor": "CURSOR_API_KEY"}[job["cli"]]
        if not env.get(key):
            raise ValueError(f"explicit API auth requires {key}")
    else:
        args = {"claude": ["auth", "status"], "codex": ["login", "status"], "cursor": ["status", "--format", "json"]}[job["cli"]]
        auth = check(binary + args)
        if job["cli"] == "codex":
            if "chatgpt" not in auth.lower():
                raise ValueError("subscription guard requires ChatGPT login")
        else:
            parsed = json.loads(auth)
            if job["cli"] == "claude" and parsed.get("authMethod") not in {"claude.ai", "oauth_token"}:
                raise ValueError("subscription guard requires Claude OAuth")
            if job["cli"] == "cursor" and not (parsed.get("authenticated") is True or parsed.get("isAuthenticated") is True):
                raise ValueError("Cursor login status is not authenticated")
    identity = {"cli": job["cli"], "version": version, "binary": binary,
                "host": "wsl" if host else "native", "requested_model": job["model"]["name"],
                "requested_effort": job["model"]["effort"], "observed_model": None,
                "model_selection": "explicit" if job["model"]["name"] else "native_default",
                "auth": job["auth"], "permissions": job["permissions"],
                "configuration_sources": ["job", "explicit adapter flags", "project instructions",
                                          "native auth home", "native defaults when omitted"]}
    if host:
        identity["configuration_sources"] += ["wsl distro=" + job["wsl"]["distro"], "linux repo=" + job["wsl"]["repo"], "linux auth home=" + job["wsl"]["home"], "linux workspace root=" + job["wsl"]["worktree_root"]]
    return binary, env, identity


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True, stderr=subprocess.STDOUT).strip()


def kill_tree(process):
    if process.returncode is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class WindowsJob:
    """Kill-on-close Job Object; refuse launch when descendant custody fails."""
    def __init__(self, pid):
        self.handle = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel = kernel
        handle = kernel.CreateJobObjectW(None, None)
        process_handle = kernel.OpenProcess(0x0100 | 0x0001, False, pid)
        limits = Extended()
        limits.BasicLimitInformation.LimitFlags = 0x2000
        try:
            if not handle or not process_handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not kernel.AssignProcessToJobObject(handle, process_handle):
                raise OSError(ctypes.get_last_error(), "Windows Job Object custody failed")
            self.handle = handle
        finally:
            if process_handle:
                kernel.CloseHandle(process_handle)
            if handle and self.handle is None:
                kernel.CloseHandle(handle)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


async def execute(argv, prompt, cwd, env, deadline, cancel, log, frames=None, remote_cancel=None):
    if cancel.exists() or time.monotonic() >= deadline:
        return None, "cancelled" if cancel.exists() else "timeout"
    process = await asyncio.create_subprocess_exec(
        *argv, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=os.name != "nt")
    try:
        custody = WindowsJob(process.pid)
    except OSError:
        kill_tree(process)
        await process.wait()
        raise
    async def consume(stream, parse):
        while line := await stream.readline():
            text = line.decode("utf-8", errors="replace")
            log.write(redact(text))
            log.flush()
            if parse and frames:
                try:
                    frames.parse_event(json.loads(text))
                    if frames.failure == "auth_route_mismatch":
                        if remote_cancel:
                            remote_cancel()
                        kill_tree(process)
                except (ValueError, AttributeError):
                    pass
    readers = [asyncio.create_task(consume(process.stdout, True)), asyncio.create_task(consume(process.stderr, False))]
    async def feed():
        try:
            process.stdin.write(prompt.encode("utf-8"))
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            process.stdin.close()
    feeder = asyncio.create_task(feed())
    reason = None
    try:
        while process.returncode is None:
            if cancel.exists() or time.monotonic() >= deadline:
                reason = "cancelled" if cancel.exists() else "timeout"
                if remote_cancel:
                    remote_cancel()
                kill_tree(process)
                break
            await asyncio.sleep(0.05)
        await process.wait()
        if remote_cancel:
            remote_cancel()
        custody.close()
        await asyncio.gather(feeder, *readers)
    finally:
        if remote_cancel:
            remote_cancel()
        kill_tree(process)
        custody.close()
    return process.returncode, reason


async def run_job(job, live=False, acknowledge=False, prepared=None):
    validate_options(job)
    if not live:
        raise ValueError("live execution is default-off; --allow-live requires action-specific owner authority")
    if job["permissions"] == "full" and not acknowledge:
        raise ValueError("full profile requires --i-understand")
    repo = Path(git(Path(job["repo"]).resolve(), "rev-parse", "--show-toplevel"))
    binary, env, identity = prepared or preflight(job, repo)
    artifact = repo / ".tmp/agent-jobs" / job["id"]
    artifact.mkdir(parents=True, exist_ok=False)
    write_json(artifact / "status.json", {"id": job["id"], "status": "running", "iteration": 0, "updated_at": time.time(), "identity": identity})
    host = WslHost(job["wsl"], job["cli"]) if job["host"] == "wsl" else None
    worktree = job["wsl"]["worktree_root"] + "/" + job["id"] if host else repo / ".worktrees" / job["id"]
    def workspace_git(*args):
        return host.git(str(worktree), *args) if host else git(worktree, *args)
    branch = "agentjob/" + job["id"]
    created = False
    status = "failed"
    report = {"status": "blocked", "summary": "No valid final report", "handoff": "", "blockers": []}
    session = job["resume_id"]
    checks = []
    usage = {"cost_usd": None, "tokens": None}
    session_usage = {}
    iterations = 0
    reason = None
    deadline = time.monotonic() + job["budget"]["wall_clock_min"] * 60
    try:
        if job["worktree"]["mode"] == "git":
            if host:
                host.git(job["wsl"]["repo"], "worktree", "add", "-b", branch, str(worktree), job["worktree"]["base"])
            else:
                git(repo, "worktree", "add", "-b", branch, str(worktree), job["worktree"]["base"])
            created = True
        else:
            worktree = repo
            branch = None
        schema = artifact / "report.schema.json"
        write_json(schema, job.get("output_schema") or REPORT_SCHEMA)
        job["schema_path"] = str(schema)
        if host:
            job["schema_path"] = str(worktree) + "/.agentjob-report-" + uuid.uuid4().hex + ".schema.json"
            host.write(job["schema_path"], json.dumps(job.get("output_schema") or REPORT_SCHEMA))
        if job["cli"] == "cursor" and job["permissions"] != "read-only":
            config = worktree / ".cursor/cli.json"
            if config.exists():
                raise ValueError("existing Cursor permission config requires explicit reviewed merge")
            config.parent.mkdir(exist_ok=True)
            write_json(config, {"permissions": {"allow": ["Read(**)", "Write(**)"] + [f"Shell({c})" for c in job["allow_commands"]],
                                               "deny": ["Shell(git push*)", "Shell(gh pr*)", "Shell(git merge*)"]}})
        feedback = ""
        for iterations in range(1, job["budget"]["max_iterations"] + 1):
            if (artifact / "cancel").exists():
                status, reason = "cancelled", "cancelled"
                break
            if job["cli"] == "cursor" and iterations > 3:
                session = None
                feedback = "Sealed handoff:\n" + report.get("handoff", "")
            prompt = (job["goal"] + "\nContext pointers: " + json.dumps(job["context_files"]) +
                      "\nRespect AGENTS.md. Never push, merge or open a PR.\nAllowed commands: " + json.dumps(job["allow_commands"]) +
                      "\nRunner verifies: " + json.dumps(job["verify"]) + "\n" + feedback +
                      "\nFinal report JSON schema: " + json.dumps(job.get("output_schema") or REPORT_SCHEMA) +
                      "\nend with a JSON report {status, summary, handoff, blockers}.\n")
            (artifact / f"prompt-{iterations}.md").write_text(redact(prompt), encoding="utf-8")
            frames = Frames(job["cli"], job["auth"])
            launch_job = job
            ceiling = job["budget"]["max_usd"]
            if ceiling is not None:
                if session_usage and usage["cost_usd"] is None:
                    status, reason = "blocked", "unknown_cost_under_ceiling"
                    break
                remaining = ceiling - (usage["cost_usd"] or 0)
                if remaining <= 0:
                    status, reason = "budget_exhausted", "cost_ceiling"
                    break
                launch_job = job | {"budget": job["budget"] | {"max_usd": remaining}}
            argv = binary + ADAPTERS[job["cli"]].build_argv(launch_job, session, os.name == "nt" and not host)
            remote_cancel = cleanup = None
            if host:
                argv, remote_cancel, cleanup = host.launch(argv, str(worktree))
            async def heartbeat():
                while True:
                    write_json(artifact / "status.json", {"id": job["id"], "status": "running", "iteration": iterations, "updated_at": time.time(), "identity": identity})
                    await asyncio.sleep(10)
            beat = asyncio.create_task(heartbeat())
            try:
                with (artifact / "run.jsonl").open("a", encoding="utf-8") as log:
                    code, reason = await execute(argv, prompt, repo if host else worktree, env, deadline, artifact / "cancel", log, frames, remote_cancel)
            finally:
                beat.cancel()
                await asyncio.gather(beat, return_exceptions=True)
                if cleanup:
                    cleanup()
            session = frames.session_id or session
            identity["observed_model"] = frames.model or identity["observed_model"]
            session_usage[session or f"unknown-{iterations}"] = {"cost_usd": frames.cost, "tokens": frames.tokens}
            usage = {key: sum(snapshot[key] for snapshot in session_usage.values())
                     if all(snapshot[key] is not None for snapshot in session_usage.values()) else None
                     for key in ("cost_usd", "tokens")}
            if ceiling is not None and usage["cost_usd"] is None:
                status, reason = "blocked", "unknown_cost_under_ceiling"
                break
            if ceiling is not None and usage["cost_usd"] >= ceiling:
                status, reason = "budget_exhausted", "cost_ceiling"
                break
            if reason:
                status = "cancelled" if reason == "cancelled" else "budget_exhausted"
                break
            if job["cli"] == "cursor" and frames.context_error and report.get("handoff") and iterations < job["budget"]["max_iterations"]:
                session = None
                feedback = "Sealed handoff after context error:\n" + report["handoff"]
                continue
            if frames.failure == "error_max_turns" and session:
                status = "budget_exhausted"
                feedback = "Previous turn reached max_turns. Continue the same goal within remaining runner budget."
                continue
            if code or frames.failure or not frames.terminal:
                reason = frames.failure or f"cli_exit_{code}_or_missing_terminal"
                status = "failed"
                break
            candidate = frames.final()
            try:
                jsonschema.validate(candidate, job.get("output_schema") or REPORT_SCHEMA)
                if not isinstance(candidate, dict):
                    raise jsonschema.ValidationError("report is not an object")
                envelope = {key: candidate[key] for key in REPORT_SCHEMA["required"] if key in candidate}
                jsonschema.validate(envelope, REPORT_SCHEMA)
            except jsonschema.ValidationError:
                status, reason = "failed", "invalid_final_report"
                break
            report = candidate
            checks = []
            for command in job["verify"]:
                shell = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "$ErrorActionPreference='Stop'; " + command + '; if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }'] if os.name == "nt" else ["/bin/sh", "-c", command]
                remote_cancel = cleanup = None
                if host:
                    shell, remote_cancel, cleanup = host.launch(["/bin/sh", "-c", command], str(worktree))
                with (artifact / "verify.log").open("a", encoding="utf-8") as log:
                    code, reason = await execute(shell, "", repo if host else worktree, env, deadline, artifact / "cancel", log, remote_cancel=remote_cancel)
                if cleanup:
                    cleanup()
                checks.append({"cmd": command, "exit": code})
                if reason:
                    break
            if reason:
                status = "cancelled" if reason == "cancelled" else "budget_exhausted"
                break
            passed = all(check["exit"] == 0 for check in checks)
            done = report["status"] == "done"
            if report["status"] == "blocked":
                status = "blocked"
                break
            mode = job["done_when"]
            completed = (
                (mode == "verify_pass_and_agent_done" and passed and done)
                or (mode == "verify_pass" and passed)
                or (mode == "agent_done" and done)
                or (mode.startswith("schema:") and selector_done(report, mode.removeprefix("schema:")))
            )
            if completed:
                status = "done"
                break
            status = "budget_exhausted"
            if not session:
                status, reason = "failed", "missing_resume_session"
                break
            feedback = "Verification feedback: " + json.dumps(checks) + "\n" + redact((artifact / "verify.log").read_text()[-4000:] if checks else "Continue toward the goal")
    except Exception as exc:
        status, reason = "failed", redact(str(exc))
    display_worktree, diffstat = str(worktree), ""
    retained = created
    try:
        if host and created:
            host.run(["rm", "-f", "--", job["schema_path"]], str(worktree))
        display_worktree = host.run(["wslpath", "-w", str(worktree)]) if host else str(worktree)
        diffstat = workspace_git("diff", "--stat", "HEAD") if created else ""
        dirty = bool(workspace_git("status", "--porcelain")) if created else True
        if created and not dirty and job["worktree"]["keep"] == "on_change":
            if host:
                host.git(job["wsl"]["repo"], "worktree", "remove", str(worktree))
                host.git(job["wsl"]["repo"], "branch", "-d", branch)
            else:
                git(repo, "worktree", "remove", str(worktree))
                git(repo, "branch", "-d", branch)
            retained = False
    except Exception as exc:
        status = "failed"
        reason = "cleanup_liability: " + redact(str(exc))
    result = {"id": job["id"], "cli": job["cli"], "status": status, "reason": reason,
              "session_id": session, "iterations": iterations, "verify": checks,
              "worktree": display_worktree, "branch": branch, "worktree_retained": retained,
              "diffstat": diffstat, "report": report, "usage": usage, "identity": identity,
              "artifacts": sorted(p.name for p in artifact.iterdir())}
    jsonschema.validate(result, json.loads((ROOT / "schemas/result.schema.json").read_text()))
    write_json(artifact / "result.json", result)
    write_json(artifact / "status.json", {"id": job["id"], "status": status, "updated_at": time.time()})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("jobs", nargs="+")
    run.add_argument("--max-parallel", type=int, default=1)
    run.add_argument("--allow-live", action="store_true")
    run.add_argument("--i-understand", action="store_true")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("job")
    for name in ("status", "cancel"):
        command = sub.add_parser(name)
        command.add_argument("id")
        command.add_argument("--repo", default=".")
        if name == "status":
            command.add_argument("--follow", action="store_true")
    args = parser.parse_args()
    if args.command == "run":
        jobs = [load_job(path) for path in args.jobs]
        if args.max_parallel < 1 or len({j["id"] for j in jobs}) != len(jobs):
            raise ValueError("parallelism must be positive and IDs unique")
        async def batch():
            semaphore = asyncio.Semaphore(args.max_parallel)
            async def one(job):
                async with semaphore:
                    return await run_job(job, args.allow_live, args.i_understand)
            return await asyncio.gather(*(one(j) for j in jobs))
        print(redact(json.dumps(asyncio.run(batch()), indent=2)))
    elif args.command == "doctor":
        job = load_job(args.job)
        print(redact(json.dumps(preflight(job, Path(job["repo"]).resolve())[2], indent=2)))
    else:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.id):
            raise ValueError("invalid job ID")
        repo = Path(git(Path(args.repo).resolve(), "rev-parse", "--show-toplevel"))
        artifact = repo / ".tmp/agent-jobs" / args.id
        if not artifact.is_dir():
            raise ValueError("unknown job")
        if args.command == "cancel":
            (artifact / "cancel").touch()
        else:
            previous = None
            while True:
                value = (artifact / "status.json").read_text(encoding="utf-8")
                state = json.loads(value)
                marker = (state["status"], state.get("iteration"))
                if marker != previous:
                    print(redact(json.dumps(state)), flush=True)
                    previous = marker
                if not args.follow or state["status"] != "running":
                    break
                time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, jsonschema.ValidationError) as error:
        print(redact(str(error)), file=sys.stderr)
        sys.exit(2)
