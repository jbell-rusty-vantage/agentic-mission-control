"""Remote launch through the ordinary manifest lifecycle; no ingress scheduler."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindingError
from mission_control.application.authoring.manifest_service import ManifestPermissionDenied
from mission_control.application.authoring.manifest_submit import (
    ManifestBlocked,
    ManifestIdempotencyConflict,
    ManifestSubmitService,
    SubmitRequest,
    TenantNotProvisioned,
)
from mission_control.application.execution.run_launch import RunLaunchRejected
from mission_control.application.signals.drainer import DrainItem, DrainRejected
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.policies.contracts import ActorContext


@dataclass(frozen=True)
class ResolvedLaunch:
    lifecycle: ManifestSubmitService
    actor: ActorContext
    manifest_yaml: str
    sponsorship_refs: frozenset[str]
    approval_refs: frozenset[str] = frozenset()


class LaunchResolver(Protocol):
    async def resolve(self, item: DrainItem) -> ResolvedLaunch:
        """Revalidate credential expiry/revocation, allowed manifest, current grants and scope.

        Bind inputs into the manifest using trusted authoring rules. Payload fields must
        never select credentials, pools, actor grants or runtime bindings.
        """
        ...

    async def preflight(self, launch: ResolvedLaunch) -> None:
        """Mandatory fresh prerequisite verification before any admission write."""
        ...


class RemoteMissionLauncher:
    def __init__(self, resolver: LaunchResolver) -> None:
        self._resolver = resolver

    async def admit(self, item: DrainItem) -> Mapping[str, Any]:
        if item.kind != "mission_request" or item.request_scope is None:
            raise DrainRejected("invalid_launch_scope")
        inputs = item.payload.get("inputs")
        if not isinstance(inputs, dict) or sha256_digest(inputs) != item.payload.get(
            "inputs_digest"
        ):
            raise DrainRejected("inputs_digest_mismatch")
        launch = await self._resolver.resolve(item)
        if launch.lifecycle.request_scope != item.request_scope:
            raise DrainRejected("cross_scope_launch")
        try:
            await self._resolver.preflight(launch)
            receipt, _ = await launch.lifecycle.submit(
                SubmitRequest(
                    manifest_yaml=launch.manifest_yaml,
                    request_id=item.ingress_id,
                    actor=launch.actor,
                    sponsorship_refs=launch.sponsorship_refs,
                    approval_refs=launch.approval_refs,
                )
            )
            # The existing service owns admission, fresh start preflight, outbox and Temporal.
            # A chain remains governed by its own release rules; only its first run starts.
            first = receipt.missions[0]
            if first.run_id is None:
                raise DrainRejected("run_not_admitted")
            try:
                await launch.lifecycle.start(first.run_id, launch.actor)
            except RunLaunchRejected as rejected:
                if rejected.code != "run_not_pending":
                    if rejected.retryable:
                        raise
                    raise DrainRejected("launch_refused") from None
        except ManifestLaunchBindingError:
            raise DrainRejected("launch_binding_unavailable") from None
        except ManifestPermissionDenied:
            raise DrainRejected("launch_unauthorized") from None
        except ManifestIdempotencyConflict:
            raise DrainRejected("launch_idempotency_conflict") from None
        except ManifestBlocked:
            raise DrainRejected("launch_prerequisites_unmet") from None
        except TenantNotProvisioned:
            raise DrainRejected("launch_tenant_not_provisioned") from None
        return {"mission_id": str(first.mission_id)}
