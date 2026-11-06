"""Deleting a remote session after custody (SPEC-06 section 8; `application.execution.harness.
retention`).

A Remote Session Lane composes one `ProviderSessionRetention` beside its
`ProviderWorkspaceCustody` and calls `after_custody` at the end of `end_session`, once the
patch, the artifacts and the branch head are in custody (and after `archive` where the provider
has one). A lane whose sessions Mission Control deletes cannot be composed without retention:
an undeleted transcript on a non-ZDR provider is the failure this guards, so it fails closed
at composition rather than at the end of a mission. A lane that ends without a native session
(nothing was created) orders nothing.
"""

from __future__ import annotations

from mission_control.application.execution.harness.lane_turns import LaneExecutionIdentity
from mission_control.application.execution.harness.retention import SessionRetentionService
from mission_control.domain.execution.lanes import LaneProfileName
from mission_control.domain.execution.session_retention import (
    SESSION_DELETED_PROFILES,
    SessionDeletion,
)


class ProviderSessionRetention:
    """The session deletion order of one lane profile, when its sessions are deleted."""

    def __init__(
        self, retention: SessionRetentionService | None, *, lane_profile: LaneProfileName
    ) -> None:
        if retention is None and lane_profile in SESSION_DELETED_PROFILES:
            raise ValueError(
                f"lane profile {lane_profile} is not ZDR-eligible: its sessions must be deleted "
                "after custody, so it needs a session retention service"
            )
        self._retention = retention
        self._lane_profile = lane_profile

    async def after_custody(
        self, identity: LaneExecutionIdentity, session_ref: str | None
    ) -> SessionDeletion | None:
        """Schedule the deletion of the session whose outputs are now in custody."""

        if self._retention is None or session_ref is None:
            return None
        return await self._retention.after_custody(
            lane_profile=self._lane_profile,
            request_scope=identity.request_scope,
            session_ref=session_ref,
        )


__all__ = ["ProviderSessionRetention"]
