"""Hosted session retention: ordering and carrying out session deletion (SPEC-06 section 8).

A lane whose sessions Mission Control deletes (``claude_managed``, ``codex_agents``) calls
``SessionRetentionService.after_custody`` from ``end_session`` once the session's outputs are in
custody. The service builds the order under the Application's ``SessionRetentionPolicy`` and
hands it to the ``SessionDeletionScheduler``: Temporal alone schedules, so the composed scheduler
starts a durable timer (``mc.hosted_session_retention.v1``) keyed by the order, and ordering the
same session again is the same order. When the timer fires, ``SessionDeletionService`` deletes
the session through the profile's ``HostedSessionDeleter`` (the lane's provider client). A
session the provider no longer has counts as deleted; any other failure is retried by the
workflow, so a session is never forgotten undeleted.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Literal, Protocol

from mission_control.domain.execution.lanes import LaneProfileName
from mission_control.domain.execution.session_retention import (
    DEFAULT_SESSION_RETENTION_POLICY,
    SESSION_DELETED_PROFILES,
    SessionDeletion,
    SessionRetentionPolicy,
)

SessionDeletionOutcome = Literal["deleted", "absent"]


class SessionDeletionScheduler(Protocol):
    """Durably schedules one deletion; idempotent on ``SessionDeletion.key``."""

    async def schedule(self, deletion: SessionDeletion) -> None: ...


class HostedSessionDeleter(Protocol):
    """Deletes one provider session; ``absent`` when the provider no longer has it."""

    async def delete_session(self, session_ref: str) -> SessionDeletionOutcome: ...


class SessionDeleterUnavailable(LookupError):
    """No deleter is composed for the order's lane profile (retried until one is)."""


class SessionRetentionService:
    """Orders the deletion of a session whose outputs are in custody."""

    def __init__(
        self,
        scheduler: SessionDeletionScheduler,
        *,
        policy: SessionRetentionPolicy = DEFAULT_SESSION_RETENTION_POLICY,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._scheduler = scheduler
        self._policy = policy
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def policy(self) -> SessionRetentionPolicy:
        return self._policy

    async def after_custody(
        self, *, lane_profile: LaneProfileName, request_scope: str, session_ref: str
    ) -> SessionDeletion | None:
        """Schedule the session's deletion (None: the profile's sessions are not deleted)."""

        deletion = self._policy.deletion(
            lane_profile=lane_profile,
            request_scope=request_scope,
            session_ref=session_ref,
            custody_at=self._clock(),
        )
        if deletion is not None:
            await self._scheduler.schedule(deletion)
        return deletion


class SessionDeletionService:
    """Carries out a due deletion through the profile's provider deleter."""

    def __init__(self, deleters: Mapping[LaneProfileName, HostedSessionDeleter]) -> None:
        stray = sorted(set(deleters) - SESSION_DELETED_PROFILES)
        if stray:
            raise ValueError(f"sessions of {', '.join(stray)} are not deleted by Mission Control")
        self._deleters = MappingProxyType(dict(deleters))

    async def delete(self, deletion: SessionDeletion) -> SessionDeletionOutcome:
        deleter = self._deleters.get(deletion.lane_profile)
        if deleter is None:
            raise SessionDeleterUnavailable(
                f"no session deleter is composed for lane profile {deletion.lane_profile}"
            )
        return await deleter.delete_session(deletion.session_ref)


__all__ = [
    "HostedSessionDeleter",
    "SessionDeleterUnavailable",
    "SessionDeletionOutcome",
    "SessionDeletionScheduler",
    "SessionDeletionService",
    "SessionRetentionService",
]
