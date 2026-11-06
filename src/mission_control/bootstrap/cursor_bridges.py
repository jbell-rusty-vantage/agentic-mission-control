"""Opt-in bridge inspection and released cleanup for the selected application and host."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import asyncpg
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from mission_control.adapters.cursor.bridge_recovery import (
    ActiveBridgeContext,
    ActiveBridgeSweepOutcome,
    ActiveDisposition,
    ReleasedBridgeSweepOutcome,
    sweep_active_cursor_bridges,
    sweep_released_cursor_bridges,
)
from mission_control.adapters.cursor.bridge_spawn import (
    inspect_active_bridge,
    shutdown_released_bridge,
)
from mission_control.adapters.postgres.lanes.workspace_leases import PostgresWorkspaceLeaseStore
from mission_control.adapters.workspaces.git_workspaces import GitWorkspaceBackend
from mission_control.bootstrap.settings import Settings
from mission_control.contracts.identities import parse_request_scope

logger = logging.getLogger(__name__)
STARTUP_TIMEOUT_S = 30


async def inspect_active_cursor_context(
    context: ActiveBridgeContext, settings: Settings, temporal_client: Client | None
) -> ActiveDisposition:
    state = context.state
    if (
        context.lifecycle != "live"
        or temporal_client is None
        or context.temporal_address != settings.temporal_address
        or context.temporal_namespace != temporal_client.namespace
        or context.temporal_namespace != settings.temporal_namespace
        or context.temporal_target != settings.temporal_target
    ):
        return "custody_required"
    if not state.native_session_ref or not state.native_turn_ref or len(state.dispatches) > 128:
        return "ambiguous_anchor"
    dispatches = tuple(state.dispatches.values())
    if not any(
        record.kind == "send"
        and record.phase == "acknowledged"
        and record.expected_generation == context.lease.generation
        and record.native_ref == state.native_turn_ref
        for record in dispatches
    ):
        return "ambiguous_anchor"
    pending = tuple(record for record in dispatches if record.phase in {"intended", "in_doubt"})
    if len(pending) > 1 or any(
        record.kind != "send" or record.expected_generation != context.lease.generation
        for record in pending
    ):
        return "ambiguous_anchor"
    native = await inspect_active_bridge(
        workspace=Path(context.lease.path),
        agent_id=state.native_session_ref,
        anchor=state.native_turn_ref,
        ambiguous_send=bool(pending),
    )
    if native != "aligned":
        return native
    handle = temporal_client.get_workflow_handle(context.workflow_id)
    try:
        actual = await handle.describe()
    except RPCError as error:
        if error.status == RPCStatusCode.NOT_FOUND:
            return "custody_required"
        raise
    if (
        actual.id != context.workflow_id
        or actual.status != WorkflowExecutionStatus.RUNNING
        or actual.parent_id != context.root_workflow_id
    ):
        return "custody_required"
    # Pin the observed execution; never start or redirect an operation here.
    await temporal_client.get_workflow_handle(context.workflow_id, run_id=actual.run_id).signal(
        "ingress_wake", f"cursor-recovery:{context.lease.lease_id}:{context.lease.fence}"
    )
    return "recovery_notified"


async def recover_released_cursor_bridges(
    settings: Settings,
    pool: asyncpg.Pool,
    *,
    default_root: Path,
    temporal_client: Client | None = None,
) -> tuple[ReleasedBridgeSweepOutcome | ActiveBridgeSweepOutcome, ...]:
    """No configured scopes means no query or shutdown; the caller has composed Cursor."""
    scopes = tuple(dict.fromkeys(settings.mission_control_cursor_bridge_sweep_scopes))
    if not scopes:
        return ()
    if len(scopes) > 32:
        raise ValueError("Cursor bridge recovery permits at most 32 scopes")
    catalog = (settings.mission_control_catalog_scope or "").split("/")
    if len(catalog) != 4 or catalog[-1] != "catalog":
        raise ValueError("released bridge sweep requires the selected application identity")
    for scope in scopes:
        parse_request_scope(scope)
        if scope.split("/")[:3] != catalog[:3]:
            raise ValueError("released bridge sweep scope differs from the selected application")
    root = settings.cursor_lease_root or (
        (settings.deep_agent_sandbox_workspace_root or default_root) / "cursor-leases"
    )
    store = PostgresWorkspaceLeaseStore(pool)
    allocator_ref = GitWorkspaceBackend(root).owner_ref
    outcomes: list[ReleasedBridgeSweepOutcome | ActiveBridgeSweepOutcome] = []

    async def inspect(context: ActiveBridgeContext) -> ActiveDisposition:
        return await inspect_active_cursor_context(context, settings, temporal_client)

    try:
        async with asyncio.timeout(STARTUP_TIMEOUT_S):
            for scope in scopes:
                active = (
                    await sweep_active_cursor_bridges(
                        store,
                        request_scope=scope,
                        root=root,
                        allocator_ref=allocator_ref,
                        inspect=inspect,
                        limit=max(1, 32 // len(scopes)),
                    )
                    if temporal_client is not None
                    else ()
                )
                outcomes.extend(active)
                batch = await sweep_released_cursor_bridges(
                    store,
                    request_scope=scope,
                    root=root,
                    allocator_ref=allocator_ref,
                    shutdown=shutdown_released_bridge,
                    limit=max(1, (32 if temporal_client is not None else 64) // len(scopes)),
                )
                outcomes.extend(batch)
                current: tuple[ActiveBridgeSweepOutcome | ReleasedBridgeSweepOutcome, ...] = (
                    *active,
                    *batch,
                )
                for outcome in current:
                    logger.info(
                        "Cursor bridge recovery lease=%s disposition=%s",
                        outcome.lease_id,
                        outcome.disposition,
                    )
    except TimeoutError:
        logger.warning("Cursor released bridge cleanup deadline reached; cleanup remains pending")
    except Exception:
        # Pool/native errors can contain credentials; fail startup without echoing them.
        raise RuntimeError(
            "Cursor released bridge cleanup failed; inspect private receipts"
        ) from None
    return tuple(outcomes)
