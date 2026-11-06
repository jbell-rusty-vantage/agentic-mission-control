"""The Signal Ingress service: verify the caller, record what it sent (SPEC-10; ADR-0045).

One service per application. Each request is verified here (bearer digest, Cursor OIDC,
environment-key HMAC with session binding, provider webhook signatures), its body is
size-capped, parsed into a strict contract and redacted, and it becomes exactly one store call
(one SQL round trip). Authority stays in SQL: whether a credential is live, which run it binds,
duplicates, rate windows and the gate answer are all decided by the 0035 functions. Nothing
here signals Temporal or writes a frame; the worker's IngressDrainer turns inbox rows into
frames, reconciliations and admissions.

Signals are evidence, never authority: a payload is stored redacted as untrusted data. The
run nonce a `session.started` signal presents to bind an `environment_key` session is hashed
and removed before anything is stored. A Managed Agents or Agents API webhook is stored only
as the `ProviderWake` it names (`wake.py`), so the worker must re-read the provider.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ValidationError

from mission_control.application.secrets.minting import TOKEN_PATTERN, token_digest
from mission_control.application.signals.contracts import (
    ArtifactCommitRequest,
    ArtifactPrepareRequest,
    ArtifactUploadSlot,
    GateAnswer,
    GateRequest,
    IngressRejected,
    MissionRequest,
    MissionRequestStatus,
    Signal,
    SignalBatch,
    SignalReceipt,
    TrustTier,
)
from mission_control.application.signals.ports import (
    GateCall,
    InboxItem,
    IngressStore,
    Principal,
    ProviderOidcVerifier,
    QuarantineUploads,
)
from mission_control.application.signals.verification import (
    CURSOR_WEBHOOK_PURPOSE,
    ENVIRONMENT_KEY_PURPOSE,
    bearer_token,
    derive_secret,
    verify_environment_signature,
    verify_hex_signature,
    verify_standard_webhook,
)
from mission_control.application.signals.wake import provider_wake
from mission_control.application.watchers.sources import cursor_status_signal, github_signal
from mission_control.contracts.identities import uuid7
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.frames.body import frame_body

RUN_NONCE_FIELD: Final = "run_nonce"
STANDARD_WEBHOOK_PROVIDERS: Final = frozenset({"anthropic", "openai"})
WEBHOOK_PROVIDERS: Final = frozenset({*STANDARD_WEBHOOK_PROVIDERS, "cursor", "github"})

_STATUS: Final[Mapping[str, int]] = {
    **dict.fromkeys(
        (
            "missing_credential",
            "invalid_token",
            "invalid_signature",
            "stale_timestamp",
            "unknown",
            "unbound_session",
            "expired",
            "revoked",
        ),
        401,
    ),
    **dict.fromkeys(
        (
            "wrong_purpose",
            "wrong_tier",
            "wrong_environment",
            "insufficient_scope",
            "tier_not_allowed",
            "manifest_not_allowed",
        ),
        403,
    ),
    **dict.fromkeys(
        ("not_found", "unknown_provider", "unknown_installation", "unknown_application"), 404
    ),
    **dict.fromkeys(("artifact_already_committed", "dedupe_conflict"), 409),
    "expired_upload": 410,
    "payload_too_large": 413,
    **dict.fromkeys(("invalid_batch", "invalid_item", "invalid_body"), 422),
    "rate_limited": 429,
}


def rejection(code: str) -> IngressRejected:
    """The typed refusal for a store or verification outcome (500 for one not listed)."""

    return IngressRejected(_STATUS.get(code, 500), code)


@dataclass(frozen=True)
class IngressKeys:
    """Signing material the edge verifies with. Masters derive per-environment and per-run
    keys (`derive_secret`); webhook secrets are per provider (`anthropic`, `openai`,
    `github`). Values never appear in a repr."""

    environment_key_master: bytes | None = field(default=None, repr=False)
    cursor_webhook_master: bytes | None = field(default=None, repr=False)
    webhook_secrets: Mapping[str, str] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class IngressLimits:
    max_signal_bytes: int = 262_144
    max_batch_bytes: int = 1_048_576
    max_webhook_bytes: int = 1_048_576
    upload_ttl_seconds: int = 900


def _parse(model: type[BaseModel], body: bytes) -> Any:
    try:
        return model.model_validate_json(body)
    except ValidationError:
        raise rejection("invalid_body") from None


def _stored_bytes(payload: Mapping[str, Any]) -> int:
    """The payload's size as SQL caps it: `octet_length(payload::text)`, whose jsonb text puts
    a space after every `:` and `,` (larger than the compact canonical body). A number jsonb
    prints longer can still exceed it there; SQL then answers `payload_too_large` too."""

    return len(json.dumps(payload, ensure_ascii=False, separators=(", ", ": ")).encode())


def _redacted(document: Mapping[str, Any], cap: int) -> tuple[str, dict[str, Any]]:
    """The digest and payload of a redacted canonical document within `cap` bytes as stored."""

    body = frame_body(document)
    payload: dict[str, Any] = json.loads(body.canonical)
    if _stored_bytes(payload) > cap:
        raise rejection("payload_too_large")
    return body.digest, payload


class SignalIngressService:
    def __init__(
        self,
        store: IngressStore,
        *,
        keys: IngressKeys,
        oidc: ProviderOidcVerifier | None = None,
        uploads: QuarantineUploads | None = None,
        limits: IngressLimits | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._keys = keys
        self._oidc = oidc
        self._uploads = uploads
        self._limits = limits or IngressLimits()
        self._clock = clock

    @property
    def application_id(self) -> str:
        return self._store.application_id

    @property
    def limits(self) -> IngressLimits:
        return self._limits

    # --- principals ----------------------------------------------------------------------

    async def _principal(
        self, headers: Mapping[str, str], body: bytes, *, gating: bool
    ) -> Principal:
        if "x-mc-signature" in headers:
            if gating:
                raise rejection("tier_not_allowed")
            return self._environment_principal(headers, body)
        token = bearer_token(headers.get("authorization"))
        if token is None:
            raise rejection("missing_credential")
        if TOKEN_PATTERN.fullmatch(token):
            return Principal(TrustTier.RUN_TOKEN, token_digest(token))
        if self._oidc is None:
            raise rejection("invalid_token")
        identity = await self._oidc.verify(token)
        return Principal(
            TrustTier.PROVIDER_OIDC,
            identity.session_id,
            provider=identity.provider,
            environment_ref=identity.environment_ref,
        )

    def _environment_principal(self, headers: Mapping[str, str], body: bytes) -> Principal:
        master = self._keys.environment_key_master
        if master is None:
            raise IngressRejected(503, "environment_key_unavailable")
        provider = headers.get("x-mc-provider")
        environment = headers.get("x-mc-environment")
        session = headers.get("x-mc-session")
        if not provider or not environment or not session:
            raise rejection("missing_credential")
        key = derive_secret(
            master, ENVIRONMENT_KEY_PURPOSE, f"{self.application_id}/{provider}/{environment}"
        )
        verify_environment_signature(
            key,
            timestamp=headers.get("x-mc-timestamp"),
            signature=headers.get("x-mc-signature"),
            body=body,
            now=self._clock(),
        )
        return Principal(
            TrustTier.ENVIRONMENT_KEY, session, provider=provider, environment_ref=environment
        )

    def _launch_principal(self, headers: Mapping[str, str]) -> Principal:
        token = bearer_token(headers.get("authorization"))
        if token is None:
            raise rejection("missing_credential")
        if not TOKEN_PATTERN.fullmatch(token):
            raise rejection("invalid_token")
        return Principal(TrustTier.LAUNCH_TOKEN, token_digest(token))

    def _cap(self, body: bytes, limit: int) -> None:
        if len(body) > limit:
            raise rejection("payload_too_large")

    # --- signals and gates -----------------------------------------------------------------

    async def signals(self, body: bytes, headers: Mapping[str, str]) -> SignalReceipt:
        """`POST signals`: one signal or a batch; duplicates are counted, never refused."""

        self._cap(body, self._limits.max_batch_bytes)
        principal = await self._principal(headers, body, gating=False)
        try:
            document = json.loads(body)
        except ValueError:
            raise rejection("invalid_body") from None
        batch = isinstance(document, dict) and "signals" in document
        signals = _parse(SignalBatch, body).signals if batch else (_parse(Signal, body),)
        items: list[InboxItem] = []
        nonce_hash: str | None = None
        for signal in signals:
            data = dict(signal.data)
            nonce = data.pop(RUN_NONCE_FIELD, None)
            if signal.type == "session.started" and isinstance(nonce, str) and nonce:
                nonce_hash = token_digest(nonce)
            stored = signal.model_dump(mode="json") | {"data": data}
            digest, payload = _redacted(stored, self._limits.max_signal_bytes)
            items.append(
                InboxItem(
                    ingress_id=uuid7(),
                    kind=f"signal.{signal.type}",
                    dedupe_key=signal.signal_id,
                    body_sha256=digest,
                    payload=payload,
                    seq=signal.seq,
                )
            )
        if nonce_hash is not None and principal.tier is TrustTier.ENVIRONMENT_KEY:
            principal = Principal(
                principal.tier,
                principal.credential,
                provider=principal.provider,
                environment_ref=principal.environment_ref,
                nonce_hash=nonce_hash,
            )
        result = await self._store.accept(principal, items)
        if result.outcome != "accepted":
            raise rejection(result.outcome)
        return SignalReceipt(accepted=result.accepted, duplicates=result.duplicates)

    async def gate(self, body: bytes, headers: Mapping[str, str]) -> GateAnswer:
        """`POST signals?gate=1`: the synchronous answer for one effect, computed in SQL."""

        self._cap(body, self._limits.max_signal_bytes)
        principal = await self._principal(headers, body, gating=True)
        request: GateRequest = _parse(GateRequest, body)
        digest, _payload = _redacted(request.model_dump(mode="json"), self._limits.max_signal_bytes)
        result = await self._store.gate(
            principal,
            GateCall(
                ingress_id=uuid7(),
                dedupe_key=request.signal_id,
                hook_event=request.hook_event.value,
                effect_ref=request.effect_ref,
                effect_kind=request.effect_kind,
                tool=request.tool,
                input_digest=sha256_digest(request.tool_input),
                body_sha256=digest,
            ),
        )
        if result.outcome != "decided" or result.decision not in {"allow", "deny", "stop"}:
            raise rejection(result.outcome)
        return GateAnswer.model_validate({"decision": result.decision, "reason": result.reason})

    # --- provider webhooks -----------------------------------------------------------------

    async def webhook(
        self,
        provider: str,
        body: bytes,
        headers: Mapping[str, str],
        *,
        route_ref: str | None = None,
    ) -> Literal["accepted", "duplicate"]:
        """A verified provider delivery, recorded once as a wake-up. A repeated delivery id
        (a provider retry or a replay inside the signature tolerance) records nothing and
        answers `duplicate`, which the route still answers 204 so the provider stops retrying."""

        if provider not in WEBHOOK_PROVIDERS:
            raise rejection("unknown_provider")
        self._cap(body, self._limits.max_webhook_bytes)
        delivery, event = self._verify_webhook(provider, body, headers, route_ref)
        try:
            parsed = json.loads(body)
        except ValueError:
            raise rejection("invalid_body") from None
        if not isinstance(parsed, dict):
            raise rejection("invalid_body")
        if provider in STANDARD_WEBHOOK_PROVIDERS:
            wake = provider_wake(provider, parsed).model_dump(mode="json", exclude_none=True)
            digest, payload = _redacted(wake, self._limits.max_signal_bytes)
        else:
            digest, payload = self._webhook_document(parsed, event, len(body))
            # Verified envelope seam for MO75. Still inbox-only: resolving an admitted
            # execution and writing frames belong to the worker drainer, not HTTP.
            normalized = None
            if provider == "github" and event in {"check_suite", "pull_request", "push"}:
                normalized = github_signal(
                    event,
                    parsed,
                    delivery_id=delivery,
                    observed_at=datetime.fromtimestamp(self._clock(), UTC),
                )
            elif provider == "cursor" and parsed.get("event") == "statusChange":
                with suppress(ValueError):
                    normalized = cursor_status_signal(
                        parsed,
                        delivery_id=delivery,
                        observed_at=datetime.fromtimestamp(self._clock(), UTC),
                    )
            if normalized is not None:
                _, payload = _redacted(
                    {"event": event, "source_signal": normalized.model_dump(mode="json")},
                    self._limits.max_signal_bytes,
                )
        outcome = await self._store.webhook(
            provider,
            route_ref,
            InboxItem(
                ingress_id=uuid7(),
                kind=f"webhook.{provider}",
                dedupe_key=delivery,
                body_sha256=digest,
                payload=payload,
            ),
        )
        if outcome not in {"accepted", "duplicate"}:
            raise rejection(outcome)
        return "accepted" if outcome == "accepted" else "duplicate"

    def _webhook_document(
        self, parsed: dict[str, Any], event: str | None, body_bytes: int
    ) -> tuple[str, dict[str, Any]]:
        """A Cursor or GitHub delivery, redacted. A wake-up needs only the identity a payload
        names (the drainer re-reads the provider), so an oversized delivery keeps its scalar
        top-level fields."""

        try:
            return _redacted({"event": event, "body": parsed}, self._limits.max_signal_bytes)
        except IngressRejected:
            scalars = {
                key: value
                for key, value in parsed.items()
                if isinstance(value, str | int | float | bool) or value is None
            }
            return _redacted(
                {"event": event, "body": scalars, "truncated": True, "body_bytes": body_bytes},
                self._limits.max_signal_bytes,
            )

    def _verify_webhook(
        self, provider: str, body: bytes, headers: Mapping[str, str], route_ref: str | None
    ) -> tuple[str, str | None]:
        """The verified delivery id and the event name a header carries."""

        if provider in STANDARD_WEBHOOK_PROVIDERS:
            delivery = verify_standard_webhook(
                self._webhook_secret(provider),
                webhook_id=headers.get("webhook-id"),
                timestamp=headers.get("webhook-timestamp"),
                signature=headers.get("webhook-signature"),
                body=body,
                now=self._clock(),
            )
            return delivery, None
        if provider == "github":
            verify_hex_signature(
                self._webhook_secret(provider).encode(),
                signature=headers.get("x-hub-signature-256"),
                body=body,
            )
            return self._delivery(headers.get("x-github-delivery")), headers.get("x-github-event")
        master = self._keys.cursor_webhook_master
        if master is None:
            raise IngressRejected(503, "webhook_unconfigured")
        if not route_ref:
            raise rejection("unknown_provider")
        # The secret registered with Cursor for this run is the hex of the derived key.
        secret = derive_secret(master, CURSOR_WEBHOOK_PURPOSE, f"{self.application_id}/{route_ref}")
        verify_hex_signature(
            secret.hex().encode(), signature=headers.get("x-webhook-signature"), body=body
        )
        return self._delivery(headers.get("x-webhook-id")), headers.get("x-webhook-event")

    def _webhook_secret(self, provider: str) -> str:
        secret = self._keys.webhook_secrets.get(provider)
        if not secret:
            raise IngressRejected(503, "webhook_unconfigured")
        return secret

    @staticmethod
    def _delivery(value: str | None) -> str:
        if not value or len(value) > 256:
            raise rejection("invalid_signature")
        return value

    # --- artifacts -------------------------------------------------------------------------

    async def prepare_artifact(self, body: bytes, headers: Mapping[str, str]) -> ArtifactUploadSlot:
        """A signed quarantine upload URL for one declared digest (bytes never cross here)."""

        if self._uploads is None:
            raise IngressRejected(503, "artifact_uploads_unavailable")
        self._cap(body, self._limits.max_signal_bytes)
        principal = await self._principal(headers, body, gating=True)
        request: ArtifactPrepareRequest = _parse(ArtifactPrepareRequest, body)
        result = await self._store.prepare_artifact(
            principal,
            uuid7(),
            artifact_ref=request.artifact_ref,
            sha256=request.sha256,
            size_bytes=request.size_bytes,
            media_type=request.media_type,
            ttl_seconds=self._limits.upload_ttl_seconds,
        )
        if result.outcome == "duplicate":
            raise rejection("artifact_already_committed")
        if (
            result.outcome != "prepared"
            or result.artifact_upload_id is None
            or result.storage_key is None
            or result.expires_at is None
        ):
            raise rejection(result.outcome)
        signed = await self._uploads.signed_upload(result.storage_key)
        return ArtifactUploadSlot(
            artifact_upload_id=result.artifact_upload_id,
            upload_url=signed.url,
            upload_token=signed.token,
            expires_at=result.expires_at,
        )

    async def commit_artifact(self, body: bytes, headers: Mapping[str, str]) -> UUID:
        """The upload is complete: the worker verifies its digest into custody."""

        self._cap(body, self._limits.max_signal_bytes)
        principal = await self._principal(headers, body, gating=True)
        request: ArtifactCommitRequest = _parse(ArtifactCommitRequest, body)
        result = await self._store.commit_artifact(principal, uuid7(), request.artifact_upload_id)
        if result.outcome not in {"committed", "duplicate"} or result.request_id is None:
            raise rejection(result.outcome)
        return result.request_id

    # --- remote launch requests (R29) ------------------------------------------------------

    async def request_mission(self, body: bytes, headers: Mapping[str, str]) -> UUID:
        """Record a launch request; the worker admits it. A repeated idempotency key answers
        the first request id."""

        self._cap(body, self._limits.max_signal_bytes)
        principal = self._launch_principal(headers)
        request: MissionRequest = _parse(MissionRequest, body)
        digest, payload = _redacted(
            request.model_dump(mode="json") | {"inputs_digest": sha256_digest(request.inputs)},
            self._limits.max_signal_bytes,
        )
        result = await self._store.request_mission(
            principal,
            InboxItem(
                ingress_id=uuid7(),
                kind="mission_request",
                dedupe_key=request.idempotency_key,
                body_sha256=digest,
                payload=payload,
            ),
            manifest_ref=request.manifest_ref,
        )
        if result.outcome not in {"accepted", "duplicate"} or result.request_id is None:
            raise rejection(result.outcome)
        return result.request_id

    async def mission_request_status(
        self, request_id: UUID, headers: Mapping[str, str]
    ) -> MissionRequestStatus:
        result = await self._store.mission_request_status(
            self._launch_principal(headers), request_id
        )
        if result.outcome != "found":
            raise rejection(result.outcome)
        return MissionRequestStatus.model_validate(
            {
                "state": result.state,
                "mission_id": result.mission_id,
                "reason": result.reason,
                "lifecycle": result.lifecycle,
            }
        )


__all__ = [
    "RUN_NONCE_FIELD",
    "IngressKeys",
    "IngressLimits",
    "SignalIngressService",
    "rejection",
]
