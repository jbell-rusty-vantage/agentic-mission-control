"""Knowledge Services identities and credentials for the one KS fake.

The binding, audience and issuer names, the K07 stand-in `Issuer` (real Ed25519 keys, a pinned
JWKS and the production `CredentialVerifier`), the `RecordingMinter` and the stepping clock the
fake and its stores share.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mission_control.adapters.knowledge.credentials import (
    CredentialVerifier,
    Ed25519CredentialMinter,
    SigningKey,
    generate_signing_key,
)
from mission_control.application.ports.knowledge import (
    CredentialRequest,
    MintedCredential,
)
from mission_control.bootstrap.application_profiles import load_application_file
from mission_control.contracts.knowledge_protocol_results import (
    CredentialClaims,
)
from mission_control.domain.resolution.resolved import KnowledgePortBinding

ISSUER = "mission-control"

AUDIENCE = "ks-executor"

BINDING = "aiengineer-postgres"

DEPLOYMENTS = Path(__file__).resolve().parents[3] / "deployments"


def knowledge_port(binding: str = BINDING) -> KnowledgePortBinding:
    """The checked-in Application Profile's knowledge port for ``binding`` (OC-R4)."""

    for path in sorted(DEPLOYMENTS.glob("*/application.toml")):
        port = load_application_file(path).profile.knowledge
        if port.binding_id == binding:
            return port
    raise LookupError(f"no deployments/*/application.toml names binding {binding}")


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# The start of the knowledge fixtures' clock: `Clock(KNOWLEDGE_NOW)` (tests.support.clock).
KNOWLEDGE_NOW = datetime(2026, 10, 24, 20, 0, tzinfo=UTC)


@dataclass
class Issuer:
    """A disposable issuer: active and retiring Ed25519 keys, the minter and the JWKS."""

    clock: Callable[[], datetime]
    active: SigningKey = field(default_factory=lambda: generate_signing_key("mc-k2"))
    retiring: SigningKey | None = field(default_factory=lambda: generate_signing_key("mc-k1"))
    issuer: str = ISSUER
    lifetime: int = 300

    def minter(self) -> Ed25519CredentialMinter:
        return Ed25519CredentialMinter(
            issuer=self.issuer,
            active=self.active,
            retiring=self.retiring,
            lifetime_seconds=self.lifetime,
            clock=self.clock,
        )

    def verifier(
        self, *, audience: str = AUDIENCE, issuer: str | None = None
    ) -> CredentialVerifier:
        return CredentialVerifier(
            issuer=issuer or self.issuer,
            audience=audience,
            jwks=self.minter().jwks(),
            clock=self.clock,
        )


@dataclass
class RecordingMinter:
    """Wraps the real minter: records claims and optionally re-signs drifted claims."""

    inner: Ed25519CredentialMinter
    drift: dict[str, Any] = field(default_factory=dict)
    minted: list[CredentialClaims] = field(default_factory=list)

    @property
    def issuer(self) -> str:
        return self.inner.issuer

    def mint(self, request: CredentialRequest) -> MintedCredential:
        minted = self.inner.mint(request)
        if self.drift:
            claims = CredentialClaims.model_validate(
                minted.claims.model_dump(mode="json") | self.drift
            )
            minted = MintedCredential(claims=claims, token=self.inner.sign_claims(claims))
        self.minted.append(minted.claims)
        return minted


__all__ = [
    "AUDIENCE",
    "BINDING",
    "DEPLOYMENTS",
    "ISSUER",
    "KNOWLEDGE_NOW",
    "Issuer",
    "RecordingMinter",
    "knowledge_port",
    "stamp",
]
