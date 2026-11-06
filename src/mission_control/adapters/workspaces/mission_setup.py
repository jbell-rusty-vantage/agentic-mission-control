"""Runs a leased worktree's mission layer: ``bash .mission/setup/run --phase <phase>`` (ADR-0042).

The `MissionSetupRunner` of local lanes. The script runs in the worktree with exactly the
environment the lane passes (the MO-04 allowlist plus ``setup``-phase secrets), never the
worker's own. Its output is discarded rather than kept: a step may echo a value the Secret
Broker delivered, and the receipt the script writes is the evidence. The kit bounds the
script itself; this runner adds a hard stop and kills the process when it is exceeded.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from mission_control.application.environments.mission_layer import EnvironmentNotPrepared
from mission_control.domain.authoring.environment_kits import MISSION_SETUP_RUN, SetupPhase

TIMED_OUT_EXIT = 124
# Windows' System32 bash.exe and its WindowsApps alias launch WSL: the child would run in
# another kernel, outside the allowlisted environment and beyond ``process.kill()``.
_WSL_LAUNCHER_DIRS = frozenset({"system32", "windowsapps"})


def resolve_bash(
    which: Callable[[str], str | None] = shutil.which, *, windows: bool = os.name == "nt"
) -> str | None:
    """The ``bash`` on PATH; on Windows, Git for Windows' bash instead of the WSL launcher."""

    found = which("bash")
    if found is None or not windows or Path(found).parent.name.lower() not in _WSL_LAUNCHER_DIRS:
        return found
    git = which("git")
    if git is None:
        return None
    # Git for Windows: git.exe in <root>/cmd, <root>/bin or <root>/mingw64/bin; bash.exe in
    # <root>/bin.
    root = Path(git).parent.parent
    if root.name.lower() in {"mingw64", "mingw32", "usr"}:
        root = root.parent
    candidate = root / "bin" / "bash.exe"
    return str(candidate) if candidate.is_file() else None


class BashMissionSetupRunner:
    def __init__(self, bash: str | None = None) -> None:
        self._bash = bash

    def _executable(self) -> str:
        executable = self._bash or resolve_bash()
        if executable is None:
            raise EnvironmentNotPrepared("no bash executable is available to run the mission layer")
        return executable

    async def run(
        self,
        root: Path,
        *,
        phase: SetupPhase,
        environment: Mapping[str, str],
        timeout_s: float,
    ) -> int:
        process = await asyncio.create_subprocess_exec(
            self._executable(),
            MISSION_SETUP_RUN,
            "--phase",
            phase,
            cwd=root,
            env=dict(environment),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            return await asyncio.wait_for(process.wait(), timeout_s)
        except TimeoutError:
            process.kill()
            await process.wait()
            return TIMED_OUT_EXIT


__all__ = ["TIMED_OUT_EXIT", "BashMissionSetupRunner", "resolve_bash"]
