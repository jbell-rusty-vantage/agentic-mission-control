"""Bounded Cursor startup inspection; only released sidecars are eligible for cleanup."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from mission_control.application.execution.harness.leases import (
    BridgeShutdownDisposition,
    ReleasedBridgeLeaseStore,
    WorkspaceLease,
)
from mission_control.application.execution.harness.state import LaneExecutionState
from mission_control.application.workspaces.policy import slot_digest, slot_path


class ReleasedBridgeShutdown(Protocol):
    async def __call__(self, *, workspace: Path, timeout_s: float) -> BridgeShutdownDisposition: ...


@dataclass(frozen=True)
class ReleasedBridgeSweepOutcome:
    lease_id: UUID
    disposition: Literal["stopped", "already_absent", "protected", "unsafe_path", "unavailable"]


ActiveDisposition = Literal[
    "protected",
    "unsafe_path",
    "unavailable",
    "ambiguous_anchor",
    "custody_required",
    "recovery_notified",
]


@dataclass(frozen=True)
class ActiveBridgeContext:
    lease: WorkspaceLease
    state: LaneExecutionState
    lifecycle: str
    workflow_id: str
    root_workflow_id: str
    temporal_address: str
    temporal_namespace: str
    temporal_target: str


class ActiveBridgeInspector(Protocol):
    async def __call__(self, context: ActiveBridgeContext) -> ActiveDisposition: ...


class ActiveBridgeLeaseStore(Protocol):
    async def active_bridge_candidates(
        self, request_scope: str, *, allocator_ref: str, limit: int
    ) -> tuple[WorkspaceLease, ...]: ...

    async def guard_active_bridge(
        self, candidate: WorkspaceLease, *, allocator_ref: str, inspect: ActiveBridgeInspector
    ) -> ActiveDisposition: ...


@dataclass(frozen=True)
class ActiveBridgeSweepOutcome:
    lease_id: UUID
    disposition: ActiveDisposition


async def sweep_active_cursor_bridges(
    store: ActiveBridgeLeaseStore,
    *,
    request_scope: str,
    root: Path,
    allocator_ref: str,
    inspect: ActiveBridgeInspector,
    limit: int = 64,
) -> tuple[ActiveBridgeSweepOutcome, ...]:
    """Classify retained holders; neither expiry nor native status authorizes release."""
    if not 1 <= limit <= 64 or not allocator_ref:
        raise ValueError("invalid active bridge sweep bounds")
    candidates = await store.active_bridge_candidates(
        request_scope, allocator_ref=allocator_ref, limit=limit
    )
    if len(candidates) > limit:
        raise ValueError("active bridge candidate bound exceeded")
    outcomes = []
    for candidate in candidates:
        # Reuse canonical-path validation without changing the retained lease itself.
        check = candidate.model_copy(update={"released_at": candidate.expires_at})
        expected = await asyncio.to_thread(
            _eligible_path, check, request_scope, root, allocator_ref
        )
        disposition: ActiveDisposition = "unsafe_path"
        if expected is not None and not candidate.released:
            try:
                async with asyncio.timeout(8):
                    disposition = await store.guard_active_bridge(
                        candidate, allocator_ref=allocator_ref, inspect=inspect
                    )
            except Exception:
                disposition = "unavailable"
        outcomes.append(ActiveBridgeSweepOutcome(candidate.lease_id, disposition))
    return tuple(outcomes)


def _eligible_path(
    candidate: WorkspaceLease, request_scope: str, root: Path, allocator_ref: str
) -> Path | None:
    try:
        expected = slot_path(root, request_scope, candidate.slot or "")
        digest = slot_digest(request_scope, candidate.slot or "")
        lexical = root.resolve() / digest[:2] / digest[2:20] / "worktree"
        safe = (
            expected == lexical
            and candidate.request_scope == request_scope
            and candidate.lane_profile == "cursor_local"
            and candidate.allocator_ref == allocator_ref
            and candidate.slot is not None
            and candidate.released
            and not candidate.active_participants
            and Path(candidate.path).absolute() == expected
        )
        return expected if safe else None
    except (OSError, RuntimeError, ValueError):
        return None


async def sweep_released_cursor_bridges(
    store: ReleasedBridgeLeaseStore,
    *,
    request_scope: str,
    root: Path,
    allocator_ref: str,
    shutdown: ReleasedBridgeShutdown,
    limit: int = 64,
    timeout_s: float = 5,
) -> tuple[ReleasedBridgeSweepOutcome, ...]:
    """One trusted scope, at most 64 candidates; caller bounds total startup time.

    Only the canonical slot path is eligible. Historical arbitrary paths and aliases refuse.
    Shutdown runs under the same persistence lock as acquisition; no files are removed.
    """
    if not 1 <= limit <= 64 or not 0 < timeout_s <= 5 or not allocator_ref:
        raise ValueError("invalid released bridge sweep bounds")
    candidates = await store.released_bridge_candidates(
        request_scope, allocator_ref=allocator_ref, limit=limit
    )
    if len(candidates) > limit:
        raise ValueError("released bridge candidate bound exceeded")
    outcomes: list[ReleasedBridgeSweepOutcome] = []
    for candidate in candidates:
        expected = await asyncio.to_thread(
            _eligible_path, candidate, request_scope, root, allocator_ref
        )
        if expected is None:
            outcomes.append(ReleasedBridgeSweepOutcome(candidate.lease_id, "unsafe_path"))
            continue

        native_disposition: list[BridgeShutdownDisposition] = []
        workspace_path: Path = expected

        async def stop(
            locked: WorkspaceLease,
            candidate: WorkspaceLease = candidate,
            expected: Path = workspace_path,
            native_disposition: list[BridgeShutdownDisposition] = native_disposition,
        ) -> BridgeShutdownDisposition:
            # Recheck under the persistence lock; paths may not change after enumeration.
            if locked.path != candidate.path or locked.fence != candidate.fence:
                raise ValueError("released bridge holder changed")
            async with asyncio.timeout(timeout_s):
                result = await shutdown(workspace=expected, timeout_s=timeout_s)
                native_disposition.append(result)
                return result

        try:
            stopped = await store.guard_released_bridge(
                candidate, allocator_ref=allocator_ref, shutdown=stop
            )
            disposition: Literal[
                "stopped", "already_absent", "protected", "unsafe_path", "unavailable"
            ] = native_disposition[0] if stopped and native_disposition else "protected"
        except Exception:
            # Native errors may contain discovery tokens. Preserve only a bounded disposition.
            disposition = "unavailable"
        outcomes.append(ReleasedBridgeSweepOutcome(candidate.lease_id, disposition))
    return tuple(outcomes)
