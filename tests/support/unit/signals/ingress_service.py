"""Builders, constants and fakes that other test files import.

Moved from tests/unit/signals/test_ingress_service.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from mission_control.application.capabilities.bundle_custody import SignedUpload
from mission_control.application.signals.contracts import IngressRejected, TrustTier
from mission_control.application.signals.ports import (
    AcceptOutcome,
    ArtifactSlotOutcome,
    GateCall,
    GateOutcome,
    InboxItem,
    OidcIdentity,
    Principal,
    RequestOutcome,
    RequestStatusOutcome,
)
from mission_control.application.signals.service import IngressKeys, SignalIngressService

TOKEN = "mct_" + "t" * 43
MASTER = b"env-master"


@dataclass
class FakeStore:
    application_id: str = "biotech"
    outcome: str = "accepted"
    calls: list[tuple[str, Principal, Any]] = field(default_factory=list)

    async def accept(self, principal: Principal, items: Sequence[InboxItem]) -> AcceptOutcome:
        self.calls.append(("accept", principal, list(items)))
        return AcceptOutcome(self.outcome, len(items) if self.outcome == "accepted" else 0, 0)

    async def gate(self, principal: Principal, call: GateCall) -> GateOutcome:
        self.calls.append(("gate", principal, call))
        if self.outcome != "accepted":
            return GateOutcome(self.outcome)
        return GateOutcome("decided", "deny", "disallowed_tool")

    async def webhook(self, provider: str, route_ref: str | None, item: InboxItem) -> str:
        self.calls.append(("webhook", Principal(TrustTier.PROVIDER_SIGNED, provider), item))
        return self.outcome

    async def prepare_artifact(
        self, principal: Principal, artifact_upload_id: UUID, **declared: Any
    ) -> ArtifactSlotOutcome:
        self.calls.append(("prepare", principal, declared))
        return ArtifactSlotOutcome(
            "prepared", artifact_upload_id, "biotech/run/abc", datetime(2026, 10, 13, tzinfo=UTC)
        )

    async def commit_artifact(
        self, principal: Principal, ingress_id: UUID, artifact_upload_id: UUID
    ) -> RequestOutcome:
        return RequestOutcome("committed", ingress_id)

    async def request_mission(
        self, principal: Principal, item: InboxItem, *, manifest_ref: str
    ) -> RequestOutcome:
        self.calls.append(("request", principal, item))
        return RequestOutcome(self.outcome, item.ingress_id)

    async def mission_request_status(
        self, principal: Principal, request_id: UUID
    ) -> RequestStatusOutcome:
        return RequestStatusOutcome("found", "refused", None, "spawn_grant_missing", None)


class Oidc:
    async def verify(self, token: str) -> OidcIdentity:
        if token != "eyJ.cursor.jwt":
            raise IngressRejected(401, "invalid_token")
        return OidcIdentity(provider="cursor", session_id="bc-1")


class Uploads:
    async def signed_upload(self, storage_key: str) -> SignedUpload:
        return SignedUpload(path=storage_key, url=f"https://storage.test/{storage_key}")


def service(store: FakeStore, **kwargs: Any) -> SignalIngressService:
    return SignalIngressService(
        store,
        keys=IngressKeys(environment_key_master=MASTER, webhook_secrets={"github": "gh"}),
        oidc=Oidc(),
        uploads=Uploads(),
        **kwargs,
    )
