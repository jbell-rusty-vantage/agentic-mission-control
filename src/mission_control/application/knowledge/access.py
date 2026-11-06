"""Host-built invocation and recovery access, and credential conformance (M02, design §5).

The host constructs :class:`InvocationAccess` from the live attempt's
:class:`~mission_control.domain.knowledge.origin.InvocationOrigin` (SV-01) plus the
authenticated principal; the model never supplies it. This module is the one place the
snake_case ``mc.invocation_origin.v1`` maps to the K01 wire ``Origin``.

:func:`verify_credential_claims` is the host half of the K07 credential profile: before a
credential leaves the process its claims must name exactly the expected audience, binding,
tenant, application, origin, operations, effect and dispatch, live at most 300 s and be valid
now. A minter that drifts fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from mission_control.application.ports.knowledge import CredentialRequest, JournalCoordinates
from mission_control.contracts.knowledge_protocol import MissionCoordinates, Origin
from mission_control.contracts.knowledge_protocol_results import (
    CredentialClaims,
    CredentialRecovery,
)
from mission_control.domain.knowledge.origin import InvocationOrigin

CLOCK_SKEW: Final = timedelta(seconds=30)


def instant(at: datetime) -> str:
    """K01 ``Instant``: UTC, second precision, ``Z`` suffix."""

    if at.tzinfo is None:
        raise ValueError("knowledge protocol instants are timezone-aware")
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def request_scope(installation_id: str, application_id: str, tenant_id: str) -> str:
    return f"mc/{installation_id}/{application_id}/{tenant_id}"


def to_wire_origin(
    origin: InvocationOrigin,
    *,
    subject: str,
    invocation_id: str,
    authenticated_at: datetime,
    installation_id: str | None = None,
) -> Origin:
    """``mc.invocation_origin.v1`` -> K01 ``Origin`` (``kind=mission_invocation``).

    ``installation_id`` is the KS component installation the binding serves (W1 D6); unset,
    the origin names the Mission Control installation (one shared installation id).
    """

    return Origin(
        kind="mission_invocation",
        installationId=installation_id or origin.installation_id,
        applicationId=origin.application_id,
        tenantId=origin.tenant_id,
        issuer=origin.issuer,
        subject=subject,
        mission=MissionCoordinates(
            missionId=origin.mission_id,
            runId=origin.run_id,
            activationId=origin.activation_id,
            operationId=origin.operation_id,
            operationAttempt=origin.attempt,
            executionGeneration=origin.generation,
            lane=origin.lane,
        ),
        recoveryAuthorityRef=None,
        invocationId=invocation_id,
        authenticatedAt=instant(authenticated_at),
    )


@dataclass(frozen=True)
class RecoveryGrant:
    """Explicit host recovery authority for one exact scoped effect key and bound digest."""

    authority_ref: str
    effect_key: str
    bound_effect_digest: str

    def covers(self, effect_key: str, bound_effect_digest: str) -> bool:
        return self.effect_key == effect_key and self.bound_effect_digest == bound_effect_digest

    def claim(self) -> CredentialRecovery:
        """The effect-scoped K01 recovery claim a new attempt presents for this effect."""

        return CredentialRecovery(
            scope="effect",
            authorityRef=self.authority_ref,
            effectKey=self.effect_key,
            boundEffectDigest=self.bound_effect_digest,
        )


@dataclass(frozen=True)
class InvocationIdentity:
    """The stable identity of one invocation attempt for submissions and finalization."""

    scope: str
    run_id: str
    operation_ref: str
    operation_attempt: int
    execution_generation: int
    invocation_ref: str
    obligations: tuple[str, ...] = ()
    unit_key: str | None = None


@dataclass(frozen=True)
class InvocationAccess:
    """Who is calling now: one live attempt, authenticated by the host."""

    origin: InvocationOrigin
    subject: str
    invocation_id: str
    authenticated_at: datetime
    recovery_grant: RecoveryGrant | None = None
    # Host-minted grants for effects earlier attempts of this operation left unresolved.
    recovery_grants: tuple[RecoveryGrant, ...] = ()
    # W1 D6: the KS component installation the wire origin names (None: the MC installation).
    # The MC request scope (journal, handles, submissions) keeps the MC installation.
    knowledge_installation_id: str | None = None
    # Provenance slice 1 (OVE-204): the attempt's runtime unit key (``activation_key``). Mission
    # Control side only: it fills the journal, handle and submission ``unit_key`` columns and
    # never enters the origin, its digest or the K01 wire.
    unit_key: str | None = None

    @property
    def scope(self) -> str:
        return request_scope(
            self.origin.installation_id, self.origin.application_id, self.origin.tenant_id
        )

    def grant_for(self, effect_key: str, bound_effect_digest: str) -> RecoveryGrant | None:
        """The host recovery grant covering exactly this effect, if this attempt holds one."""

        grants = (*((self.recovery_grant,) if self.recovery_grant else ()), *self.recovery_grants)
        return next((g for g in grants if g.covers(effect_key, bound_effect_digest)), None)

    @property
    def invocation_ref(self) -> str:
        """Stable per attempt (excludes the per-authentication invocation id)."""

        return "mc-inv:" + self.origin.digest()

    def wire_origin(self) -> Origin:
        return to_wire_origin(
            self.origin,
            subject=self.subject,
            invocation_id=self.invocation_id,
            authenticated_at=self.authenticated_at,
            installation_id=self.knowledge_installation_id,
        )

    def coordinates(self) -> JournalCoordinates:
        return JournalCoordinates(
            mission_id=self.origin.mission_id,
            run_id=self.origin.run_id,
            activation_id=self.origin.activation_id,
            operation_ref=self.origin.operation_id,
            operation_attempt=self.origin.attempt,
            execution_generation=self.origin.generation,
            lane_profile=self.origin.lane,
            unit_key=self.unit_key,
        )

    def identity(self, obligations: tuple[str, ...] = ()) -> InvocationIdentity:
        return InvocationIdentity(
            scope=self.scope,
            run_id=self.origin.run_id,
            operation_ref=self.origin.operation_id,
            operation_attempt=self.origin.attempt,
            execution_generation=self.origin.generation,
            invocation_ref=self.invocation_ref,
            obligations=obligations,
            unit_key=self.unit_key,
        )


@dataclass(frozen=True)
class RecoveryAccess:
    """Read-only recovery authority (receipt lookup after the invocation ended)."""

    installation_id: str
    application_id: str
    tenant_id: str
    issuer: str
    subject: str
    authority_ref: str
    invocation_id: str
    authenticated_at: datetime
    # W1 D6: the KS component installation the wire origin names (None: the MC installation).
    knowledge_installation_id: str | None = None

    @property
    def scope(self) -> str:
        return request_scope(self.installation_id, self.application_id, self.tenant_id)

    @property
    def wire_installation_id(self) -> str:
        return self.knowledge_installation_id or self.installation_id

    def wire_origin(self) -> Origin:
        return Origin(
            kind="recovery",
            installationId=self.wire_installation_id,
            applicationId=self.application_id,
            tenantId=self.tenant_id,
            issuer=self.issuer,
            subject=self.subject,
            mission=None,
            recoveryAuthorityRef=self.authority_ref,
            invocationId=self.invocation_id,
            authenticatedAt=instant(self.authenticated_at),
        )

    def in_scope_of(self, origin: Origin) -> bool:
        return (
            origin.issuer == self.issuer
            and origin.installationId == self.wire_installation_id
            and origin.applicationId == self.application_id
            and origin.tenantId == self.tenant_id
        )

    def claim(self, effect_key: str, bound_effect_digest: str) -> CredentialRecovery:
        """The read-only K01 recovery claim of one receipt lookup for this exact effect."""

        return CredentialRecovery(
            scope="read_only",
            authorityRef=self.authority_ref,
            effectKey=effect_key,
            boundEffectDigest=bound_effect_digest,
        )


class CredentialMismatch(ValueError):
    """Minted claims differ from what this dispatch is authorized for (fail closed)."""


def verify_credential_claims(
    claims: CredentialClaims, expected: CredentialRequest, *, now: datetime
) -> None:
    origin = expected.origin
    checks = {
        # The origin's issuer is the host that authenticated it: the credential's issuer.
        "iss": claims.iss == origin.issuer,
        "aud": claims.aud == expected.audience,
        "binding": claims.binding == expected.binding,
        "tenant": claims.tenant == origin.tenantId,
        "application": claims.application == origin.applicationId,
        "sub": claims.sub == origin.subject,
        "origin": claims.origin == origin,
        "operations": tuple(claims.operations) == expected.operations,
        "dispatchId": claims.dispatchId == expected.dispatch_id,
        "effect": (
            (claims.effect is None and expected.effect_key is None)
            or (
                claims.effect is not None
                and claims.effect.effectKey == expected.effect_key
                and claims.effect.boundEffectDigest == expected.bound_effect_digest
            )
        ),
        # Exactly the authority this dispatch presents: none, read-only for a recovery
        # origin, or effect-scoped to this dispatch's effect for a new attempt.
        "recovery": claims.recovery == expected.recovery,
        # WI-03: exactly the evaluator grant this dispatch presents (none for the producer).
        "evaluation": claims.evaluation == expected.evaluation,
    }
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise CredentialMismatch("credential claims differ: " + ", ".join(failed))
    stamp = int(now.timestamp())
    skew = int(CLOCK_SKEW.total_seconds())
    if not claims.nbf - skew <= stamp < claims.exp:
        raise CredentialMismatch("credential is not valid now")


__all__ = [
    "CLOCK_SKEW",
    "CredentialMismatch",
    "InvocationAccess",
    "InvocationIdentity",
    "RecoveryAccess",
    "RecoveryGrant",
    "instant",
    "request_scope",
    "to_wire_origin",
    "verify_credential_claims",
]
