"""Auto-subscribe the launcher of a run to its coordinator inbox (SPEC-04 §6, ADR-0049).

ADR-0032 promised that a coordinator is subscribed when it starts a run; this is that hook.
Every launch through the operator API (HTTP, CLI and the authenticated MCP) registers, for the
launching actor, a durable coordinator inbox over the run with the default coordinator
profile, **before** the launch, so even a run that finishes at once is materialized after the
inbox cursor and wakes `missionctl wait`. The launch may opt out with ``notify: none``.

The hook is idempotent (a repeated start reuses the actor's open inbox) and never decides the
launch: an absent inbox service or a launcher without the read grant is reported, not raised.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from mission_control.application.subscriptions.coordinator import CoordinatorContract
from mission_control.application.subscriptions.coordinator_service import (
    CoordinatorInboxService,
    CoordinatorRejected,
    CoordinatorSubscribeRequest,
)
from mission_control.domain.policies.contracts import ActorContext

LaunchNotify = Literal["inbox", "none"]


class LauncherInbox(CoordinatorContract):
    """`coordinator_inbox` on a launch receipt: where the launcher is woken, if anywhere."""

    status: Literal["subscribed", "existing", "off", "unavailable"]
    subscription_id: UUID | None = None
    reason: str | None = None


async def subscribe_launcher(
    inboxes: CoordinatorInboxService | None,
    run_id: str,
    actor: ActorContext,
    *,
    notify: LaunchNotify = "inbox",
) -> LauncherInbox:
    """Ensure the launching actor's inbox over ``run_id`` (call before the launch)."""

    if notify == "none":
        return LauncherInbox(status="off")
    if inboxes is None:
        return LauncherInbox(status="unavailable", reason="coordinator inboxes are not composed")
    try:
        run = UUID(run_id)
    except ValueError:
        return LauncherInbox(status="unavailable", reason="the run id is not a run uuid")
    try:
        inbox, created = await inboxes.ensure(
            CoordinatorSubscribeRequest(target="run", target_id=run), actor
        )
    except CoordinatorRejected as rejected:
        return LauncherInbox(status="unavailable", reason=rejected.code)
    return LauncherInbox(
        status="subscribed" if created else "existing", subscription_id=inbox.subscription_id
    )


__all__ = ["LaunchNotify", "LauncherInbox", "subscribe_launcher"]
