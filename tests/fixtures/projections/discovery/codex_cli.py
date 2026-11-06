"""Record what the real Codex app-server discovers from a codex Host Projection (MO-34).

``uv run --frozen python -m tests.fixtures.projections.discovery.codex_cli`` renders the same
``discovery_rows()`` as the Claude recorder for ``codex`` and layers it (MO-02) over a scratch git
repository that owns its cognition: an ``AGENTS.md``, an ``.agents/skills`` skill and a
``.codex/config.toml`` with its own MCP server. It writes the lane's isolated ``CODEX_HOME``
exactly as the codex lane does (project trust plus the hash trust of every projected hook),
starts the locally installed ``codex app-server`` over stdio, sends ``initialize`` and
``thread/start``, then the lane's discovery requests ``skills/list``, ``hooks/list`` and
``config/read``. Nothing reaches a model: no login exists in the scratch home, the session's
model provider is a closed loopback port (``127.0.0.1:9``) and no turn is started. It then
restores the repository files layering merged, checks they are byte-identical, and writes
``codex.recorded.json`` with workspace and home paths replaced by placeholders and the host
user's own skills (scope ``user``/``admin``) left out.

On Windows the npm ``codex`` shim is a ``.cmd`` script; set ``MC_CODEX_BINARY`` to the native
``codex.exe`` it wraps. The recording is a FIXTURE of local discovery by one exact CLI build: it
proves the projected files load in that build; it does not qualify the lane or exercise a turn.
"""

from __future__ import annotations

import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from tests.fixtures.layering_repo import REPO_FILES, repository_bytes, write_repository_files
from tests.fixtures.projections.discovery.claude_cli import (
    INSTRUCTION,
    STUB_TARGET,
    discovery_rows,
)

from mission_control.adapters.codex.harness import (
    CODEX_HOME_DIR,
    projected_hooks,
    trust_config_toml,
)
from mission_control.application.agentic_components.layering import restore_repository_files
from mission_control.application.agentic_components.materialization import (
    ProjectionMaterialization,
    materialize_projection,
    projection_digest,
    required_executables,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.projection import HostProjection
from mission_control.domain.capabilities.host_support import LaneProfile

HERE = Path(__file__).resolve().parent
RECORDING = HERE / "codex.recorded.json"
PROFILE = LaneProfile.CODEX
WORKSPACE = "<workspace>"
CODEX_HOME = "<codex_home>"
# The host's own skills are personal data; repo and bundled system skills are kept.
KEPT_SCOPES = frozenset({"repo", "system"})
CLOSED_PROVIDER = (
    'model_providers.mc-closed={name="closed loopback", base_url="http://127.0.0.1:9/v1", '
    'wire_api="responses"}'
)
REQUESTS: tuple[tuple[str, str], ...] = (
    ("skills_list", "skills/list"),
    ("hooks_list", "hooks/list"),
    ("config_read", "config/read"),
)

REPOSITORY: dict[str, bytes] = {
    "AGENTS.md": REPO_FILES["AGENTS.md"],
    ".agents/skills/repo-notes/SKILL.md": REPO_FILES[".claude/skills/repo-notes/SKILL.md"],
    ".codex/config.toml": REPO_FILES[".codex/config.toml"],
}


def project() -> HostProjection:
    return HOST_PROJECTORS.render(discovery_rows(), PROFILE, INSTRUCTION, kernel_hooks=())


def materialize(projection: HostProjection, root: Path) -> ProjectionMaterialization:
    materialization = materialize_projection(
        projection, root, executables=required_executables(discovery_rows(), PROFILE)
    )
    stub = root / STUB_TARGET
    stub.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HERE / "mcp_stub.py", stub)
    return materialization


def codex_home(projection: HostProjection, root: Path) -> Path:
    """The lane's isolated home: project trust and the hash trust of the placed hooks."""

    home = root / CODEX_HOME_DIR
    home.mkdir(parents=True, exist_ok=True)
    records, _kernel = projected_hooks(projection, root)
    (home / "config.toml").write_text(trust_config_toml(root, records), encoding="utf-8")
    return home


def _binary() -> str:
    binary = os.environ.get("MC_CODEX_BINARY") or shutil.which("codex") or "codex"
    if binary.lower().endswith((".cmd", ".bat")):
        raise SystemExit("set MC_CODEX_BINARY to the native codex executable the shim wraps")
    return binary


def _environment(home: Path) -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "COMSPEC", "PATHEXT", "LANG")
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env["CODEX_HOME"] = str(home)
    return env


class AppServer:
    """``codex app-server`` over stdio: newline-delimited JSON-RPC."""

    def __init__(self, binary: str, root: Path, home: Path) -> None:
        self.process = subprocess.Popen(
            [
                binary,
                "app-server",
                "-c",
                'model_provider="mc-closed"',
                "-c",
                CLOSED_PROVIDER,
            ],
            cwd=root,
            env=_environment(home),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.reader = threading.Thread(target=self._pump, daemon=True)
        self.reader.start()
        self.next_id = 0

    def _pump(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict):
                self.messages.put(message)

    def notify(self, method: str) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps({"method": method}) + "\n")
        self.process.stdin.flush()

    def request(self, method: str, params: Mapping[str, Any], timeout: float = 30.0) -> Any:
        self.next_id += 1
        assert self.process.stdin is not None
        self.process.stdin.write(
            json.dumps({"id": self.next_id, "method": method, "params": dict(params)}) + "\n"
        )
        self.process.stdin.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=max(deadline - time.monotonic(), 0.01))
            except queue.Empty:
                break
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise SystemExit(f"{method} failed: {message['error']}")
                return message.get("result")
        raise SystemExit(f"{method}: no answer within {timeout} s")

    def close(self) -> None:
        """End of input stops the server (and the MCP servers it started); kill if it hangs."""

        assert self.process.stdin is not None
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)


def run_codex(root: Path, home: Path) -> dict[str, Any]:
    binary = _binary()
    version = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    server = AppServer(binary, root, home)
    try:
        server.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "mission-control-fixture",
                    "title": "fixture",
                    "version": "0",
                },
                "capabilities": {"experimentalApi": False},
            },
        )
        server.notify("initialized")
        server.request(
            "thread/start",
            {
                "cwd": str(root),
                "model": "fixture-model",
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "ephemeral": True,
            },
        )
        answers = {
            key: server.request(
                method, {"cwd": str(root)} if method == "config/read" else {"cwds": [str(root)]}
            )
            for key, method in REQUESTS
        }
    finally:
        server.close()
    return {"cli_version": version, **answers}


def _placeholders(value: Any, replacements: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        for real, placeholder in replacements.items():
            value = value.replace(real, placeholder)
        return value
    if isinstance(value, list):
        return [_placeholders(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            _placeholders(key, replacements): _placeholders(item, replacements)
            for key, item in value.items()
        }
    return value


def _kept(run: Mapping[str, Any]) -> dict[str, Any]:
    """The answers without the host user's own skills and with only the MCP slice of the
    effective config (the rest is the CLI's defaults and the session flags)."""

    skills = {
        "data": [
            {
                **item,
                "skills": [
                    skill for skill in item.get("skills") or () if skill.get("scope") in KEPT_SCOPES
                ],
            }
            for item in run["skills_list"].get("data") or ()
        ]
    }
    config = run["config_read"]
    return {
        "skills_list": skills,
        "hooks_list": run["hooks_list"],
        "config_read": {
            "config": {"mcp_servers": (config.get("config") or {}).get("mcp_servers")},
            "origins": {
                key: origin
                for key, origin in (config.get("origins") or {}).items()
                if key.startswith("mcp_servers.")
            },
        },
    }


def summarize(
    run: dict[str, Any],
    projection: HostProjection,
    materialization: ProjectionMaterialization,
    repository_unchanged: bool,
    *,
    root: Path,
    home: Path,
) -> dict[str, Any]:
    replacements = {
        str(home): CODEX_HOME,
        str(root): WORKSPACE,
        home.as_posix(): CODEX_HOME,
        root.as_posix(): WORKSPACE,
    }
    return {
        "schema_version": "mc.discovery_recording.v1",
        "fixture": True,
        "evidence": "local_cli_discovery",
        "lane_profile": PROFILE.value,
        "provider_call": (
            "none: no login in the scratch CODEX_HOME, model provider http://127.0.0.1:9 "
            "(closed loopback port), no turn started; the process is stopped after config/read"
        ),
        "cli": {"binary": "codex", "version": run["cli_version"]},
        "host": {"os": platform.system(), "python": platform.python_version()},
        "requests": [
            "initialize",
            "thread/start {cwd}",
            *(
                f"{method} {{{'cwd' if method == 'config/read' else 'cwds'}}}"
                for _key, method in REQUESTS
            ),
        ],
        "projection_digest": projection_digest(projection),
        "projected_paths": list(projection.paths()),
        "answers": _placeholders(_kept(run), replacements),
        "repository": {
            "paths": sorted(REPOSITORY),
            "byte_identical_after_restore": repository_unchanged,
        },
        "layering": (
            None
            if materialization.layering is None
            else materialization.layering.model_dump(mode="json")
        ),
        "placed": {item.path: item.digest for item in materialization.files},
        "recorded_on": time.strftime("%Y-%m-%d"),
    }


def main() -> None:
    projection = project()
    # A child the server started may still hold its home briefly on Windows.
    with tempfile.TemporaryDirectory(
        prefix="mc-codex-discovery-", ignore_cleanup_errors=True
    ) as scratch:
        root = Path(scratch) / "workspace"
        root.mkdir()
        write_repository_files(root, REPOSITORY)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        materialization = materialize(projection, root)
        home = codex_home(projection, root)
        run = run_codex(root, home)
        restore_repository_files(root)
        unchanged = repository_bytes(root, REPOSITORY) == REPOSITORY
        document = summarize(run, projection, materialization, unchanged, root=root, home=home)
    RECORDING.write_bytes((json.dumps(document, indent=2, sort_keys=True) + "\n").encode())
    json.dump(document["answers"]["config_read"]["config"], sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
