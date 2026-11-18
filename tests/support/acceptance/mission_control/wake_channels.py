"""Builders, constants and fakes that other test files import.

Moved from tests/acceptance/mission_control/test_wake_channels.py.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys


def missionctl(url: str, token: str, *args: str) -> subprocess.Popen[bytes]:
    """A separate `missionctl` process (the Windows selector loop cannot spawn asyncio ones)."""

    return subprocess.Popen(
        [sys.executable, "-m", "mission_control.interfaces.cli", *args],
        env={
            **os.environ,
            "MISSION_CONTROL_URL": url,
            "MISSION_CONTROL_APPLICATION_ID": "biotech",
            "MISSION_CONTROL_TOKEN": token,
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


async def finished(process: subprocess.Popen[bytes], seconds: float) -> tuple[str, str]:
    stdout, stderr = await asyncio.to_thread(process.communicate, timeout=seconds)
    return stdout.decode(), stderr.decode()
