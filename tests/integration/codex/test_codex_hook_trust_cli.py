"""MO-03 / Q-X2 against the real `codex app-server` (opt-in; no login, no model turn, no cost).

Runs only with `MC_CODEX_HOOK_DRILL=1` and a codex CLI (`MC_CODEX_BINARY`, default
`codex`; the R21 pin is 0.162.1, so the 0.162.0 schema pin is overridden explicitly). The
production `prepare` writes the kernel projection, `kernel.py` and the isolated `CODEX_HOME`
trust; the production launcher starts the app-server in that home, and only `initialize`
and `hooks/list` are sent: Codex must report every projected hook trusted at the hash
Mission Control recorded, and an edited trust record must make the check refuse.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from mission_control.adapters.codex.harness import CODEX_HOME_DIR, projected_hooks
from mission_control.adapters.codex.hook_trust import (
    HOOKS_FILE,
    HookTrustUnverified,
    verify_listed_trust,
)
from mission_control.adapters.codex.launcher import LaunchSpec, SubprocessAppServerLauncher
from mission_control.adapters.codex.protocol import M_HOOKS_LIST, M_INITIALIZE, M_INITIALIZED
from mission_control.domain.execution.lanes import PrepareRequest
from tests.unit.codex.drive import fields
from tests.unit.codex.test_kernel_hooks import kernel_projection, kernel_stack, memory_hooks

pytestmark = pytest.mark.skipif(
    os.environ.get("MC_CODEX_HOOK_DRILL") != "1",
    reason="opt-in: set MC_CODEX_HOOK_DRILL=1 with a local codex CLI (no login needed)",
)
ENV_NAMES = ("PATH", "SYSTEMROOT", "SystemRoot", "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA")


async def _listed(root: Path, home: Path) -> dict[str, object]:
    launcher = SubprocessAppServerLauncher(
        os.environ.get("MC_CODEX_BINARY", "codex"), allow_version_mismatch=True
    )
    env = {name: os.environ[name] for name in ENV_NAMES if name in os.environ}
    launched = await launcher.launch(
        LaunchSpec(cwd=root, env={**env, "CODEX_HOME": str(home)}, codex_home=home)
    )
    try:
        connection = launched.connection
        await connection.request(
            M_INITIALIZE,
            {"clientInfo": {"name": "mission_control_probe", "version": "0"}, "capabilities": {}},
        )
        await connection.notify(M_INITIALIZED)
        return await connection.request(M_HOOKS_LIST, {"cwds": [str(root)]}) or {}
    finally:
        await launched.terminate()


async def test_the_real_app_server_trusts_the_hooks_the_lane_projected(tmp_path: Path) -> None:
    stack = kernel_stack(tmp_path, hooks=memory_hooks()[0])
    harness = stack.harness
    harness.stage(stack.heid, stack.operation)
    await harness.prepare(
        PrepareRequest(
            **fields(stack),
            run_id=stack.operation.identity.run_id,
            operation_id=stack.operation.identity.operation_id,
            attempt_no=1,
        )
    )
    root = Path(harness.lease_path(stack.heid))
    await asyncio.to_thread(subprocess.run, ["git", "init", "-q", str(root)], check=True)
    home = root / CODEX_HOME_DIR
    records, kernel = projected_hooks(kernel_projection(), root)
    assert kernel and records

    verify_listed_trust(await _listed(root, home), records, root / HOOKS_FILE)

    config = home / "config.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("trusted_hash", "stale_hash", 1),
        encoding="utf-8",
    )
    with pytest.raises(HookTrustUnverified, match="untrusted"):
        verify_listed_trust(await _listed(root, home), records, root / HOOKS_FILE)
