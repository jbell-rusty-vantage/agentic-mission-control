"""missionctl exit codes (RUNTIME-CONTRACTS): 0 success, 2 invalid, 3 denied, 4 conflict,
5 unavailable, 6 wait timeout or blocked terminal result."""

from __future__ import annotations

WAIT_TIMEOUT = 6


def exit_status(status: int) -> int:
    if 200 <= status < 300:
        return 0
    if status in {401, 403}:
        return 3
    if status == 409:
        return 4
    if status in {400, 404, 413, 422}:
        return 2
    return 5


__all__ = ["WAIT_TIMEOUT", "exit_status"]
