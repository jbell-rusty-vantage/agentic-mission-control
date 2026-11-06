"""Record what the real Claude Code CLI discovers from a claude_agent_sdk Host Projection.

``uv run --frozen python -m tests.fixtures.projections.discovery.claude_cli`` renders
``discovery_rows()`` for ``claude_agent_sdk`` and layers it (MO-02) over a scratch git
repository that already owns its cognition: an ``AGENTS.md``, a ``.claude/skills`` skill, a
``.cursor/hooks.json`` and a ``.claude/settings.json`` whose own ``SessionStart`` and
``InstructionsLoaded`` hooks write markers. It then runs the locally installed ``claude`` binary
in print mode with ``--setting-sources project``, the mission overlay as
``--append-system-prompt`` (what the SDK's ``claude_code`` preset ``append`` sends) and
stream-json output. The run never reaches a model: the config directory is a fresh scratch
directory (no owner credentials or settings), the API key is a placeholder and
``ANTHROPIC_BASE_URL`` points at a closed loopback port, so the only provider-side effect is a
refused local TCP connection. The CLI emits its ``system``/``init`` message (tools, MCP server
status, agents, skills) and fires ``SessionStart`` hooks before that first request; the recorder
keeps those, stops the process, restores the repository files layering merged, checks they are
byte-identical, and writes ``claude_agent_sdk.recorded.json``.

The recording is a FIXTURE of local discovery by one exact CLI build. It proves that the
projected files load in that build; it does not qualify the lane, prove hosted behaviour or
exercise a model turn.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from hashlib import sha256
from pathlib import Path

from tests.fixtures.layering_repo import REPO_FILES, repository_bytes, write_repository_files
from tests.fixtures.projections.rows import _entry, _mcp, _pin, skill_row

from mission_control.application.agentic_components.layering import restore_repository_files
from mission_control.application.agentic_components.materialization import (
    ProjectionMaterialization,
    materialize_projection,
    projection_digest,
    required_executables,
)
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.agentic_components.projection import (
    BundleFile,
    HostProjection,
    ResolvedCapability,
)
from mission_control.domain.authoring.contracts import (
    HookScriptDefinition,
    SubagentProfileDefinition,
)
from mission_control.domain.capabilities.host_support import LaneProfile, all_profiles

HERE = Path(__file__).resolve().parent
RECORDING = HERE / "claude_agent_sdk.recorded.json"
STUB_TARGET = ".mission/discovery/mcp_stub.py"
MARKER_DIR = ".mission/discovery"
INSTRUCTION = "Discovery fixture. Do not act."
PROFILE = LaneProfile.CLAUDE_AGENT_SDK

MARKER_SCRIPT = (
    b"import json\n"
    b"import pathlib\n"
    b"import sys\n\n"
    b"payload = json.loads(sys.stdin.read() or '{}')\n"
    b"event = payload.get('event', 'unknown')\n"
    b"root = pathlib.Path(payload.get('workspace_root') or '.')\n"
    b"marker = root / '.mission' / 'discovery' / f'fired-{event}.json'\n"
    b"marker.parent.mkdir(parents=True, exist_ok=True)\n"
    b"marker.write_text(json.dumps({'event': event, 'lane': payload.get('lane_profile')}))\n"
    b'print(json.dumps({"schema_version": "mc.hook_result.v1", "decision": "allow"}))\n'
)
MARKER_FILES = (BundleFile(path="marker.py", content=MARKER_SCRIPT),)

# The repository's own hooks: a marker per event, naming the instruction file Claude loaded.
REPO_MARKER_SCRIPT = (
    b"import json\n"
    b"import pathlib\n"
    b"import sys\n\n"
    b"event = sys.argv[1]\n"
    b"payload = json.loads(sys.stdin.read() or '{}')\n"
    b"loaded = payload.get('file_path')\n"
    b"name = pathlib.Path(loaded).name if loaded else None\n"
    b"suffix = f'-{name}' if name else ''\n"
    b"marker = pathlib.Path('.mission') / 'discovery' / f'fired-repo-{event}{suffix}.json'\n"
    b"marker.parent.mkdir(parents=True, exist_ok=True)\n"
    b"marker.write_text(json.dumps({'event': event, 'file': name}))\n"
)


def _repo_hook(event: str) -> list[dict[str, object]]:
    command = {"type": "command", "command": "python", "args": [".repo-hooks/marker.py", event]}
    return [{"hooks": [command]}]


REPOSITORY: dict[str, bytes] = {
    **{path: REPO_FILES[path] for path in ("AGENTS.md", ".claude/skills/repo-notes/SKILL.md")},
    ".cursor/hooks.json": REPO_FILES[".cursor/hooks.json"],
    ".claude/settings.json": (
        json.dumps(
            {
                "hooks": {
                    "SessionStart": _repo_hook("session_start"),
                    "InstructionsLoaded": _repo_hook("instructions_loaded"),
                }
            },
            indent=2,
        )
        + "\n"
    ).encode("utf-8"),
    ".repo-hooks/marker.py": REPO_MARKER_SCRIPT,
}


def discovery_mcp_row() -> ResolvedCapability:
    definition = _mcp(
        "mcp.discovery-stub",
        transport="stdio",
        launch_template=["python", STUB_TARGET],
        tools=[{"name": "discovery_echo"}],
        host_support=all_profiles().model_dump(mode="json"),
    )
    return ResolvedCapability(
        pin=_pin("mcp.discovery-stub", "1.0.0", "discovery-stub"), definition=definition
    )


def discovery_hook_row() -> ResolvedCapability:
    definition = HookScriptDefinition.model_validate(
        {
            "logical_id": "hook.discovery-marker",
            "title": "Discovery marker",
            "description": "Writes a marker file when a projected hook fires (fixture).",
            "events": ["session_start"],
            "timeout_seconds": 20,
            "file_manifest": [_entry(item) for item in MARKER_FILES],
            "manifest_digest": "sha256:" + sha256(b"discovery-marker").hexdigest(),
            "entrypoint": "marker.py",
            "interpreter": "python",
            "host_support": all_profiles().model_dump(mode="json"),
        }
    )
    return ResolvedCapability(
        pin=_pin("hook.discovery-marker", "1.0.0", "discovery-marker"),
        definition=definition,
        files=MARKER_FILES,
    )


def discovery_agent_row() -> ResolvedCapability:
    definition = SubagentProfileDefinition.model_validate(
        {
            "logical_id": "subagent.discovery-reviewer",
            "title": "Discovery reviewer",
            "description": "Fixture subagent.",
            "profile": {
                "name": "discovery-reviewer",
                "description": "Reviews discovery output. Fixture only.",
                "prompt": "You review fixture output.",
                "readonly": True,
                "skills": ["agent-browser"],
                "mcp_servers": ["mcp.discovery-stub"],
            },
            "host_support": all_profiles().model_dump(mode="json"),
        }
    )
    return ResolvedCapability(
        pin=_pin("subagent.discovery-reviewer", "1.0.0", "discovery-reviewer"),
        definition=definition,
    )


def discovery_rows() -> tuple[ResolvedCapability, ...]:
    return (skill_row(), discovery_mcp_row(), discovery_hook_row(), discovery_agent_row())


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


def overlay(projection: HostProjection) -> str:
    system_prompt = projection.send_options["system_prompt"]
    assert isinstance(system_prompt, dict)
    return str(system_prompt["append"])


def _isolated_env(config_dir: Path) -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "COMSPEC", "PATHEXT", "LANG")
    env = {name: os.environ[name] for name in keep if name in os.environ}
    env.update(
        CLAUDE_CONFIG_DIR=str(config_dir),
        HOME=str(config_dir),
        USERPROFILE=str(config_dir),
        ANTHROPIC_API_KEY="placeholder-not-a-credential",
        ANTHROPIC_BASE_URL="http://127.0.0.1:9",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
        DISABLE_AUTOUPDATER="1",
        DISABLE_TELEMETRY="1",
    )
    return env


def run_claude(
    root: Path, config_dir: Path, append: str, *, timeout: float = 60.0
) -> dict[str, object]:
    command = [
        shutil.which("claude") or "claude",
        "-p",
        "Discovery fixture. Do not act.",
        "--output-format",
        "stream-json",
        "--verbose",
        "--setting-sources",
        "project",
        "--append-system-prompt",
        append,
        "--max-turns",
        "1",
    ]
    process = subprocess.Popen(
        command,
        cwd=root,
        env=_isolated_env(config_dir),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    events: list[dict[str, object]] = []
    init: dict[str, object] | None = None
    found = threading.Event()

    def pump() -> None:
        nonlocal init
        assert process.stdout is not None
        for raw in process.stdout:
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            events.append(message)
            if message.get("type") == "system" and message.get("subtype") == "init":
                init = message
                found.set()

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    found.wait(timeout)
    deadline = time.monotonic() + 10
    expected = (
        root / MARKER_DIR / "fired-session_start.json",
        root / MARKER_DIR / "fired-repo-session_start.json",
    )
    while time.monotonic() < deadline and not all(marker.exists() for marker in expected):
        time.sleep(0.25)
    process.kill()
    process.wait(timeout=10)
    reader.join(timeout=5)
    version = subprocess.run(
        [command[0], "--version"], capture_output=True, text=True, check=False
    ).stdout.strip()
    markers = sorted(path.name for path in (root / MARKER_DIR).glob("fired-*.json"))
    loaded = sorted(
        str(json.loads(path.read_text(encoding="utf-8")).get("file"))
        for path in (root / MARKER_DIR).glob("fired-repo-instructions_loaded*.json")
    )
    return {
        "cli_version": version,
        "init": init,
        "markers": markers,
        "instructions_loaded": loaded,
        "event_count": len(events),
    }


def summarize(
    run: dict[str, object],
    projection: HostProjection,
    materialization: ProjectionMaterialization,
    repository_unchanged: bool,
) -> dict[str, object]:
    init = run["init"]
    if not isinstance(init, dict):
        raise SystemExit("claude emitted no system/init message; nothing recorded")
    servers = init.get("mcp_servers") or []
    tools = [str(tool) for tool in init.get("tools") or []]
    return {
        "schema_version": "mc.discovery_recording.v1",
        "fixture": True,
        "evidence": "local_cli_discovery",
        "lane_profile": PROFILE.value,
        "provider_call": (
            "none: ANTHROPIC_BASE_URL=http://127.0.0.1:9 (closed loopback port), placeholder "
            "API key, fresh CLAUDE_CONFIG_DIR; the process is stopped after system/init"
        ),
        "cli": {"binary": "claude", "version": run["cli_version"]},
        "host": {"os": platform.system(), "python": platform.python_version()},
        "invocation": [
            "claude",
            "-p",
            "<prompt>",
            "--output-format",
            "stream-json",
            "--verbose",
            "--setting-sources",
            "project",
            "--append-system-prompt",
            "<mission overlay>",
            "--max-turns",
            "1",
        ],
        "projection_digest": projection_digest(projection),
        "projected_paths": list(projection.paths()),
        "discovered": {
            "skills": sorted(str(item) for item in init.get("skills") or []),
            "agents": sorted(str(item) for item in init.get("agents") or []),
            "mcp_servers": sorted(
                (
                    {"name": str(item.get("name")), "status": str(item.get("status"))}
                    for item in servers
                    if isinstance(item, dict)
                ),
                key=lambda item: item["name"],
            ),
            "mcp_tools": sorted(tool for tool in tools if tool.startswith("mcp__")),
            "slash_commands": sorted(str(item) for item in init.get("slash_commands") or []),
        },
        "hooks_fired": run["markers"],
        "instructions_loaded": run["instructions_loaded"],
        "repository": {
            "paths": sorted(REPOSITORY),
            "byte_identical_after_restore": repository_unchanged,
        },
        "layering": (
            None
            if materialization.layering is None
            else materialization.layering.model_dump(mode="json")
        ),
        "recorded_on": time.strftime("%Y-%m-%d"),
    }


def main() -> None:
    projection = project()
    with tempfile.TemporaryDirectory(prefix="mc-discovery-") as scratch:
        root = Path(scratch) / "workspace"
        config = Path(scratch) / "config"
        root.mkdir()
        config.mkdir()
        write_repository_files(root, REPOSITORY)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        materialization = materialize(projection, root)
        run = run_claude(root, config, overlay(projection))
        restore_repository_files(root)
        unchanged = repository_bytes(root, REPOSITORY) == REPOSITORY
        document = summarize(run, projection, materialization, unchanged)
    RECORDING.write_bytes((json.dumps(document, indent=2, sort_keys=True) + "\n").encode())
    json.dump(document["discovered"], sys.stdout, indent=2)
    sys.stdout.write(f"\nhooks fired: {document['hooks_fired']}\n")


if __name__ == "__main__":
    main()
