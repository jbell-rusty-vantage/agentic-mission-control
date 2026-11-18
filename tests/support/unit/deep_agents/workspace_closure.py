"""Builders, constants and fakes that other test files import.

Moved from tests/unit/deep_agents/test_workspace_closure.py.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

from mission_control.domain.execution.contracts import WorkspaceOwner, WorkspaceSlotBinding

OWNER = WorkspaceOwner(kind="stage", owner_id="stage-a")


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _workspace(*, sensitive: bool = False) -> Any:
    slots = (
        WorkspaceSlotBinding(
            slot_name="out", logical_path="/out", access="exclusive_write", owner=OWNER
        ),
        WorkspaceSlotBinding(
            slot_name="private",
            logical_path="/private",
            access="exclusive_write",
            owner=OWNER,
            sensitive=sensitive,
        ),
        WorkspaceSlotBinding(
            slot_name="ctx-input",
            logical_path="/inputs/brief.md",
            access="read_only",
            owner=OWNER,
            durable_ref="memory://brief",
            content_digest=_digest(b"brief"),
        ),
    )
    return SimpleNamespace(slot_bindings=slots, exclusive_write_paths=("/out", "/private"))
