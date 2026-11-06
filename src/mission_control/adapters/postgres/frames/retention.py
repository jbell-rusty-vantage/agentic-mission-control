"""Native Event Store retention (SPEC-03 "Retention"; TRACING-PROPOSAL §P8a, TR-D1).

`mission_control.frame_retention_policy` holds one row per application (absent = the
defaults: 30 days, keep closing frames, 8 KiB excerpt cap, no step retention, `delete`).
Since release 1.4.4 a frame carries a generated `retention_class`:

- `delta` (`message_delta`, `thinking_delta`, `tool_call_delta`, `heartbeat`, `status`):
  `expire` deletes them, within one tenant scope, once observed before `now - retain_days`
  (`expire_provider_frames`, narrowed to the class; deltas never close, so
  `keep_closing_frames` is honoured for compatibility only).
- `step` (every other frame): kept for the mission's evidence life. Only when the
  application set `step_retain_days` does `expire` also run
  `expire_step_provider_frames(now - step_retain_days)`, which deletes step frames of
  terminal (`lifecycle = 'completed'`) runs only; pins arrive with TR-D17.
- `prune_mode = 'tombstone'` is reserved for TR-D17: until the tombstone writer exists the
  step clock prunes nothing in that mode (`expired_step = 0`), never deletes.

Mission events are never touched; a transcript rendered after expiry shows `expired`
placeholders on the deleted deltas and every step frame stays (FX-TR-RETAIN).

Tracing Stage 3 (R4-F1, R4-F2), without a schema change:

- The persisted projection is the record of what retention deleted (`keep_expired` turns the
  deleted frames it holds into placeholders), so a run's frames are deleted only once its
  projection is current. Before the delete, `expire` projects every run with expiring frames
  whose projection is behind (the composed `projectors`, the maintenance worker's
  `transcript.project` projectors). A run still not current (no projectors, a failed pass)
  is excluded: the cutoff is lowered below its oldest expiring frame, which the expiry
  functions' single cutoff allows (`skipped_unprojected` counts those runs; the other runs'
  older frames still go).
- In the delete transaction, before the delete, each covered run's projection is
  invalidated: its `transcript_projection_state` row is deleted (the rows holding the
  deleted bodies are never served as current again) and one `transcript_projection` outbox
  intent (`transcript-projection:{run}:expire:{cutoff}`) re-projects it with placeholders.
  The frame count in the marks guards the same rule for any other deletion path.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

import asyncpg

from mission_control.adapters.postgres.frames.transcript_entries import (
    insert_transcript_projection_intent,
    projection_is_current,
)
from mission_control.adapters.postgres.run_control.canonical import SCOPE, advisory_lock, begin
from mission_control.application.frames.projection_trigger import transcript_projection_intent
from mission_control.domain.frames.contracts import DEFAULT_EXCERPT_CAP_BYTES

_LOG = logging.getLogger(__name__)

DEFAULT_RETAIN_DAYS = 30
MIN_STEP_RETAIN_DAYS = 30

PruneMode = Literal["delete", "tombstone"]


@dataclass(frozen=True)
class FrameRetentionPolicy:
    retain_days: int = DEFAULT_RETAIN_DAYS
    """The delta clock (TR-D1)."""
    keep_closing_frames: bool = True
    excerpt_cap_bytes: int = DEFAULT_EXCERPT_CAP_BYTES
    step_retain_days: int | None = None
    """The step clock; ``None`` is the mission's evidence life (step frames never expire)."""
    prune_mode: PruneMode = "delete"
    """Reserved for TR-D17 (`tombstone`: the row stays, the body goes, `body_state: pruned`)."""

    def __post_init__(self) -> None:
        if self.retain_days < 1:
            raise ValueError("retain_days must be at least 1 day")
        if self.step_retain_days is not None and self.step_retain_days < MIN_STEP_RETAIN_DAYS:
            raise ValueError(f"step_retain_days must be at least {MIN_STEP_RETAIN_DAYS} days")
        if self.prune_mode not in ("delete", "tombstone"):
            raise ValueError("prune_mode is 'delete' or 'tombstone'")


@dataclass(frozen=True)
class FrameExpiryReport:
    request_scope: str
    cutoff: datetime
    """The delta cutoff (``now - retain_days``)."""
    deleted_non_closing: int
    deleted_closing: int
    policy: FrameRetentionPolicy
    expired_delta: int = 0
    """Delta-class frames deleted by ``retain_days``."""
    expired_step: int = 0
    """Step-class frames of terminal runs deleted by ``step_retain_days`` (0 when unset)."""
    step_cutoff: datetime | None = None
    skipped_unprojected: int = 0
    """Runs whose expiring frames were kept: their projection could not be made current
    (Tracing Stage 3, R4-F2); the next pass tries again."""
    expired_closures: int = 0
    """OVE-204 slice 5: Workspace Closures of completed runs past their `retain_until`
    (rows only; the content-addressed payload bytes stay)."""
    invalidated_projections: int = 0
    """Runs whose projection the expiry invalidated and re-queued (R4-F1)."""


class RunProjector(Protocol):
    """What `expire` needs of `transcript.project`'s projector (`TranscriptProjector`)."""

    async def project(self, run_key: str) -> object: ...


@dataclass(frozen=True, slots=True)
class _ExpiringRun:
    run_id: UUID
    run_key: str
    oldest_delta: datetime | None = None
    oldest_step: datetime | None = None


def retention_cutoffs(
    policy: FrameRetentionPolicy, now: datetime
) -> tuple[datetime, datetime | None]:
    """``(delta_cutoff, step_cutoff)``; the step cutoff is ``None`` unless the policy set it."""

    if now.tzinfo is None:
        raise ValueError("expiry clock must be timezone-aware")
    delta = now - timedelta(days=policy.retain_days)
    step = (
        now - timedelta(days=policy.step_retain_days)
        if policy.step_retain_days is not None
        else None
    )
    return delta, step


async def _policy(connection: asyncpg.Connection, args: tuple[object, ...]) -> FrameRetentionPolicy:
    row = await connection.fetchrow(
        """
        SELECT retain_days, keep_closing_frames, excerpt_cap_bytes, step_retain_days, prune_mode
        FROM mission_control.frame_retention_policy
        WHERE installation_id = $1 AND application_id = $2
        """,
        args[0],
        args[1],
    )
    if row is None:
        return FrameRetentionPolicy()
    step = row["step_retain_days"]
    return FrameRetentionPolicy(
        retain_days=int(row["retain_days"]),
        keep_closing_frames=bool(row["keep_closing_frames"]),
        excerpt_cap_bytes=int(row["excerpt_cap_bytes"]),
        step_retain_days=int(step) if step is not None else None,
        prune_mode="tombstone" if row["prune_mode"] == "tombstone" else "delete",
    )


async def _expiring_runs(
    connection: asyncpg.Connection,
    args: tuple[object, ...],
    cutoff: datetime,
    step_cutoff: datetime | None,
) -> dict[UUID, _ExpiringRun]:
    """The runs with frames the expiry functions would delete at these cutoffs, with the
    oldest such frame per class (the same predicates as `expire_provider_frames` and
    `expire_step_provider_frames`)."""

    runs: dict[UUID, _ExpiringRun] = {}
    deltas = await connection.fetch(
        """
        SELECT f.run_id, r.run_key, min(f.observed_at) AS oldest
        FROM mission_control.provider_frame AS f
        JOIN mission_control.mission_run AS r
          ON r.installation_id = f.installation_id AND r.application_id = f.application_id
         AND r.tenant_id = f.tenant_id AND r.run_id = f.run_id
        WHERE f.installation_id = $1 AND f.application_id = $2 AND f.tenant_id = $3
          AND f.retention_class = 'delta' AND f.observed_at < $4
        GROUP BY f.run_id, r.run_key
        """,
        *args,
        cutoff,
    )
    for row in deltas:
        runs[row["run_id"]] = _ExpiringRun(
            row["run_id"], row["run_key"], oldest_delta=row["oldest"]
        )
    if step_cutoff is None:
        return runs
    steps = await connection.fetch(
        """
        SELECT f.run_id, r.run_key, min(f.observed_at) AS oldest
        FROM mission_control.provider_frame AS f
        JOIN mission_control.mission_run AS r
          ON r.installation_id = f.installation_id AND r.application_id = f.application_id
         AND r.tenant_id = f.tenant_id AND r.run_id = f.run_id
        WHERE f.installation_id = $1 AND f.application_id = $2 AND f.tenant_id = $3
          AND r.lifecycle = 'completed' AND f.retention_class = 'step' AND f.observed_at < $4
        GROUP BY f.run_id, r.run_key
        """,
        *args,
        step_cutoff,
    )
    for row in steps:
        known = runs.get(row["run_id"])
        runs[row["run_id"]] = _ExpiringRun(
            row["run_id"],
            row["run_key"],
            oldest_delta=known.oldest_delta if known is not None else None,
            oldest_step=row["oldest"],
        )
    return runs


def _below(cutoff: datetime, oldest: list[datetime | None]) -> datetime:
    """The cutoff lowered so no frame at or after any `oldest` is deleted (R4-F2)."""

    return min([cutoff, *(item for item in oldest if item is not None)])


class PostgresFrameRetention:
    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        actor_ref: str = "mission-control-frames-expire",
        projectors: Callable[[str], RunProjector] | None = None,
    ) -> None:
        self._pool = pool
        self._actor = actor_ref
        self._projectors = projectors

    async def policy(self, request_scope: str) -> FrameRetentionPolicy:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            return await _policy(connection, args)

    async def set_policy(self, request_scope: str, policy: FrameRetentionPolicy) -> None:
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            await connection.execute(
                """
                INSERT INTO mission_control.frame_retention_policy (
                    installation_id, application_id, retain_days, keep_closing_frames,
                    excerpt_cap_bytes, step_retain_days, prune_mode, version, updated_at,
                    created_at, created_by_actor_ref
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, 1, clock_timestamp(), clock_timestamp(), $8)
                ON CONFLICT (installation_id, application_id) DO UPDATE
                SET retain_days = EXCLUDED.retain_days,
                    keep_closing_frames = EXCLUDED.keep_closing_frames,
                    excerpt_cap_bytes = EXCLUDED.excerpt_cap_bytes,
                    step_retain_days = EXCLUDED.step_retain_days,
                    prune_mode = EXCLUDED.prune_mode,
                    version = mission_control.frame_retention_policy.version + 1,
                    updated_at = EXCLUDED.updated_at
                """,
                args[0],
                args[1],
                policy.retain_days,
                policy.keep_closing_frames,
                policy.excerpt_cap_bytes,
                policy.step_retain_days,
                policy.prune_mode,
                self._actor,
            )

    async def _project_behind(
        self, request_scope: str, cutoff: datetime, step: datetime | None
    ) -> None:
        """Tracing Stage 3 (R4-F2): bring the projection of every run about to lose frames
        up to date first, so the deleted frames stay in the Transcript as placeholders."""

        if self._projectors is None:
            return
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            runs = await _expiring_runs(connection, args, cutoff, step)
            behind = [
                run.run_key
                for run in runs.values()
                if not await projection_is_current(connection, args, run.run_id)
            ]
        if not behind:
            return
        projector = self._projectors(request_scope)
        for run_key in behind:
            try:
                await projector.project(run_key)
            except Exception as error:  # the run is excluded below; the next pass retries
                _LOG.warning(
                    "frames.expire kept the frames of %s: its projection failed (%s)",
                    run_key,
                    error,
                )

    async def expire(self, request_scope: str, *, now: datetime) -> FrameExpiryReport:
        if now.tzinfo is None:
            raise ValueError("expiry clock must be timezone-aware")
        policy = await self.policy(request_scope)
        cutoff, step_cutoff = retention_cutoffs(policy, now)
        step_clock = step_cutoff if policy.prune_mode == "delete" else None
        await self._project_behind(request_scope, cutoff, step_clock)
        async with self._pool.acquire() as connection, connection.transaction():
            args = await begin(connection, request_scope)
            runs = await _expiring_runs(connection, args, cutoff, step_clock)
            covered: list[_ExpiringRun] = []
            uncovered: list[_ExpiringRun] = []
            # One lock order (by run id) so two passes never deadlock; `replace` holds one.
            for run in sorted(runs.values(), key=lambda item: item.run_id):
                await advisory_lock(connection, f"transcript-projection:{run.run_id}")
                current = await projection_is_current(connection, args, run.run_id)
                (covered if current else uncovered).append(run)
            # R4-F2: a run whose projection is not current keeps every expiring frame.
            delta_cutoff = _below(cutoff, [run.oldest_delta for run in uncovered])
            step_cut = (
                _below(step_clock, [run.oldest_step for run in uncovered])
                if step_clock is not None
                else None
            )
            touched = [
                run
                for run in covered
                if (run.oldest_delta is not None and run.oldest_delta < delta_cutoff)
                or (
                    step_cut is not None
                    and run.oldest_step is not None
                    and run.oldest_step < step_cut
                )
            ]
            # R4-F1: before the delete, the projection of every run it touches stops being
            # served (the state row goes) and is re-queued (one outbox intent per pass).
            for run in touched:
                await connection.execute(
                    f"DELETE FROM mission_control.transcript_projection_state "
                    f"WHERE {SCOPE} AND run_id = $4",
                    *args,
                    run.run_id,
                )
                await insert_transcript_projection_intent(
                    connection,
                    args,
                    transcript_projection_intent(
                        request_scope=request_scope,
                        run_key=run.run_key,
                        settlement_id=f"expire:{cutoff.isoformat()}",
                    ),
                    # The wall clock, not the expiry clock: the relay leases due intents.
                    at=datetime.now(UTC),
                    actor_ref=self._actor,
                )
            # Scope comes from the transaction context `begin` set; the definer functions
            # are the only path that deletes frames (no role holds DELETE on the table).
            rows = await connection.fetch(
                """
                SELECT expired_closing
                FROM mission_control.expire_provider_frames($1, $2)
                """,
                delta_cutoff,
                policy.keep_closing_frames,
            )
            expired_step = 0
            if step_cut is not None:
                step_rows = await connection.fetch(
                    """
                    SELECT expired_frame_id
                    FROM mission_control.expire_step_provider_frames($1)
                    """,
                    step_cut,
                )
                expired_step = len(step_rows)
            # OVE-204 slice 5: closures carry their own clock (`retain_until`, NULL = the
            # mission's evidence life); the definer deletes only completed runs' rows.
            closure_rows = await connection.fetch(
                """
                SELECT expired_closure_id
                FROM mission_control.expire_workspace_closures($1)
                """,
                now,
            )
        if uncovered:
            _LOG.warning(
                "frames.expire kept the expiring frames of %d run(s) without a current "
                "projection in %s",
                len(uncovered),
                request_scope,
            )
        closing = sum(1 for row in rows if row["expired_closing"])
        return FrameExpiryReport(
            request_scope=request_scope,
            cutoff=cutoff,
            deleted_non_closing=len(rows) - closing,
            deleted_closing=closing,
            policy=policy,
            expired_delta=len(rows),
            expired_step=expired_step,
            step_cutoff=step_cutoff,
            skipped_unprojected=len(uncovered),
            invalidated_projections=len(touched),
            expired_closures=len(closure_rows),
        )


__all__ = [
    "DEFAULT_RETAIN_DAYS",
    "MIN_STEP_RETAIN_DAYS",
    "FrameExpiryReport",
    "FrameRetentionPolicy",
    "PostgresFrameRetention",
    "PruneMode",
    "RunProjector",
    "retention_cutoffs",
]
