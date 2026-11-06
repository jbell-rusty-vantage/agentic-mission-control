"""Read-only preflight of a worker host for the local Claude and Codex lanes (MO-08).

``python -m mission_control.bootstrap.preflight host`` answers whether *this* host can serve
``claude_agent_sdk`` and ``codex``. Both refuse a Windows worker (``LANE_UNSUPPORTED_OS``), so
the owner's Windows machine runs them on a WSL2 worker (DECISIONS D5/R28, SPEC-09 §2 and §6).
The report is an ``mc.local_readiness.v1`` restricted to host facts. It checks:

* the operating system against each lane's host rule (``preflight.LANE_HOSTS``) and the
  interpreter against the worker's Python (3.12);
* the toolchain: ``uv`` can read ``uv.lock`` (``uv lock --check --offline``), Node is a
  maintained LTS release and ``git`` is present;
* every CLI the lanes spawn resolves to a Linux binary, never a Windows shim leaking in through
  a Windows drive mount (``/mnt/<drive>``, or the ``[automount] root`` of ``/etc/wsl.conf``)
  on ``PATH``; ``codex --version`` equals the launcher's pin (or its explicit override);
  ``claude`` answers on ``PATH`` and the SDK-bundled Claude Code is the pinned one;
* the same-tree rule: the running ``mission_control`` is imported from the checked tree, whose
  venv lives on the Linux filesystem; a ``/mnt`` checkout uses its own Linux venv
  (``UV_PROJECT_ENVIRONMENT``), and a clone is a clean checkout of the checkpoint commit;
* Workspace Lease roots, as the worker composes them, on the Linux filesystem and outside
  provider-owned worktree roots;
* auth per lane through the worker's own :class:`AuthAdmissionService` with the read-only
  status probe on, so a lane passes exactly when its launch would be admitted.

Every command is argv-only with the status-probe environment and a timeout. No login, no
model call; auth sees variable names, file existence and redacted status phrases only.
"""

from __future__ import annotations

import configparser
import importlib.util
import os
import platform
import re
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from mission_control.adapters.claude.describe import CLAUDE_BUNDLED_CLI_VERSION
from mission_control.adapters.codex.protocol import PINNED_CODEX_CLI_VERSION
from mission_control.adapters.provider_auth.preflight import SubprocessStatusRunner
from mission_control.adapters.provider_auth.redaction import redact_text
from mission_control.adapters.provider_auth.status import StatusOutput
from mission_control.adapters.temporal.provider_lane_composition import (
    claude_lease_root,
    codex_lease_root,
)
from mission_control.application.execution.auth_admission import (
    AuthAdmissionRejected,
    AuthAdmissionService,
)
from mission_control.bootstrap.preflight import (
    LANE_HOSTS,
    CheckState,
    HostLane,
    PreflightIssue,
    ReadinessReport,
)
from mission_control.bootstrap.provider_auth import (
    AuthProfilesUnavailable,
    compose_auth_admission,
    selected_auth_environment,
    status_probe_environment,
)
from mission_control.bootstrap.settings import PROJECT_ROOT, Settings

WORKER_PYTHON: Final = (3, 12)
# The oldest LTS line still maintained (nodejs.org previous-releases); older lines are EOL.
MIN_NODE_MAJOR: Final = 22
# DECISIONS R19: a worker clone runs the checkpoint commit on origin/main.
DEFAULT_CHECKPOINT: Final = "origin/main"
DEFAULT_MOUNT_ROOT: Final = "/mnt"
WSL_CONF: Final = Path("/etc/wsl.conf")
VENV_HINT: Final = "UV_PROJECT_ENVIRONMENT=$HOME/.venvs/mission-control"
INSTALL_HINT: Final = "scripts/wsl/install_worker_toolchain.sh"

_SEMVER: Final = re.compile(r"(\d+\.\d+\.\d+)")
_CODEX_VERSION: Final = re.compile(r"codex-cli\s+(\S+)")
_NODE_MAJOR: Final = re.compile(r"v(\d+)\.\d+\.\d+")
# `process.release.lts` is the LTS codename and is absent on Current releases (Node docs).
_NODE_LTS: Final = ("-p", "process.release.lts || ''")


def on_windows_mount(path: str, mount_root: str = DEFAULT_MOUNT_ROOT) -> bool:
    """A WSL path into a Windows drive (``<mount root>/c/...``): the Windows filesystem."""

    root = re.escape(mount_root.rstrip("/"))
    return re.match(rf"{root}/[A-Za-z](/|$)", path) is not None


def wsl_automount_root(conf: Path = WSL_CONF) -> str:
    """Where WSL mounts the Windows drives: ``[automount] root`` in ``/etc/wsl.conf``."""

    parser = configparser.ConfigParser(
        strict=False, interpolation=None, inline_comment_prefixes=("#", ";")
    )
    try:
        parser.read(conf, encoding="utf-8")  # a missing or unreadable file reads as empty
    except (configparser.Error, UnicodeDecodeError):
        return DEFAULT_MOUNT_ROOT
    root = parser.get("automount", "root", fallback="").strip().strip("\"'")
    return root or DEFAULT_MOUNT_ROOT


def _within(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def bundled_claude_cli() -> str | None:
    """Where the pinned SDK keeps its bundled Claude Code (``SubprocessCLITransport.
    _find_bundled_cli``, claude_agent_sdk 0.2.165: ``<package>/_bundled/claude[.exe]``)."""

    spec = importlib.util.find_spec("claude_agent_sdk")
    if spec is None or spec.origin is None:
        return None
    name = "claude.exe" if platform.system() == "Windows" else "claude"
    return (Path(spec.origin).parent / "_bundled" / name).as_posix()


@dataclass(frozen=True)
class WorkerHost:
    """The host facts the checks read; paths are POSIX strings (injectable for tests).
    `source_root` is the directory this process imports ``mission_control`` from."""

    system: str
    release: str
    python: tuple[int, int, int]
    project_root: str
    source_root: str
    venv: str
    home: str
    environ: Mapping[str, str]
    bundled_claude: str | None = None
    mount_root: str = DEFAULT_MOUNT_ROOT

    @property
    def wsl(self) -> bool:
        release = self.release.lower()
        return self.system == "Linux" and ("microsoft" in release or "wsl" in release)

    @property
    def codex_home(self) -> str:
        return self.environ.get("CODEX_HOME") or f"{self.home}/.codex"

    def on_windows_fs(self, path: str) -> bool:
        return on_windows_mount(path, self.mount_root)

    @classmethod
    def current(cls, environ: Mapping[str, str] | None = None) -> WorkerHost:
        major, minor, micro = sys.version_info[:3]
        system = platform.system()
        return cls(
            system=system,
            release=platform.release(),
            python=(major, minor, micro),
            project_root=PROJECT_ROOT.as_posix(),
            # <tree>/src/mission_control/bootstrap/host_preflight.py for a checkout or an
            # editable install; a regular install resolves into site-packages instead.
            source_root=Path(__file__).resolve().parents[2].as_posix(),
            venv=Path(sys.prefix).as_posix(),
            home=Path.home().as_posix(),
            environ=dict(environ if environ is not None else os.environ),
            bundled_claude=bundled_claude_cli(),
            mount_root=wsl_automount_root() if system == "Linux" else DEFAULT_MOUNT_ROOT,
        )


class ToolProbe(Protocol):
    """Resolves and runs host tools; `run` returns None when the command cannot run."""

    def which(self, name: str) -> str | None: ...

    async def run(self, argv: Sequence[str]) -> StatusOutput | None: ...


class SubprocessToolProbe:
    """Resolves on the worker's ``PATH`` and runs argv-only with the status-probe environment
    (``PATH``/``HOME``-class variables, no credential variables) and a hard timeout."""

    def __init__(self, environ: Mapping[str, str], *, timeout_s: float = 30.0) -> None:
        self._path = environ.get("PATH", "")
        self._runner = SubprocessStatusRunner(
            status_probe_environment(environ), timeout_s=timeout_s
        )

    def which(self, name: str) -> str | None:
        found = shutil.which(name, path=self._path)
        return Path(found).as_posix() if found is not None else None

    async def run(self, argv: Sequence[str]) -> StatusOutput | None:
        return await self._runner.run(argv)


def _resolve(
    host: WorkerHost, tools: ToolProbe, command: str, pointer: str, issues: list[PreflightIssue]
) -> str | None:
    """`command` resolved to a Linux binary, or None with the refusal recorded."""

    path = tools.which(command)
    if path is None:
        issues.append(
            PreflightIssue(
                code="TOOL_MISSING",
                pointer=pointer,
                message=f"{command} is not on PATH; install it with {INSTALL_HINT}",
            )
        )
        return None
    if host.on_windows_fs(path):
        issues.append(
            PreflightIssue(
                code="TOOL_WINDOWS_SHIM",
                pointer=pointer,
                message=(
                    f"{command} resolves to a Windows binary through the appended Windows PATH; "
                    f"install the Linux build ({INSTALL_HINT}) or set [interop] "
                    "appendWindowsPath=false in /etc/wsl.conf"
                ),
                observed=path,
            )
        )
        return None
    return path


async def _version(tools: ToolProbe, path: str, pattern: re.Pattern[str]) -> str | None:
    output = await tools.run((path, "--version"))
    if output is None or output.exit_code != 0:
        return None
    match = pattern.search(output.stdout + "\n" + output.stderr)
    return match.group(1) if match else None


async def _stdout(tools: ToolProbe, argv: Sequence[str]) -> str | None:
    output = await tools.run(argv)
    if output is None or output.exit_code != 0:
        return None
    return output.stdout.strip() or None


def _last_line(output: StatusOutput) -> str:
    lines = [line for line in (output.stderr + "\n" + output.stdout).splitlines() if line.strip()]
    return redact_text(lines[-1][:200]) if lines else f"exit {output.exit_code}"


# --- Host, toolchain and tree --------------------------------------------------------------


def check_os(lanes: Sequence[HostLane], host: WorkerHost) -> list[PreflightIssue]:
    return [
        PreflightIssue(
            code="LANE_UNSUPPORTED_OS",
            pointer="host#/system",
            message=f"{lane} cannot run on a {host.system} worker: {LANE_HOSTS[lane].reason}",
            expected=" | ".join(sorted(LANE_HOSTS[lane].systems)),
            observed=host.system,
        )
        for lane in lanes
        if host.system not in LANE_HOSTS[lane].systems
    ]


def check_python(host: WorkerHost) -> list[PreflightIssue]:
    if host.python[:2] == WORKER_PYTHON:
        return []
    return [
        PreflightIssue(
            code="PYTHON_UNSUPPORTED",
            pointer="host#/python",
            message=f"the worker venv runs Python 3.12 (`uv python install 3.12`; {VENV_HINT})",
            expected=".".join(map(str, WORKER_PYTHON)),
            observed=".".join(map(str, host.python)),
        )
    ]


async def check_toolchain(
    host: WorkerHost, tools: ToolProbe, facts: dict[str, str | bool]
) -> list[PreflightIssue]:
    issues: list[PreflightIssue] = []
    if (uv := _resolve(host, tools, "uv", "host#/path/uv", issues)) is not None:
        facts["uv"] = await _version(tools, uv, _SEMVER) or "unknown"
        argv = (uv, "lock", "--check", "--offline", "--project", host.project_root)
        locked = await tools.run(argv)
        if locked is None or locked.exit_code != 0:
            issues.append(
                PreflightIssue(
                    code="UV_LOCK_INCOMPATIBLE",
                    pointer="host#/path/uv",
                    message="this uv cannot validate uv.lock offline; run `uv self update`",
                    observed=_last_line(locked) if locked is not None else "did not run",
                )
            )
    if (node := _resolve(host, tools, "node", "host#/path/node", issues)) is not None:
        major = await _version(tools, node, _NODE_MAJOR)
        lts = await _stdout(tools, (node, *_NODE_LTS))
        facts["node_major"] = major or "unknown"
        facts["node_lts"] = lts or "none"
        if major is None or int(major) < MIN_NODE_MAJOR or lts is None:
            issues.append(
                PreflightIssue(
                    code="NODE_NOT_LTS",
                    pointer="host#/path/node",
                    message="Node must be a maintained LTS release (`nvm install --lts`)",
                    expected=f"an LTS release (process.release.lts), major >= {MIN_NODE_MAJOR}",
                    observed=f"{major or 'unknown'} (lts: {lts or 'none'})",
                )
            )
    if (git := _resolve(host, tools, "git", "host#/path/git", issues)) is not None:
        facts["git"] = await _version(tools, git, _SEMVER) or "unknown"
    if any(host.on_windows_fs(entry) for entry in host.environ.get("PATH", "").split(":")):
        issues.append(
            PreflightIssue(
                code="WINDOWS_PATH_APPENDED",
                pointer="host#/environ/PATH",
                severity="advisory",
                message="PATH carries Windows directories (WSL appendWindowsPath); every lane "
                "CLI is checked to resolve to a Linux binary first",
            )
        )
    return issues


async def check_same_tree(
    host: WorkerHost, tools: ToolProbe, facts: dict[str, str | bool], checkpoint: str
) -> list[PreflightIssue]:
    """The worker runs the API's tree (SPEC-09 §2: build ids must match): this process
    imports ``mission_control`` from the checked tree and its venv is on the Linux filesystem;
    that tree is the ``/mnt`` checkout itself or a clean clone of the checkpoint commit."""

    issues: list[PreflightIssue] = []
    tree_source = f"{host.project_root}/src"
    if host.source_root != tree_source:
        issues.append(
            PreflightIssue(
                code="VENV_OTHER_TREE",
                pointer="host#/source_root",
                message="the venv imports mission_control from another tree; sync it from this "
                f"checkout (`uv sync` with {VENV_HINT}) or run from the tree it was synced from",
                expected=tree_source,
                observed=host.source_root,
            )
        )
    windows_checkout = host.on_windows_fs(host.project_root)
    facts["same_tree"] = "windows_checkout" if windows_checkout else "clone"
    if host.on_windows_fs(host.venv) or (
        windows_checkout and _within(host.venv, host.project_root)
    ):
        issues.append(
            PreflightIssue(
                code="VENV_ON_WINDOWS_FS",
                pointer="host#/venv",
                message="the worker's venv lives on the Linux filesystem, never in the Windows "
                f"checkout's .venv ({VENV_HINT})",
                observed=host.venv,
            )
        )
    if not windows_checkout:
        issues.extend(await _check_checkpoint(host, tools, facts, checkpoint))
    return issues


async def _check_checkpoint(
    host: WorkerHost, tools: ToolProbe, facts: dict[str, str | bool], checkpoint: str
) -> list[PreflightIssue]:
    """A clone is a clean checkout of the checkpoint commit the API runs."""

    issues: list[PreflightIssue] = []
    if (git := _resolve(host, tools, "git", "host#/path/git", issues)) is None:
        return issues

    def commit(revision: str) -> tuple[str, ...]:
        return (git, "-C", host.project_root, "rev-parse", "--verify", "--quiet", revision)

    head = await _stdout(tools, commit("HEAD^{commit}"))
    expected = await _stdout(tools, commit(f"{checkpoint}^{{commit}}"))
    status = await tools.run((git, "-C", host.project_root, "status", "--porcelain"))
    clean = status is not None and status.exit_code == 0 and not status.stdout.strip()
    facts["checkout_commit"] = head or "unknown"
    facts["checkpoint"] = f"{checkpoint} {expected or 'unresolved'}"
    if expected is None:
        message = f"the checkpoint {checkpoint} does not resolve in the clone; fetch it"
    elif head != expected:
        message = f"the clone is not at the checkpoint {checkpoint} the API runs"
    elif not clean:
        message = "the clone has local changes; a worker clone is a clean checkout"
    else:
        return issues
    issues.append(
        PreflightIssue(
            code="CLONE_NOT_CHECKPOINT",
            pointer="host#/project_root",
            message=message,
            expected=expected,
            observed=f"{head or 'unknown'}{'' if clean else ' (dirty)'}",
        )
    )
    return issues


# --- Lanes ---------------------------------------------------------------------------------

_LEASE_ROOTS: Final[Mapping[HostLane, tuple[Callable[[Settings], Path], str]]] = {
    "claude_agent_sdk": (claude_lease_root, "env:MISSION_CONTROL_CLAUDE_LEASE_ROOT"),
    "codex": (codex_lease_root, "env:MISSION_CONTROL_CODEX_LEASE_ROOT"),
}


def lease_root(lane: HostLane, settings: Settings) -> str:
    """The lane's Workspace Lease root exactly as the worker composes it."""

    return _LEASE_ROOTS[lane][0](settings).as_posix()


def check_lease_root(lane: HostLane, settings: Settings, host: WorkerHost) -> list[PreflightIssue]:
    pointer = _LEASE_ROOTS[lane][1]
    root = lease_root(lane, settings)
    issues: list[PreflightIssue] = []
    if host.on_windows_fs(root):
        issues.append(
            PreflightIssue(
                code="LEASE_ROOT_ON_WINDOWS_FS",
                pointer=pointer,
                message=f"{lane} leases live on the Linux filesystem (e.g. $HOME/mc-leases/...)",
                observed=root,
            )
        )
    for owned in (f"{host.home}/.cursor/worktrees", f"{host.codex_home}/worktrees"):
        if _within(root, owned):
            issues.append(
                PreflightIssue(
                    code="LEASE_ROOT_PROVIDER_OWNED",
                    pointer=pointer,
                    message="the lease root stays outside provider-owned worktree roots, whose "
                    "cleanup may delete worktrees it did not create (SPEC-03 §2)",
                    observed=root,
                )
            )
    return issues


async def check_claude_cli(
    host: WorkerHost, tools: ToolProbe, facts: dict[str, str | bool]
) -> list[PreflightIssue]:
    """``claude`` on PATH serves login and the status probe; sessions spawn the SDK-bundled
    Claude Code, which must be the pinned Linux build."""

    issues: list[PreflightIssue] = []
    if (claude := _resolve(host, tools, "claude", "host#/path/claude", issues)) is not None:
        version = await _version(tools, claude, _SEMVER)
        if version is None:
            issues.append(
                PreflightIssue(
                    code="CLI_UNRESPONSIVE",
                    pointer="host#/path/claude",
                    message="`claude --version` did not answer",
                )
            )
        else:
            facts["claude"] = version
    bundled = host.bundled_claude
    observed = await _version(tools, bundled, _SEMVER) if bundled is not None else None
    if observed == CLAUDE_BUNDLED_CLI_VERSION:
        facts["claude_bundled"] = observed
    else:
        issues.append(
            PreflightIssue(
                code="CLAUDE_BUNDLED_CLI_MISMATCH",
                pointer="host#/venv/claude_agent_sdk/_bundled",
                message="the venv's claude-agent-sdk bundles the pinned Linux Claude Code; sync "
                f"the Linux venv ({VENV_HINT})",
                expected=CLAUDE_BUNDLED_CLI_VERSION,
                observed=observed or bundled,
            )
        )
    return issues


async def check_codex_cli(
    host: WorkerHost, settings: Settings, tools: ToolProbe, facts: dict[str, str | bool]
) -> list[PreflightIssue]:
    """The binary the launcher spawns, against the pin it enforces
    (``SubprocessAppServerLauncher.check_version``)."""

    issues: list[PreflightIssue] = []
    pointer = "env:MISSION_CONTROL_CODEX_BINARY"
    codex = _resolve(host, tools, settings.mission_control_codex_binary, pointer, issues)
    if codex is None:
        return issues
    observed = await _version(tools, codex, _CODEX_VERSION)
    facts["codex"] = observed or "unknown"
    if observed == PINNED_CODEX_CLI_VERSION:
        return issues
    overridden = observed is not None and settings.mission_control_codex_allow_version_mismatch
    issues.append(
        PreflightIssue(
            code="CODEX_PIN_OVERRIDDEN" if overridden else "CODEX_PIN_MISMATCH",
            pointer=pointer,
            severity="advisory" if overridden else "blocking",
            message="codex-cli differs from the pin; the launcher accepts it only under "
            "MISSION_CONTROL_CODEX_ALLOW_VERSION_MISMATCH",
            expected=PINNED_CODEX_CLI_VERSION,
            observed=observed,
        )
    )
    return issues


AuthSource = AuthAdmissionService | PreflightIssue


async def check_auth(
    lane: HostLane,
    auth: AuthSource,
    profile_id: str | None,
    facts: dict[str, str | bool],
    *,
    settings: Settings | None = None,
) -> list[PreflightIssue]:
    """Admit the lane's auth profile exactly as a launch would; `auth` is the worker's
    admission or the reason there is none."""

    if isinstance(auth, PreflightIssue):
        return [auth]
    try:
        admitted = await auth.admit(lane, profile_id, pointer="")
    except AuthAdmissionRejected as rejected:
        return [
            PreflightIssue(
                code=issue.code,
                pointer=f"auth-profile:{profile_id or '-'}#{issue.pointer}",
                message=issue.message,
            )
            for issue in rejected.issues
        ]
    if lane == "codex" and admitted.route == "owner_cli_login" and settings is not None:
        if (
            settings.mission_control_codex_home_mode != "owner"
            or settings.mission_control_codex_owner_home is None
        ):
            return [
                PreflightIssue(
                    code="CODEX_OWNER_HOME_REQUIRED",
                    pointer="env:MISSION_CONTROL_CODEX_OWNER_HOME",
                    message="Codex owner login requires owner mode and an explicit owner home; "
                    "isolated homes require an admitted API-key route.",
                )
            ]
        facts["codex.auth_home"] = str(settings.mission_control_codex_owner_home)
    facts[f"{lane}.auth"] = f"{admitted.profile_id} ({admitted.route}, {admitted.billing_mode})"
    return []


# --- The host report -----------------------------------------------------------------------


async def assess_worker_host(
    lanes: Sequence[HostLane],
    host: WorkerHost,
    settings: Settings,
    *,
    tools: ToolProbe,
    auth: AuthSource,
    auth_profile_ids: Mapping[str, str],
    checkpoint: str = DEFAULT_CHECKPOINT,
) -> ReadinessReport:
    facts: dict[str, str | bool] = {
        "system": host.system,
        "release": host.release,
        "python": ".".join(map(str, host.python)),
        "wsl": host.wsl,
        "project_root": host.project_root,
        "source_root": host.source_root,
        "venv": host.venv,
    }
    checks: dict[str, CheckState] = {}
    issues: list[PreflightIssue] = []

    def record(name: str, found: Sequence[PreflightIssue]) -> None:
        for item in found:
            # A finding shared by several checks (a missing git, no auth registry) is listed once.
            if item not in issues:
                issues.append(item)
        blocking = any(item.severity == "blocking" for item in found)
        checks[name] = "failed" if blocking else "passed"

    record("host_os", check_os(lanes, host))
    record("python", check_python(host))
    record("toolchain", await check_toolchain(host, tools, facts))
    record("same_tree", await check_same_tree(host, tools, facts, checkpoint))
    for lane in lanes:
        if lane == "claude_agent_sdk":
            record(f"{lane}.cli", await check_claude_cli(host, tools, facts))
        else:
            record(f"{lane}.cli", await check_codex_cli(host, settings, tools, facts))
        facts[f"{lane}.lease_root"] = lease_root(lane, settings)
        record(f"{lane}.lease_root", check_lease_root(lane, settings, host))
        record(
            f"{lane}.auth",
            await check_auth(lane, auth, auth_profile_ids.get(lane), facts, settings=settings),
        )
    return ReadinessReport(host=facts, checks=checks, issues=tuple(issues))


def worker_auth(settings: Settings, host: WorkerHost, profiles: Path | None) -> AuthSource:
    """The worker's auth admission over `profiles` with the status probe on."""

    missing = PreflightIssue(
        code="AUTH_PROFILES_MISSING",
        pointer="env:MISSION_CONTROL_AUTH_PROFILES_PATH",
        message="no mc.auth_profile.v1 registry is configured (--auth-profiles)",
    )
    path = profiles or settings.mission_control_auth_profiles_path
    if path is None:
        return missing
    selected_env = selected_auth_environment(settings, host.environ)
    runner = SubprocessStatusRunner(
        status_probe_environment(selected_env),
        timeout_s=settings.mission_control_auth_status_timeout_s,
        binaries={"codex": settings.mission_control_codex_binary},
    )
    try:
        admission = compose_auth_admission(
            settings.model_copy(update={"mission_control_auth_profiles_path": path}),
            environ=selected_env,
            status_runner=runner,
            home=Path(host.home),
            project_root=Path(host.project_root),
        )
    except AuthProfilesUnavailable as error:
        return PreflightIssue(
            code="AUTH_PROFILES_INVALID", pointer=path.as_posix(), message=redact_text(str(error))
        )
    return admission if admission is not None else missing


async def worker_host_readiness(
    lanes: Sequence[HostLane],
    settings: Settings,
    *,
    auth_profile_ids: Mapping[str, str],
    auth_profiles: Path | None = None,
    checkpoint: str = DEFAULT_CHECKPOINT,
    environ: Mapping[str, str] | None = None,
) -> ReadinessReport:
    """The live host report: this process's facts, real tools and the worker's admission."""

    host = WorkerHost.current(environ)
    return await assess_worker_host(
        lanes,
        host,
        settings,
        tools=SubprocessToolProbe(host.environ),
        auth=worker_auth(settings, host, auth_profiles),
        auth_profile_ids=auth_profile_ids,
        checkpoint=checkpoint,
    )


__all__ = [
    "DEFAULT_CHECKPOINT",
    "AuthSource",
    "SubprocessToolProbe",
    "ToolProbe",
    "WorkerHost",
    "assess_worker_host",
    "bundled_claude_cli",
    "lease_root",
    "on_windows_mount",
    "worker_auth",
    "worker_host_readiness",
    "wsl_automount_root",
]
