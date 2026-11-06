"""Lease-private detached Cursor bridge with explicit child environment (CM-04/05).

The pinned SDK's launcher inherits the worker environment and owns an asyncio subprocess.
This launcher uses synchronous Popen in a thread and AsyncClient.connect so Selector loops
and worker restarts reuse a live sidecar. Endpoint tokens and stderr remain under the lease
state root and never enter snapshots/artifacts. Tool/store callbacks are not configured;
custom-tool approvals and copied stores remain deferred. End-session shuts down explicitly.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlsplit

from cursor_sdk._bridge import BridgeEndpoint
from cursor_sdk._vendor import resolve_bridge_path
from cursor_sdk.asyncio import AsyncClient

from mission_control.adapters.cursor.bridge import CURSOR_SDK_PIN

_SDK_VERSION: Final = version("cursor-sdk")
if _SDK_VERSION != CURSOR_SDK_PIN:  # pragma: no cover - guards an SDK bump
    raise ImportError(f"cursor-sdk {_SDK_VERSION} is installed; the bridge pins {CURSOR_SDK_PIN}")

# The client markers `_bridge_subprocess_env` adds (the backend identifies Python callers).
CLIENT_LANGUAGE_ENV: Final = "CURSOR_SDK_CLIENT_LANGUAGE"
PYTHON_VERSION_ENV: Final = "CURSOR_SDK_PYTHON_VERSION"


def bridge_spawn_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Exactly what the bridge receives: the explicit environment plus the SDK's markers."""

    return {**environment, CLIENT_LANGUAGE_ENV: "python", PYTHON_VERSION_ENV: _SDK_VERSION}


DISCOVERY_FILE: Final = "mc-bridge-discovery.json"


def _spawn_endpoint(
    command: Sequence[str] | None,
    workspace: Path,
    state_root: Path,
    environment: Mapping[str, str],
    timeout: float,
) -> BridgeEndpoint:
    """Popen works independently of the worker event loop, including Windows Selector."""
    from cursor_sdk._bridge import parse_discovery_line

    argv = [
        *(command or (resolve_bridge_path(),)),
        "--workspace",
        str(workspace),
        "--state-root",
        str(state_root),
    ]
    # A pipe owned by the worker can break when that worker dies. A lease-private log
    # leaves the sidecar independent of the worker's descriptors and event loop.
    log_path = state_root / "mc-bridge-stderr.log"
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as log:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=log,
            env=bridge_spawn_environment(environment),
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    deadline = time.monotonic() + timeout
    try:
        with log_path.open(encoding="utf-8", errors="replace") as stream:
            while time.monotonic() < deadline:
                line = stream.readline()
                if line:
                    raw = parse_discovery_line(line)
                    if raw is not None:
                        return BridgeEndpoint.from_discovery(raw)
                elif process.poll() is not None:
                    raise RuntimeError("Cursor bridge exited before discovery")
                else:
                    time.sleep(0.01)
        raise RuntimeError("Cursor bridge discovery timed out")
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        raise RuntimeError("Cursor bridge discovery failed") from None


def _save_endpoint(path: Path, endpoint: BridgeEndpoint, workspace: Path, state_root: Path) -> None:
    # Contains the bridge token: lease-private, never a provider frame or artifact.
    temporary = path.with_suffix(".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(
            {
                "endpoint": dataclasses.asdict(endpoint),
                "workspace": str(workspace.resolve()),
                "state_root": str(state_root.resolve()),
            },
            stream,
        )
    temporary.chmod(0o600)
    temporary.replace(path)


def _load_endpoint(
    path: Path, workspace: Path, state_root: Path, *, canonical_identity: bool = False
) -> BridgeEndpoint:
    record = json.loads(path.read_text(encoding="utf-8"))
    endpoint = BridgeEndpoint(**record["endpoint"])
    url = urlsplit(endpoint.url)
    if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Cursor discovery is not a loopback endpoint")
    identity = Path.absolute if canonical_identity else Path.resolve
    if identity(Path(record["state_root"])) != identity(state_root):
        raise RuntimeError("Cursor discovery belongs to another state root")
    if identity(Path(record["workspace"])) != identity(workspace):
        raise RuntimeError("Cursor discovery belongs to another workspace")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise RuntimeError("Cursor discovery file is not private")
    return endpoint


async def launch_bridge_client(
    command: Sequence[str] | None,
    *,
    workspace: Path,
    state_root: Path,
    environment: Mapping[str, str],
    discovery_timeout_s: float,
) -> AsyncClient:
    """Connect to the lease's detached bridge; never replace an ambiguous live bridge.

    Closing the HTTP client does not kill the bridge. end_session explicitly shuts it down.
    A stale/unreachable discovery is an error requiring reconciliation, never a blind spawn.
    """
    await asyncio.to_thread(state_root.mkdir, parents=True, exist_ok=True, mode=0o700)
    path = state_root / DISCOVERY_FILE
    if path.exists():
        endpoint = await asyncio.to_thread(_load_endpoint, path, workspace, state_root)
    else:
        endpoint = await asyncio.to_thread(
            _spawn_endpoint, command, workspace, state_root, environment, discovery_timeout_s
        )
        await asyncio.to_thread(_save_endpoint, path, endpoint, workspace, state_root)
    client = AsyncClient.connect(
        endpoint.url, endpoint.auth_token, max_retries=0, unary_timeout=discovery_timeout_s
    )
    # connect() has no environment-fallback parameter; the client defaults false.
    try:
        await client.ping()
        version_info = await client.get_version()
        if not version_info:
            raise RuntimeError("Cursor bridge returned no version evidence")
    except Exception:
        await client.aclose()
        raise RuntimeError("Cursor bridge capability check failed; reconcile discovery") from None
    return client


async def shutdown_bridge(state_root: Path, *, workspace: Path) -> None:
    path = state_root / DISCOVERY_FILE
    if not path.exists():
        return
    endpoint = await asyncio.to_thread(_load_endpoint, path, workspace, state_root)
    client = AsyncClient.connect(endpoint.url, endpoint.auth_token, max_retries=0, unary_timeout=5)
    try:
        await client.shutdown(grace_seconds=0)
    finally:
        await client.aclose()
    await asyncio.to_thread(path.unlink)


async def shutdown_released_bridge(
    *, workspace: Path, timeout_s: float = 5
) -> Literal["stopped", "already_absent"]:
    """Read-only discovery and endpoint shutdown for a persistence-guarded released lease.

    Never unlinks discovery/log/store files and never signals a PID. Missing discovery is
    reported as absence; malformed or unreachable evidence raises for the caller to record.
    """
    from mission_control.application.agentic_components.placement import STATE_ROOT

    if not 0 < timeout_s <= 5:
        raise ValueError("invalid released bridge shutdown timeout")
    state_root = workspace / STATE_ROOT
    path = state_root / DISCOVERY_FILE
    resolved_state = await asyncio.to_thread(state_root.resolve)
    resolved_workspace = await asyncio.to_thread(workspace.resolve)
    canonical_workspace = await asyncio.to_thread(workspace.absolute)
    if (
        resolved_workspace != canonical_workspace
        or resolved_state != resolved_workspace / STATE_ROOT
        or path.is_symlink()
        or path.is_junction()
    ):
        raise ValueError("released bridge state root escapes workspace")
    if not path.exists():
        return "already_absent"
    if not path.is_file():
        raise ValueError("released bridge discovery is not a regular file")
    endpoint = await asyncio.to_thread(
        _load_endpoint, path, workspace, state_root, canonical_identity=True
    )
    client = AsyncClient.connect(
        endpoint.url, endpoint.auth_token, max_retries=0, unary_timeout=timeout_s
    )
    try:
        async with asyncio.timeout(timeout_s):
            await client.shutdown(grace_seconds=0)
    finally:
        await client.aclose()
    return "stopped"


async def inspect_active_bridge(
    *, workspace: Path, agent_id: str, anchor: str, ambiguous_send: bool
) -> Literal["aligned", "ambiguous_anchor", "unavailable"]:
    """Read existing loopback discovery only; never launch, resume, cancel or send."""
    from mission_control.application.agentic_components.placement import STATE_ROOT

    state_root = workspace / STATE_ROOT
    path = state_root / DISCOVERY_FILE

    def safe_discovery() -> bool:
        return (
            workspace.resolve() == workspace.absolute()
            and state_root.resolve() == workspace.resolve() / STATE_ROOT
            and not path.is_symlink()
            and not path.is_junction()
            and path.is_file()
        )

    if not await asyncio.to_thread(safe_discovery):
        return "unavailable"
    endpoint = await asyncio.to_thread(
        _load_endpoint, path, workspace, state_root, canonical_identity=True
    )
    client = AsyncClient.connect(endpoint.url, endpoint.auth_token, max_retries=0, unary_timeout=2)
    try:
        async with asyncio.timeout(3):
            agent = await client.get_agent(agent_id, cwd=str(workspace))
            if (
                str(agent.agent_id) != agent_id
                or agent.runtime != "local"
                or not agent.cwd
                or not await asyncio.to_thread(
                    lambda: Path(agent.cwd).resolve() == workspace.resolve()
                )
            ):
                return "ambiguous_anchor"
            listed = await client.list_runs(agent_id, cwd=str(workspace), runtime="local", limit=65)
            runs = tuple(str(run.id) for run in listed.items)
            if len(runs) > 64 or len(runs) != len(set(runs)) or anchor not in runs:
                return "ambiguous_anchor"
            ahead = runs.index(anchor)
            if ahead != (1 if ambiguous_send else 0):
                return "ambiguous_anchor"
            for run_id in runs[: ahead + 1]:
                native = await client.get_run(run_id)
                if (
                    str(native.id) != run_id
                    or str(native.agent_id) != agent_id
                    or native.status not in {"running", "finished", "error", "cancelled", "expired"}
                ):
                    return "ambiguous_anchor"
            return "aligned"
    finally:
        await client.aclose()


async def sweep_bridges(
    state_roots: Sequence[Path], *, active_roots: Sequence[Path]
) -> tuple[Path, ...]:
    """Startup composition supplies only reconciled orphan lease roots; active leases win."""
    active = {root.resolve() for root in active_roots}
    stopped: list[Path] = []
    for root in state_roots:
        if root.resolve() in active or not (root / DISCOVERY_FILE).is_file():
            continue
        record = json.loads((root / DISCOVERY_FILE).read_text(encoding="utf-8"))
        await shutdown_bridge(root, workspace=Path(record["workspace"]))
        stopped.append(root)
    return tuple(stopped)


__all__ = [
    "CLIENT_LANGUAGE_ENV",
    "PYTHON_VERSION_ENV",
    "bridge_spawn_environment",
    "launch_bridge_client",
]
