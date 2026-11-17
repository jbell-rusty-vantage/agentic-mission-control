"""Run a local installation's two process roles in the background, evaluate it, and stop it.

The installation is the directory ``scripts/dev/local_installation.py`` prepared (default
``.scratch/local-stack/<app>/``). Every process this script starts gets operating-system
essentials plus that directory's ``mission-control.env`` and nothing else, so no Mission Control
setting, database name or credential of the calling shell (or of a repository ``.env``) reaches it.

* ``up``: starts ``mission-control api`` (``python -m mission_control.bootstrap.cli api``) and
  waits for ``/health/ready``; then the worker (``... cli worker``) and waits until Temporal
  reports a poller on the installation's root task queue. ``--worker auto`` (default) starts
  the worker only when the installation recorded its prerequisites as present; ``on`` requires
  it; ``off`` leaves it out. Logs go to ``logs/<role>.log``; ``run/<role>.pid`` and
  ``run/stack.json`` record what was started. A role that does not come up fails the command
  and everything this run started is stopped again.
* ``down``: stops exactly the processes ``run/stack.json`` records, each identified by its pid
  AND its creation time (a reused pid is never touched), with their child processes.
* ``status``: what is recorded, what is alive and the API's readiness.
* ``eval``: re-mints the operator bearer and runs ``scripts/consumer_surface_eval.py`` against
  the running API; the scorecard lands in ``eval/``. It is a scorecard, not a gate: the exit
  code is non-zero only when the evaluation could not run.

    uv run --no-sync python scripts/dev/local_stack.py up --app ai-engineer --port 8020
    uv run --no-sync python scripts/dev/local_stack.py eval --app ai-engineer
    uv run --no-sync python scripts/dev/local_stack.py down --app ai-engineer
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any


def _sibling(name: str) -> ModuleType:
    """A script beside this one as a module (the repository's own loading idiom)."""

    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# The installation's layout, environment rule and refusals are the installer's.
installation = _sibling("local_installation")
ROOT = installation.ROOT
ENTRYPOINT = "mission_control.bootstrap.cli"
ROLES = ("api", "worker")
STACK = "run/stack.json"
READY_TIMEOUT_SECONDS = 240
WORKER_TIMEOUT_SECONDS = 180
STOP_GRACE_SECONDS = 20
# Never show a credential when a role's log tail is printed.
REDACTIONS = (
    re.compile(r"postgres(?:ql)?://\S+"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    # Also inside a longer name (`OPENAI_API_KEY=...`, `MC_AIENG_DB_RUNTIME_DSN: ...`).
    re.compile(r"(?i)(password|secret|token|api[_-]?key|dsn)(\w*\s*[=:]\s*)\S+"),
)


class StackError(Exception):
    """The stack could not be started, evaluated or described (the message is safe to print)."""


# ------------------------------------------------------------------------------------- processes


def process_start(pid: int) -> str | None:
    """A token for the creation instant of the live process ``pid``; ``None`` when there is none.

    A pid alone does not identify a process (the system reuses them); the pair does.
    """

    if pid <= 0:
        return None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
            code = wintypes.DWORD()
            if not kernel32.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ) or not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return None
            if code.value != 259:  # STILL_ACTIVE
                return None
            return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
        finally:
            kernel32.CloseHandle(handle)
    stat = Path(f"/proc/{pid}/stat")
    if stat.is_file():
        try:
            # Field 22 (starttime); the command name in parentheses may hold spaces.
            fields = stat.read_text(encoding="utf-8", errors="replace").rsplit(")", 1)[1].split()
        except (OSError, IndexError):
            return None
        return None if fields[0] == "Z" else fields[19]
    listed = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, check=False
    )
    return listed.stdout.strip() or None


def spawn(command: list[str], environment: dict[str, str], log: Path) -> subprocess.Popen[bytes]:
    """Start ``command`` detached from this terminal, its output appended to ``log``."""

    log.parent.mkdir(parents=True, exist_ok=True)
    # Its own process group (Windows: no console window) or session (POSIX), so it outlives
    # this command and can be stopped as a group.
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    with log.open("ab") as stream:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        stream.write(f"\n==== {stamp} start: {' '.join(command[1:])}\n".encode())
        stream.flush()
        return subprocess.Popen(
            command,
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stream,
            stderr=subprocess.STDOUT,
            close_fds=True,
            creationflags=flags,
            start_new_session=sys.platform != "win32",
        )


def stop_process(pid: int, started: str, *, grace: float = STOP_GRACE_SECONDS) -> str:
    """Stop the recorded process and its children; never a process with another creation time."""

    if process_start(pid) != started:
        return "not running"
    if sys.platform == "win32":
        # The virtual environment's python.exe is a launcher: the interpreter is its child.
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, check=False
        )
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if process_start(pid) != started:
            return "stopped"
        time.sleep(0.25)
    if sys.platform != "win32":
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pid, signal.SIGKILL)
        time.sleep(0.5)
    return "stopped" if process_start(pid) != started else "still running"


def redacted_tail(log: Path, lines: int = 40) -> str:
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    tail = text.splitlines()[-lines:]
    for index, line in enumerate(tail):
        line = REDACTIONS[0].sub("<dsn>", line)
        line = REDACTIONS[1].sub("<token>", line)
        tail[index] = REDACTIONS[2].sub(r"\1\2<redacted>", line)
    return "\n".join(tail)


# ------------------------------------------------------------------------------------- probes


def probe_host(host: str) -> str:
    return "127.0.0.1" if host in {"0.0.0.0", "::"} else host


def port_in_use(host: str, port: int) -> bool:
    try:
        with socket.create_connection((probe_host(host), port), timeout=1):
            return True
    except OSError:
        return False


def api_ready(url: str) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{url}/health/ready", timeout=3) as response:
            if response.status != 200:
                return None
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


async def _pollers(address: str, namespace: str, task_queue: str) -> int:
    from temporalio.api.enums.v1 import TaskQueueType
    from temporalio.api.taskqueue.v1 import TaskQueue
    from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
    from temporalio.client import Client

    client = await Client.connect(address, namespace=namespace)
    response = await client.workflow_service.describe_task_queue(
        DescribeTaskQueueRequest(
            namespace=namespace,
            task_queue=TaskQueue(name=task_queue),
            task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
        )
    )
    return len(response.pollers)


def worker_pollers(temporal: dict[str, str]) -> int:
    """Workflow pollers Temporal reports on the installation's root task queue (0 on any error)."""

    try:
        return asyncio.run(
            asyncio.wait_for(
                _pollers(temporal["address"], temporal["namespace"], temporal["root_task_queue"]),
                timeout=10,
            )
        )
    except Exception:
        return 0


def worker_wanted(mode: str, prerequisites: dict[str, Any]) -> bool:
    """``on`` always, ``off`` never, ``auto`` only when the installation recorded the worker's
    prerequisites (the capability resource owner, pinned skill bundles, Node) as present."""

    return mode == "on" or (mode == "auto" and bool(prerequisites.get("ready")))


# ------------------------------------------------------------------------------------- the stack


class Stack:
    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()
        self.state = installation.load_state(self.directory)
        if self.state is None or "binding_digest" not in self.state:
            raise StackError(
                f"{self.directory} holds no finished installation; run `make local-install` first"
            )
        self.application: str = self.state["application"]
        self.record_path = self.directory / STACK

    def environment(self) -> dict[str, str]:
        """The env file, then each credential the installation references (``--credential``):
        its value read from its ignored file now, by name, so the installation holds none."""

        values = installation.read_env_file(self.directory / installation.ENV_FILE)
        if not values.get("MISSION_CONTROL_DEPLOYMENT_FILE"):
            raise StackError(f"{installation.ENV_FILE} is missing or incomplete; rerun the install")
        for name, file in sorted((self.state.get("credentials") or {}).items()):
            value = installation.read_env_file(Path(file)).get(name)
            if not value:
                raise StackError(f"credential {name} has no value in its referenced file {file}")
            values[name] = value
        return installation.base_environment(values)

    def temporal(self) -> dict[str, str]:
        document = json.loads(
            (self.directory / installation.dep.DEPLOYMENT).read_text(encoding="utf-8")
        )
        return dict(document["applications"][0]["temporal"])

    def record(self) -> dict[str, Any]:
        if not self.record_path.is_file():
            return {}
        try:
            value = json.loads(self.record_path.read_text(encoding="utf-8"))
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def alive(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            item
            for item in record.get("processes", [])
            if process_start(int(item["pid"])) == item["started"]
        ]

    def write_record(self, record: dict[str, Any]) -> None:
        run = self.record_path.parent
        run.mkdir(parents=True, exist_ok=True)
        for item in record["processes"]:
            (run / f"{item['role']}.pid").write_text(f"{item['pid']}\n", encoding="utf-8")
        self.record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    def clear_record(self) -> None:
        for path in (*self.record_path.parent.glob("*.pid"), self.record_path):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()

    def start(self, role: str, arguments: list[str]) -> dict[str, Any]:
        command = [sys.executable, "-m", ENTRYPOINT, role, *arguments]
        log = self.directory / "logs" / f"{role}.log"
        process = spawn(command, self.environment(), log)
        started = None
        for _ in range(40):  # the creation time is readable as soon as the process exists
            started = process_start(process.pid)
            if started is not None or process.poll() is not None:
                break
            time.sleep(0.05)
        if started is None:
            raise StackError(
                f"the {role} exited at once (exit {process.poll()}); see {log}\n"
                f"{redacted_tail(log)}"
            )
        return {
            "role": role,
            "pid": process.pid,
            "started": started,
            "command": ["mission-control", role, *arguments],
            "log": log.relative_to(self.directory).as_posix(),
        }

    def wait(self, item: dict[str, Any], ready: Any, timeout: float, what: str) -> Any:
        log = self.directory / item["log"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process_start(int(item["pid"])) != item["started"]:
                raise StackError(
                    f"the {item['role']} exited before {what}; see {log}\n{redacted_tail(log)}"
                )
            result = ready()
            if result:
                return result
            time.sleep(1.0)
        raise StackError(
            f"the {item['role']} did not reach {what} in {timeout:.0f}s; see {log}\n"
            f"{redacted_tail(log)}"
        )

    # -- commands ------------------------------------------------------------------------------

    def up(self, host: str, port: int, worker: str) -> dict[str, Any]:
        existing = self.record()
        alive = self.alive(existing)
        if alive:
            raise StackError(
                f"already running ({', '.join(item['role'] for item in alive)} at "
                f"{existing.get('url')}); run `make local-down` first"
            )
        self.clear_record()
        if port_in_use(host, port):
            raise StackError(f"{probe_host(host)}:{port} is in use; pass another PORT")
        url = f"http://{probe_host(host)}:{port}"
        record: dict[str, Any] = {
            "schema": "mc.local_stack.v1",
            "application": self.application,
            "url": url,
            "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "processes": [],
        }
        prerequisites = self.state.get("worker") or {}
        with_worker = worker_wanted(worker, prerequisites)
        try:
            api = self.start("api", ["--host", host, "--port", str(port)])
            record["processes"].append(api)
            self.write_record(record)
            record["ready"] = self.wait(
                api, lambda: api_ready(url), READY_TIMEOUT_SECONDS, "/health/ready"
            )
            if with_worker:
                temporal = self.temporal()
                item = self.start("worker", [])
                record["processes"].append(item)
                self.write_record(record)
                record["worker_pollers"] = self.wait(
                    item,
                    lambda: worker_pollers(temporal),
                    WORKER_TIMEOUT_SECONDS,
                    f"a poller on {temporal['root_task_queue']} ({temporal['namespace']})",
                )
            else:
                reason = "left out (--worker off)" if worker == "off" else "prerequisites missing"
                record["worker_skipped"] = {
                    "reason": reason,
                    "missing": [] if worker == "off" else prerequisites.get("missing", []),
                }
        except BaseException:
            for item in record["processes"]:
                stop_process(int(item["pid"]), item["started"])
            self.clear_record()
            raise
        self.write_record(record)
        return {"status": "up", **record}

    def down(self) -> dict[str, Any]:
        record = self.record()
        outcomes = {
            item["role"]: {
                "pid": item["pid"],
                "outcome": stop_process(int(item["pid"]), item["started"]),
            }
            for item in reversed(record.get("processes", []))
        }
        if any(value["outcome"] == "still running" for value in outcomes.values()):
            raise StackError(f"a process did not stop: {json.dumps(outcomes)}")
        self.clear_record()
        return {"status": "down", "application": self.application, "processes": outcomes}

    def status(self) -> dict[str, Any]:
        record = self.record()
        alive = {item["role"] for item in self.alive(record)}
        url = record.get("url")
        return {
            "status": "up" if alive else "down",
            "application": self.application,
            "url": url,
            "processes": {
                item["role"]: {"pid": item["pid"], "alive": item["role"] in alive}
                for item in record.get("processes", [])
            },
            "ready": api_ready(url) if url and "api" in alive else None,
        }

    def evaluate(self) -> int:
        record = self.record()
        url = record.get("url")
        if not url or "api" not in {item["role"] for item in self.alive(record)}:
            raise StackError("the API is not running; run `make local-up` first")
        minted = subprocess.run(
            [
                sys.executable,
                "scripts/dev/local_installation.py",
                "token",
                "--app",
                self.application,
                "--out",
                str(self.directory),
            ],
            cwd=ROOT,
            env=installation.base_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
        if minted.returncode != 0:
            raise StackError(f"the operator bearer could not be minted (exit {minted.returncode})")
        out = self.directory / "eval"
        done = subprocess.run(
            [
                sys.executable,
                "scripts/consumer_surface_eval.py",
                "--url",
                url,
                "--application",
                self.application,
                "--token-file",
                str(self.directory / installation.dep.TOKEN),
                "--out",
                str(out),
            ],
            cwd=ROOT,
            env=installation.base_environment({"PYTHONIOENCODING": "utf-8"}),
            check=False,
        )
        if done.returncode != 0:
            raise StackError(f"the evaluation could not run (exit {done.returncode})")
        print(f"scorecard: {(out / 'scorecard.md').as_posix()}", flush=True)
        return 0


# ------------------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("command", choices=("up", "down", "status", "eval"))
    parser.add_argument("--app", choices=installation.APPLICATIONS)
    parser.add_argument("--dir", type=Path, help="default .scratch/local-stack/<app>")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--worker", choices=("auto", "on", "off"), default="auto")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    directory = args.dir or installation.default_out(args.app or installation.DEFAULT_APPLICATION)
    try:
        installation.gen.assert_ignored(directory.resolve() / STACK)
        stack = Stack(directory)
        if args.command == "eval":
            return stack.evaluate()
        if args.command == "up":
            document = stack.up(args.host, args.port, args.worker)
        elif args.command == "down":
            document = stack.down()
        else:
            document = stack.status()
    except (StackError, installation.Refused) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(document, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
