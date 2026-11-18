"""MO-08: the worker-host preflight for the local `claude_agent_sdk` and `codex` lanes.

Host facts and tools are injected (a fake `ToolProbe` answering the exact argv the checks run);
auth goes through the worker's real `compose_auth_admission` over the committed example
registry with a recorded status reading, so a lane passes exactly when its launch would be
admitted. The live run on the owner's WSL2 worker is recorded in the MO-08 handoff.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath

import pytest

import mission_control
from mission_control.adapters.claude.describe import CLAUDE_BUNDLED_CLI_VERSION
from mission_control.adapters.codex.protocol import PINNED_CODEX_CLI_VERSION
from mission_control.adapters.provider_auth.status import StatusOutput
from mission_control.adapters.temporal.provider_lane_composition import (
    DEFAULT_LANE_WORKSPACE_ROOT,
)
from mission_control.bootstrap import host_preflight, preflight
from mission_control.bootstrap.host_preflight import (
    AuthSource,
    SubprocessToolProbe,
    WorkerHost,
    assess_worker_host,
    lease_root,
    on_windows_mount,
    worker_auth,
    wsl_automount_root,
)
from mission_control.bootstrap.preflight import (
    HOST_LANES,
    PreflightIssue,
    ReadinessReport,
)
from mission_control.bootstrap.provider_auth import compose_auth_admission
from mission_control.bootstrap.settings import Settings, get_settings

ROOT = Path(__file__).resolve().parents[3]
AUTH_EXAMPLE = ROOT / "deployments" / "examples" / "provider-auth-profiles.example.json"
PROFILES = {"claude_agent_sdk": "claude-sdk-api", "codex": "codex-owner-chatgpt"}
SECRET = "sk-ant-api03-" + "q" * 40

HOME = "/home/owner"
CHECKOUT = "/mnt/c/Users/Owner/BellLabs/platform/mission-control"
NODE_BIN = f"{HOME}/.nvm/versions/node/v24.18.0/bin"
NODE_LTS = (f"{NODE_BIN}/node", "-p", "process.release.lts || ''")
BUNDLED = (
    f"{HOME}/.venvs/mission-control/lib/python3.12/site-packages/claude_agent_sdk/_bundled/claude"
)
WSL = WorkerHost(
    system="Linux",
    release="6.18.40.1-microsoft-standard-WSL2",
    python=(3, 12, 11),
    project_root=CHECKOUT,
    source_root=f"{CHECKOUT}/src",
    venv=f"{HOME}/.venvs/mission-control",
    home=HOME,
    environ={
        "PATH": f"{HOME}/.local/bin:{NODE_BIN}:/usr/bin:/mnt/c/Program Files/nodejs",
        "HOME": HOME,
        "ANTHROPIC_API_KEY": SECRET,
    },
    bundled_claude=BUNDLED,
)


def ok(stdout: str = "", stderr: str = "", exit_code: int = 0) -> StatusOutput:
    return StatusOutput(exit_code=exit_code, stdout=stdout, stderr=stderr)


@dataclass
class FakeTools:
    """Answers only the argv the preflight is expected to run; anything else cannot run."""

    paths: dict[str, str] = field(
        default_factory=lambda: {
            "uv": f"{HOME}/.local/bin/uv",
            "node": f"{NODE_BIN}/node",
            "git": "/usr/bin/git",
            "claude": f"{HOME}/.local/bin/claude",
            "codex": f"{NODE_BIN}/codex",
        }
    )
    outputs: dict[tuple[str, ...], StatusOutput] = field(
        default_factory=lambda: {
            (f"{HOME}/.local/bin/uv", "--version"): ok("uv 0.12.23 (46b84fd0b 2026-10-03)"),
            (f"{HOME}/.local/bin/uv", "lock", "--check", "--offline", "--project", CHECKOUT): ok(
                stderr="Resolved 292 packages in 8ms"
            ),
            (f"{NODE_BIN}/node", "--version"): ok("v24.18.0"),
            NODE_LTS: ok("Krypton\n"),
            ("/usr/bin/git", "--version"): ok("git version 2.34.1"),
            (f"{HOME}/.local/bin/claude", "--version"): ok("2.1.296 (Claude Code)"),
            (BUNDLED, "--version"): ok(f"{CLAUDE_BUNDLED_CLI_VERSION} (Claude Code)"),
            (f"{NODE_BIN}/codex", "--version"): ok(f"codex-cli {PINNED_CODEX_CLI_VERSION}"),
        }
    )
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def which(self, name: str) -> str | None:
        return self.paths.get(name)

    async def run(self, argv: Sequence[str]) -> StatusOutput | None:
        self.calls.append(tuple(argv))
        return self.outputs.get(tuple(argv))


@dataclass
class RecordedStatus:
    """The read-only vendor status commands, answered from recorded phrases."""

    replies: Mapping[tuple[str, ...], StatusOutput]
    calls: list[tuple[str, ...]] = field(default_factory=list)

    async def run(self, argv: Sequence[str]) -> StatusOutput | None:
        self.calls.append(tuple(argv))
        return self.replies.get(tuple(argv))


SIGNED_IN = {("codex", "login", "status"): ok(stderr="Logged in using ChatGPT")}


def settings(**update: object) -> Settings:
    base = {
        "mission_control_claude_lease_root": Path(f"{HOME}/mc-leases/claude"),
        "mission_control_codex_lease_root": Path(f"{HOME}/mc-leases/codex"),
        "mission_control_codex_binary": "codex",
        "mission_control_codex_home_mode": "owner",
        "mission_control_codex_owner_home": Path(f"{HOME}/.codex"),
        "mission_control_codex_allow_version_mismatch": False,
        "mission_control_auth_profiles_path": AUTH_EXAMPLE,
        "deep_agent_sandbox_workspace_root": None,
    }
    return get_settings().model_copy(update={**base, **update})


def admission(
    host: WorkerHost, configured: Settings, replies: Mapping[tuple[str, ...], StatusOutput]
) -> AuthSource:
    composed = compose_auth_admission(
        configured,
        environ=host.environ,
        status_runner=RecordedStatus(replies),
        home=PurePosixPath(host.home),
        platform="linux",
        project_root=PurePosixPath(host.project_root),
    )
    assert composed is not None
    return composed


async def assess(
    host: WorkerHost = WSL,
    tools: FakeTools | None = None,
    configured: Settings | None = None,
    *,
    replies: Mapping[tuple[str, ...], StatusOutput] = SIGNED_IN,
    auth: AuthSource | None = None,
    profiles: Mapping[str, str] = PROFILES,
    checkpoint: str = "origin/main",
) -> ReadinessReport:
    configured = configured or settings()
    return await assess_worker_host(
        HOST_LANES,
        host,
        configured,
        tools=tools or FakeTools(),
        auth=auth if auth is not None else admission(host, configured, replies),
        auth_profile_ids=profiles,
        checkpoint=checkpoint,
    )


def blocking(report: ReadinessReport) -> list[tuple[str, str]]:
    return [(item.code, item.pointer) for item in report.issues if item.severity == "blocking"]


async def test_a_wsl2_worker_with_the_pinned_toolchain_passes_for_both_lanes() -> None:
    tools = FakeTools()
    report = await assess(tools=tools)

    assert report.ready, blocking(report)
    assert set(report.checks.values()) == {"passed"}
    assert set(report.checks) == {
        "host_os",
        "python",
        "toolchain",
        "same_tree",
        *(f"{lane}.{part}" for lane in HOST_LANES for part in ("cli", "lease_root", "auth")),
    }
    assert [item.code for item in report.issues] == ["WINDOWS_PATH_APPENDED"]
    assert report.host["wsl"] is True
    assert report.host["same_tree"] == "windows_checkout"
    assert report.host["codex"] == PINNED_CODEX_CLI_VERSION
    assert report.host["claude_bundled"] == CLAUDE_BUNDLED_CLI_VERSION
    assert report.host["claude_agent_sdk.lease_root"] == f"{HOME}/mc-leases/claude"
    assert report.host["claude_agent_sdk.auth"] == "claude-sdk-api (api_key, api)"
    assert report.host["codex.auth"] == "codex-owner-chatgpt (owner_cli_login, subscription)"
    assert report.host["node_lts"] == "Krypton"
    # Read-only commands only: versions, Node's release line and the offline lock check.
    assert all(
        call[1:] == ("--version",) or call == NODE_LTS or call[1:3] == ("lock", "--check")
        for call in tools.calls
    )
    assert SECRET not in report.model_dump_json()


async def test_a_windows_worker_refuses_both_lanes() -> None:
    report = await assess(replace(WSL, system="Windows", release="11"))

    refused = [item for item in report.issues if item.code == "LANE_UNSUPPORTED_OS"]
    assert [item.message.split(" ")[0] for item in refused] == list(HOST_LANES)
    assert {item.expected for item in refused} == {"Darwin | Linux"}
    assert report.checks["host_os"] == "failed"
    assert report.host["wsl"] is False


async def test_windows_shims_leaking_through_mnt_c_are_refused() -> None:
    tools = FakeTools()
    tools.paths.update(
        codex="/mnt/c/Users/Owner/AppData/Roaming/npm/codex",
        node="/mnt/c/Program Files/nodejs/node",
    )
    del tools.paths["claude"]

    report = await assess(tools=tools)

    assert ("TOOL_WINDOWS_SHIM", "env:MISSION_CONTROL_CODEX_BINARY") in blocking(report)
    assert ("TOOL_WINDOWS_SHIM", "host#/path/node") in blocking(report)
    assert ("TOOL_MISSING", "host#/path/claude") in blocking(report)
    shim = next(item for item in report.issues if item.pointer.endswith("CODEX_BINARY"))
    assert shim.observed == "/mnt/c/Users/Owner/AppData/Roaming/npm/codex"
    # A shim is never executed.
    assert not any(call[0].startswith("/mnt/") for call in tools.calls)


async def test_an_old_uv_python_or_a_non_lts_node_is_refused() -> None:
    tools = FakeTools()
    lock_check = (f"{HOME}/.local/bin/uv", "lock", "--check", "--offline", "--project", CHECKOUT)
    tools.outputs[lock_check] = ok(stderr="error: unsupported lockfile revision", exit_code=2)
    tools.outputs[(f"{NODE_BIN}/node", "--version")] = ok("v23.11.0")
    tools.outputs[NODE_LTS] = ok("\n")

    report = await assess(replace(WSL, python=(3, 10, 12)), tools)

    codes = {code for code, _pointer in blocking(report)}
    assert {"UV_LOCK_INCOMPATIBLE", "NODE_NOT_LTS", "PYTHON_UNSUPPORTED"} <= codes
    lock = next(item for item in report.issues if item.code == "UV_LOCK_INCOMPATIBLE")
    assert lock.observed == "error: unsupported lockfile revision"
    assert report.checks["toolchain"] == "failed" and report.checks["python"] == "failed"


@pytest.mark.parametrize(
    ("version", "lts", "ready"),
    [
        ("v26.0.0", "", False),  # an even major that is still Current, before its LTS promotion
        ("v20.19.5", "Iron", False),  # an LTS line past its end of life
        ("v22.21.0", "Jod", True),
    ],
)
async def test_node_is_judged_by_its_own_release_line(version: str, lts: str, ready: bool) -> None:
    tools = FakeTools()
    tools.outputs[(f"{NODE_BIN}/node", "--version")] = ok(version)
    tools.outputs[NODE_LTS] = ok(f"{lts}\n")

    report = await assess(tools=tools)

    assert (report.checks["toolchain"] == "passed") is ready
    assert ("NODE_NOT_LTS" in {code for code, _ in blocking(report)}) is not ready


async def test_codex_must_match_the_pin_unless_the_launcher_override_is_set() -> None:
    tools = FakeTools()
    tools.outputs[(f"{NODE_BIN}/codex", "--version")] = ok("codex-cli 9.9.9")

    refused = await assess(tools=tools)
    (pin,) = [item for item in refused.issues if item.code == "CODEX_PIN_MISMATCH"]
    assert (pin.expected, pin.observed, pin.severity) == (
        PINNED_CODEX_CLI_VERSION,
        "9.9.9",
        "blocking",
    )
    assert refused.checks["codex.cli"] == "failed"

    overridden = await assess(
        tools=tools, configured=settings(mission_control_codex_allow_version_mismatch=True)
    )
    assert overridden.ready
    assert "CODEX_PIN_OVERRIDDEN" in {item.code for item in overridden.issues}
    assert overridden.host["codex"] == "9.9.9"


async def test_the_configured_codex_binary_is_the_one_checked() -> None:
    tools = FakeTools()
    tools.paths[f"{HOME}/bin/codex-pinned"] = f"{HOME}/bin/codex-pinned"
    tools.outputs[(f"{HOME}/bin/codex-pinned", "--version")] = ok(
        f"codex-cli {PINNED_CODEX_CLI_VERSION}"
    )

    report = await assess(
        tools=tools, configured=settings(mission_control_codex_binary=f"{HOME}/bin/codex-pinned")
    )

    assert report.ready
    assert (f"{HOME}/bin/codex-pinned", "--version") in tools.calls


async def test_the_sdk_bundled_claude_code_must_be_the_pinned_linux_build() -> None:
    tools = FakeTools()
    tools.outputs[(BUNDLED, "--version")] = ok("2.0.1 (Claude Code)")
    mismatched = await assess(tools=tools)
    (issue,) = [item for item in mismatched.issues if item.code == "CLAUDE_BUNDLED_CLI_MISMATCH"]
    assert (issue.expected, issue.observed) == (CLAUDE_BUNDLED_CLI_VERSION, "2.0.1")

    absent = await assess(replace(WSL, bundled_claude=None))
    assert ("CLAUDE_BUNDLED_CLI_MISMATCH", "host#/venv/claude_agent_sdk/_bundled") in blocking(
        absent
    )


async def test_lease_roots_live_on_the_linux_filesystem_outside_provider_worktrees() -> None:
    defaulted = settings(
        mission_control_claude_lease_root=None, mission_control_codex_lease_root=None
    )
    # The worker's own composition: <PROJECT_ROOT>/.workspaces, which is /mnt/c/... in WSL.
    assert (
        lease_root("codex", defaulted) == (DEFAULT_LANE_WORKSPACE_ROOT / "codex-leases").as_posix()
    )
    on_windows = await assess(
        configured=defaulted.model_copy(
            update={"deep_agent_sandbox_workspace_root": Path(f"{CHECKOUT}/.workspaces")}
        )
    )
    assert ("LEASE_ROOT_ON_WINDOWS_FS", "env:MISSION_CONTROL_CLAUDE_LEASE_ROOT") in blocking(
        on_windows
    )
    assert ("LEASE_ROOT_ON_WINDOWS_FS", "env:MISSION_CONTROL_CODEX_LEASE_ROOT") in blocking(
        on_windows
    )

    provider_owned = await assess(
        replace(WSL, environ={**WSL.environ, "CODEX_HOME": f"{HOME}/codex-home"}),
        configured=settings(
            mission_control_claude_lease_root=Path(f"{HOME}/.cursor/worktrees/mc"),
            mission_control_codex_lease_root=Path(f"{HOME}/codex-home/worktrees"),
        ),
    )
    assert [code for code, _ in blocking(provider_owned)] == ["LEASE_ROOT_PROVIDER_OWNED"] * 2

    sandbox_root = settings(
        mission_control_codex_lease_root=None,
        deep_agent_sandbox_workspace_root=Path(f"{HOME}/mc-workspaces"),
    )
    assert lease_root("codex", sandbox_root) == f"{HOME}/mc-workspaces/codex-leases"


async def test_the_same_tree_rule_needs_this_checkouts_code_in_a_linux_venv() -> None:
    windows_venv = await assess(replace(WSL, venv=f"{CHECKOUT}/.venv"))
    assert blocking(windows_venv) == [("VENV_ON_WINDOWS_FS", "host#/venv")]

    # The shared venv is an editable install of another worktree: its code is not this tree's.
    other = "/mnt/c/Users/Owner/BellLabs/platform/.worktrees/other/src"
    other_tree = await assess(replace(WSL, source_root=other))
    assert blocking(other_tree) == [("VENV_OTHER_TREE", "host#/source_root")]
    (issue,) = [item for item in other_tree.issues if item.code == "VENV_OTHER_TREE"]
    assert (issue.expected, issue.observed) == (f"{CHECKOUT}/src", other)
    assert other_tree.checks["same_tree"] == "failed"


CLONE = replace(
    WSL, project_root=f"{HOME}/mission-control", source_root=f"{HOME}/mission-control/src"
)
GIT = "/usr/bin/git"
CHECKPOINT = "146c9eb0"


def clone_tools(head: str = CHECKPOINT, status: str = "") -> FakeTools:
    tools = FakeTools()
    root = CLONE.project_root
    rev_parse = (GIT, "-C", root, "rev-parse", "--verify", "--quiet")
    tools.outputs.update(
        {
            (f"{HOME}/.local/bin/uv", "lock", "--check", "--offline", "--project", root): ok(),
            (*rev_parse, "HEAD^{commit}"): ok(f"{head}\n"),
            (*rev_parse, "origin/main^{commit}"): ok(f"{CHECKPOINT}\n"),
            (GIT, "-C", root, "status", "--porcelain"): ok(status),
        }
    )
    return tools


async def test_a_clone_is_a_clean_checkout_of_the_checkpoint_commit() -> None:
    clean = await assess(CLONE, clone_tools())
    assert clean.ready, blocking(clean)
    assert (clean.host["same_tree"], clean.host["checkout_commit"]) == ("clone", CHECKPOINT)
    assert clean.host["checkpoint"] == f"origin/main {CHECKPOINT}"

    dirty = await assess(CLONE, clone_tools(status="?? src/mission_control/patch.py\n"))
    assert blocking(dirty) == [("CLONE_NOT_CHECKPOINT", "host#/project_root")]

    behind = await assess(CLONE, clone_tools(head="0ddba11"))
    (issue,) = [item for item in behind.issues if item.code == "CLONE_NOT_CHECKPOINT"]
    assert (issue.expected, issue.observed) == (CHECKPOINT, "0ddba11")

    unfetched = await assess(CLONE, clone_tools(), checkpoint="origin/release")
    (issue,) = [item for item in unfetched.issues if item.code == "CLONE_NOT_CHECKPOINT"]
    assert issue.expected is None and "origin/release" in issue.message

    windows_venv = await assess(replace(CLONE, venv="/mnt/c/venvs/mc"), clone_tools())
    assert blocking(windows_venv) == [("VENV_ON_WINDOWS_FS", "host#/venv")]


async def test_a_finding_shared_by_several_checks_is_reported_once() -> None:
    tools = clone_tools()
    del tools.paths["git"]
    missing = worker_auth(settings(mission_control_auth_profiles_path=None), CLONE, None)

    report = await assess(CLONE, tools, auth=missing)

    assert [code for code, _ in blocking(report)] == ["TOOL_MISSING", "AUTH_PROFILES_MISSING"]
    assert report.checks["toolchain"] == report.checks["same_tree"] == "failed"
    assert report.checks["claude_agent_sdk.auth"] == report.checks["codex.auth"] == "failed"


async def test_auth_per_lane_is_the_launch_admission_without_reading_values() -> None:
    signed_out = {("codex", "login", "status"): ok(stderr="Not logged in", exit_code=1)}
    no_key = replace(
        WSL, environ={key: v for key, v in WSL.environ.items() if key != "ANTHROPIC_API_KEY"}
    )

    report = await assess(no_key, replies=signed_out)

    assert ("AUTH_CREDENTIAL_MISSING", "auth-profile:claude-sdk-api#/auth") in blocking(report)
    assert ("AUTH_NOT_SIGNED_IN", "auth-profile:codex-owner-chatgpt#/auth") in blocking(report)
    assert report.checks["claude_agent_sdk.auth"] == "failed"
    assert report.checks["codex.auth"] == "failed"

    shadowed = await assess(replace(WSL, environ={**WSL.environ, "OPENAI_API_KEY": SECRET}))
    assert ("AUTH_ROUTE_SHADOWED", "auth-profile:codex-owner-chatgpt#/auth") in blocking(shadowed)
    assert SECRET not in shadowed.model_dump_json()


async def test_a_lane_without_a_profile_or_a_registry_is_refused(tmp_path: Path) -> None:
    unselected = await assess(profiles={"claude_agent_sdk": "claude-sdk-api"})
    assert ("AUTH_PROFILE_MISSING", "auth-profile:-#/auth/profile") in blocking(unselected)

    missing = worker_auth(settings(mission_control_auth_profiles_path=None), WSL, None)
    assert isinstance(missing, PreflightIssue) and missing.code == "AUTH_PROFILES_MISSING"

    broken = tmp_path / "auth.json"
    broken.write_text('{"profiles": "none"}', encoding="utf-8")
    invalid = worker_auth(settings(), WSL, broken)
    assert isinstance(invalid, PreflightIssue) and invalid.code == "AUTH_PROFILES_INVALID"


def test_windows_mount_paths_are_recognised() -> None:
    assert on_windows_mount("/mnt/c/Users/Owner")
    assert on_windows_mount("/mnt/D")
    assert not on_windows_mount("/mnt/wsl/docker")
    assert not on_windows_mount("/home/owner/mnt/c")
    assert on_windows_mount("/win/c/Users", "/win/")
    assert not on_windows_mount("/mnt/c/Users", "/win/")
    assert on_windows_mount("/c/Users", "/")


def test_the_automount_root_comes_from_wsl_conf(tmp_path: Path) -> None:
    conf = tmp_path / "wsl.conf"
    assert wsl_automount_root(conf) == "/mnt"
    conf.write_text("[interop]\nappendWindowsPath=false\n", encoding="utf-8")
    assert wsl_automount_root(conf) == "/mnt"
    conf.write_text('[automount]\nenabled = true\nroot = "/win/"  # drives\n', encoding="utf-8")
    assert wsl_automount_root(conf) == "/win/"


async def test_a_custom_automount_root_still_catches_windows_shims_and_lease_roots() -> None:
    tools = FakeTools()
    tools.paths["codex"] = "/win/c/Users/Owner/AppData/Roaming/npm/codex"

    report = await assess(
        replace(WSL, mount_root="/win"),
        tools,
        settings(mission_control_claude_lease_root=Path("/win/c/leases/claude")),
    )

    assert ("TOOL_WINDOWS_SHIM", "env:MISSION_CONTROL_CODEX_BINARY") in blocking(report)
    assert ("LEASE_ROOT_ON_WINDOWS_FS", "env:MISSION_CONTROL_CLAUDE_LEASE_ROOT") in blocking(report)


def test_the_live_host_reports_the_tree_mission_control_is_imported_from() -> None:
    package = Path(mission_control.__file__).resolve().parent
    assert WorkerHost.current({}).source_root == package.parent.as_posix()


async def test_the_subprocess_probe_resolves_and_runs_argv_only() -> None:
    interpreter = Path(sys.executable)
    tools = SubprocessToolProbe({"PATH": str(interpreter.parent)})
    resolved = tools.which(interpreter.stem)
    assert resolved is not None and Path(resolved) == interpreter
    output = await tools.run((interpreter.as_posix(), "--version"))
    assert output is not None and output.exit_code == 0
    assert "Python 3.12" in output.stdout + output.stderr
    assert await tools.run(("mission-control-no-such-binary", "--version")) is None


async def test_the_preflight_cli_runs_the_host_check_for_the_selected_lanes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    async def fake(lanes: Sequence[str], _settings: Settings, **kwargs: object) -> ReadinessReport:
        seen.update(lanes=tuple(lanes), **kwargs)
        return ReadinessReport(host={}, checks={"host_os": "passed"}, issues=())

    monkeypatch.setattr(host_preflight, "worker_host_readiness", fake)
    code = await preflight.main(
        ["host", "--lane", "codex", "--auth-profile", "codex=codex-owner-chatgpt"]
    )
    assert code == 0
    assert seen == {
        "lanes": ("codex",),
        "auth_profile_ids": {"codex": "codex-owner-chatgpt"},
        "auth_profiles": None,
        "checkpoint": "origin/main",
    }
    await preflight.main(["host", "--checkpoint", "146c9eb"])
    assert seen["checkpoint"] == "146c9eb"
    with pytest.raises(SystemExit):
        preflight.build_parser().parse_args(["host", "--auth-profile", "cursor_local=x"])
