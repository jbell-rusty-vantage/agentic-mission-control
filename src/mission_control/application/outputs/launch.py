"""Register a run's admitted named promises at launch (WI-01 gap, OVE-166; used by WI-02).

The admitted blueprint names the run's ``output_promises`` (the configuration copies them from
it); before the run's root is submitted, every launch route registers exactly those promises
(revision 1 of each, the admitted completion) through
:meth:`OutputFulfillmentService.register_promises`. Registration is idempotent: a relaunch with
the same set is a no-op, a different set refuses the launch.
"""

from __future__ import annotations

from mission_control.application.execution.run_launch import RunLaunchRejected
from mission_control.application.outputs.fulfillment import HostAccess, OutputFulfillmentService
from mission_control.domain.outputs.contracts import OutputError, OutputPromiseSet

LAUNCH_ACTOR = "mission-control:launch"


class LaunchPromiseRegistrar:
    """``(request_scope, run_id, configuration_digest) -> None``; refuses typed on a conflict."""

    def __init__(self, outputs: OutputFulfillmentService) -> None:
        self._outputs = outputs

    async def __call__(
        self,
        request_scope: str,
        run_id: str,
        configuration_digest: str,
        promises: OutputPromiseSet,
    ) -> None:
        registered = await self._outputs.register_promises(
            HostAccess(scope=request_scope, actor_ref=LAUNCH_ACTOR, origin_ref="mc-host:launch"),
            run_id,
            promises,
            configuration_digest=configuration_digest,
        )
        if isinstance(registered, OutputError):
            raise RunLaunchRejected(
                "promises_refused", f"{registered.code}: {registered.safe_message}"
            )


__all__ = ["LaunchPromiseRegistrar"]
