"""Hosted session retention: when a provider session is deleted (SPEC-06 section 8).

Neither hosted agent API is ZDR-eligible (DECISIONS C3): a Managed Agents transcript persists
until it is deleted, and an Agents API session's application state is retained until deleted
(research/anthropic-managed-agents.md section 7, research/openai-hosted-agents.md section 6). So
every ``claude_managed`` and ``codex_agents`` session is deleted once its outputs are in custody
and the Application's retention interval has passed. The interval keeps the provider record
readable for a late reconcile or a fork's seed, and no longer. A deletion is ordered only after
custody, never in place of it; a profile outside ``SESSION_DELETED_PROFILES`` (Cursor archives
its agents, the local lanes own their sessions) is never ordered.

The default interval matches the development Temporal namespace's history retention (DECISIONS
R20, 7 days), so a session is deleted no later than the workflow history that refers to it.
An Application Binding may shorten or lengthen it.

Pure: a lane profile, the session, the custody time and the policy in, an order or nothing out.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from mission_control.domain.execution.lanes import HOSTED_AGENT_API_PROFILES, LaneProfileName

SESSION_DELETED_PROFILES: Final[frozenset[LaneProfileName]] = HOSTED_AGENT_API_PROFILES
DEFAULT_SESSION_RETENTION: Final = timedelta(days=7)


class SessionDeletion(BaseModel):
    """The order to delete one provider session once ``delete_after`` has passed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_profile: LaneProfileName
    request_scope: str = Field(min_length=1)
    session_ref: str = Field(min_length=1, max_length=1_024)
    custody_at: AwareDatetime
    delete_after: AwareDatetime

    @property
    def key(self) -> str:
        """One order per session under its tenant scope; ordering it again is the same order."""

        return f"{self.request_scope}:{self.lane_profile}:{self.session_ref}"


class SessionRetentionPolicy(BaseModel):
    """How long a deleted profile's session outlives the custody of its outputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    retention: timedelta = DEFAULT_SESSION_RETENTION

    @field_validator("retention")
    @classmethod
    def _not_negative(cls, value: timedelta) -> timedelta:
        if value < timedelta(0):
            raise ValueError("a session retention interval cannot be negative")
        return value

    def deletion(
        self,
        *,
        lane_profile: LaneProfileName,
        request_scope: str,
        session_ref: str,
        custody_at: AwareDatetime,
    ) -> SessionDeletion | None:
        """The deletion order of a session whose outputs entered custody at ``custody_at``,
        or ``None`` for a profile whose sessions Mission Control does not delete."""

        if lane_profile not in SESSION_DELETED_PROFILES:
            return None
        return SessionDeletion(
            lane_profile=lane_profile,
            request_scope=request_scope,
            session_ref=session_ref,
            custody_at=custody_at,
            delete_after=custody_at + self.retention,
        )


DEFAULT_SESSION_RETENTION_POLICY: Final = SessionRetentionPolicy()

__all__ = [
    "DEFAULT_SESSION_RETENTION",
    "DEFAULT_SESSION_RETENTION_POLICY",
    "SESSION_DELETED_PROFILES",
    "SessionDeletion",
    "SessionRetentionPolicy",
]
