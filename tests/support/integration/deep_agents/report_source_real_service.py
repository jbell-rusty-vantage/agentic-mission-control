"""Builders, constants and fakes that other test files import.

Moved from tests/integration/deep_agents/test_report_source_real_service.py.
"""

from __future__ import annotations

import asyncio
import json


async def response(process):
    line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 90)
    if not line:
        raise AssertionError(f"fixture host exited: {process.returncode}")
    return json.loads(line)


async def command(process, payload):
    process.stdin.write((json.dumps(payload) + "\n").encode())
    process.stdin.flush()
    return await response(process)
