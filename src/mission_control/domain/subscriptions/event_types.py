"""Mission event type patterns shared by subscription filters and watcher triggers."""

from __future__ import annotations

import fnmatch


def event_type_matches(pattern: str, event_type: str) -> bool:
    """Exact names, ``*`` for everything, or a trailing ``.*`` family (``human_task.*``)."""

    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return event_type.startswith(pattern[:-1])
    return fnmatch.fnmatchcase(event_type, pattern) if "*" in pattern else pattern == event_type


__all__ = ["event_type_matches"]
