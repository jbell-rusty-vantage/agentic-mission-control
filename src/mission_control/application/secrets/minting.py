"""Per-run credentials Mission Control mints (SPEC-01 section 4, SPEC-04, SPEC-10; ADR-0043).

`mint:<purpose>` issues a random bearer token bound to one request scope, run, unit and
generation, carrying only its purpose's scopes and expiring at the purpose's lifetime or the
mission deadline, whichever comes first. Only the token's digest is stored; the value goes to
the one delivery channel that asked for it and is never recorded. Verification looks the digest
up and refuses a token that is unknown, expired, revoked, minted for another purpose, bound to
another scope/run/unit/generation, or lacking the scope a caller needs. A generation change
revokes the earlier generations' tokens, and a terminal run revokes all of its tokens.

Every token carries the `mct_` prefix, so frames and transcripts redact one by pattern even
where its value was never resolved in the process that renders them.

The purposes are a closed table here: `signal_token` (the `run_token` ingress tier) and
`mission_request` (the operator launch credential of the Signal Ingress launch route, R29),
which is bound to a tenant scope only (`LaunchBinding`), never to a run. A credential may carry
a secret-free `context` the ingress reads (a gate's harness execution, lane profile and
disallowed tools; a launch credential's allowed `manifest_refs`) and each purpose sets the
per-minute request limit the ingress enforces. A new purpose, such as the Model Gateway's
`model_gateway` (HL-03), is one more `MintPurpose` entry.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol

from mission_control.contracts.identities import uuid7
from mission_control.domain.frames.body import MINTED_TOKEN_PATTERN


@dataclass(frozen=True)
class MintPurpose:
    name: str
    scopes: tuple[str, ...]
    lifetime: timedelta
    # Requests per fixed 60 s window the ingress accepts with one credential of this purpose.
    rate_limit_per_minute: int
    # A run-bound credential carries a `CredentialBinding`; otherwise a `LaunchBinding`.
    run_bound: bool = True


SIGNAL_TOKEN: Final = MintPurpose(
    "signal_token", ("signal:write",), timedelta(hours=24), rate_limit_per_minute=600
)
MISSION_REQUEST: Final = MintPurpose(
    "mission_request",
    ("mission:request",),
    timedelta(days=7),
    rate_limit_per_minute=30,
    run_bound=False,
)

MINT_PURPOSES: Final[Mapping[str, MintPurpose]] = MappingProxyType(
    {purpose.name: purpose for purpose in (SIGNAL_TOKEN, MISSION_REQUEST)}
)

TOKEN_PREFIX: Final = "mct_"  # noqa: S105 - the prefix every minted token carries
# `secrets.token_urlsafe(32)` yields the 43 URL-safe characters the frame redactor matches.
TOKEN_PATTERN: Final = MINTED_TOKEN_PATTERN

RejectionReason = Literal[
    "unknown", "expired", "revoked", "wrong_purpose", "wrong_binding", "insufficient_scope"
]

# Context keys never stored with a credential (the ingress table refuses them too).
_FORBIDDEN_CONTEXT_KEYS: Final = frozenset({"secret", "secret_value", "password", "token"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def token_digest(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CredentialBinding:
    """What a minted credential is bound to: one generation of one unit of one run."""

    request_scope: str
    run_id: str
    unit_id: str
    generation: int


@dataclass(frozen=True)
class LaunchBinding:
    """What an operator launch credential (`mission_request`) is bound to: one tenant scope."""

    request_scope: str


@dataclass(frozen=True)
class MintedCredential:
    """The stored record of a minted credential: its digest, never its value."""

    credential_id: str
    purpose: str
    digest: str
    binding: CredentialBinding | LaunchBinding
    scopes: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    rate_limit_per_minute: int
    revoked_at: datetime | None = None
    context: Mapping[str, Any] = field(default_factory=dict, hash=False)


class MintedToken:
    """A freshly minted token and its record. The value leaves only through `value`."""

    __slots__ = ("_value", "record")

    def __init__(self, value: str, record: MintedCredential) -> None:
        self._value = value
        self.record = record

    @property
    def value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"MintedToken({self.record.purpose}, {self.record.credential_id})"


class CredentialRejected(PermissionError):
    def __init__(self, reason: RejectionReason) -> None:
        super().__init__(f"minted credential rejected: {reason}")
        self.reason: RejectionReason = reason


class MintedCredentialStore(Protocol):
    """Digest-only storage of minted credentials (the PostgreSQL store is MO-40's
    `ingress_credential`, so the edge verifies the same records)."""

    async def insert(self, record: MintedCredential) -> None: ...

    async def by_digest(self, digest: str) -> MintedCredential | None: ...

    async def revoke(
        self,
        request_scope: str,
        run_id: str,
        *,
        at: datetime,
        unit_id: str | None = None,
        below_generation: int | None = None,
    ) -> int:
        """Revoke the run's live credentials (one unit's, below a generation, when named);
        the number revoked."""
        ...


class CredentialMinter:
    def __init__(
        self,
        store: MintedCredentialStore,
        *,
        purposes: Mapping[str, MintPurpose] = MINT_PURPOSES,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._store = store
        self._purposes = purposes
        self._clock = clock

    def purpose(self, name: str) -> MintPurpose:
        purpose = self._purposes.get(name)
        if purpose is None:
            raise ValueError(f"mint:{name} is not a purpose Mission Control mints")
        return purpose

    async def mint(
        self,
        purpose: str,
        binding: CredentialBinding | LaunchBinding,
        *,
        deadline: datetime | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> MintedToken:
        """A new token for `binding`, expiring at the purpose lifetime or `deadline`;
        `context` is the secret-free data the ingress reads with it."""

        kind = self.purpose(purpose)
        if isinstance(binding, CredentialBinding) != kind.run_bound:
            needed = "a run" if kind.run_bound else "a tenant scope only"
            raise ValueError(f"mint:{kind.name} is bound to {needed}")
        if context is not None and _FORBIDDEN_CONTEXT_KEYS & context.keys():
            raise ValueError("a credential context never carries a secret value")
        now = self._clock()
        expires_at = now + kind.lifetime
        if deadline is not None:
            if deadline <= now:
                raise ValueError("the mission deadline has passed; nothing is minted")
            expires_at = min(expires_at, deadline)
        value = TOKEN_PREFIX + secrets.token_urlsafe(32)
        record = MintedCredential(
            credential_id=str(uuid7()),
            purpose=kind.name,
            digest=token_digest(value),
            binding=binding,
            scopes=kind.scopes,
            issued_at=now,
            expires_at=expires_at,
            rate_limit_per_minute=kind.rate_limit_per_minute,
            context=dict(context or {}),
        )
        await self._store.insert(record)
        return MintedToken(value, record)

    async def verify(
        self,
        token: str,
        *,
        purpose: str,
        binding: CredentialBinding | LaunchBinding,
        scope: str | None = None,
    ) -> MintedCredential:
        """The live record of `token` when it is bound to exactly `binding`; otherwise
        `CredentialRejected` with the first failed check."""

        record = await self._store.by_digest(token_digest(token))
        if record is None:
            raise CredentialRejected("unknown")
        if record.revoked_at is not None:
            raise CredentialRejected("revoked")
        if self._clock() >= record.expires_at:
            raise CredentialRejected("expired")
        if record.purpose != purpose:
            raise CredentialRejected("wrong_purpose")
        if record.binding != binding:
            raise CredentialRejected("wrong_binding")
        if scope is not None and scope not in record.scopes:
            raise CredentialRejected("insufficient_scope")
        return record

    async def revoke_superseded(self, binding: CredentialBinding) -> int:
        """A new generation of the unit: its earlier generations' credentials stop working."""

        return await self._store.revoke(
            binding.request_scope,
            binding.run_id,
            at=self._clock(),
            unit_id=binding.unit_id,
            below_generation=binding.generation,
        )

    async def revoke_run(self, request_scope: str, run_id: str) -> int:
        """A terminal run: every credential minted for it stops working."""

        return await self._store.revoke(request_scope, run_id, at=self._clock())


__all__ = [
    "MINT_PURPOSES",
    "MISSION_REQUEST",
    "SIGNAL_TOKEN",
    "TOKEN_PATTERN",
    "TOKEN_PREFIX",
    "CredentialBinding",
    "CredentialMinter",
    "CredentialRejected",
    "LaunchBinding",
    "MintPurpose",
    "MintedCredential",
    "MintedCredentialStore",
    "MintedToken",
    "RejectionReason",
    "token_digest",
]
