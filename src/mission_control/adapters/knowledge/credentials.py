"""Issuer-backed knowledge operation credentials (Sprint V M02/K07, design §5).

:class:`Ed25519CredentialMinter` signs one K01 ``credential-claims.v2`` per dispatch as a
compact JWS (``alg: EdDSA`` over Ed25519, ``typ: ks-knowledge-operation+jwt``, ``kid`` of the
active key) immediately before the dispatch: a fresh ``jti``, ``iat = nbf = now`` and
``exp = now + lifetime`` (300 s default, the profile maximum). Rotation keeps two pinned keys:
the *active* key signs, the *retiring* key is only published so tokens it signed before the
rotation still verify until they expire. :func:`publish_jwks` renders the public JWKS document
the Knowledge Services executor pins (``KS_KNOWLEDGE_JWKS_FILE`` / ``_URL``).

:func:`load_signing_key` reads a private key file (an Ed25519 private JWK JSON object, the
format the KS executor's test support writes, or PKCS#8 PEM). Errors name the path, never the
bytes; a :class:`SigningKey` never renders its key material.

:class:`CredentialVerifier` is the verifying half the K07 profile describes: pinned issuer and
JWKS, the ``EdDSA`` algorithm allowlist, exact token type and audience, unknown ``kid`` fails
closed, a validity window with bounded skew, strict claim validation and single use of each
``jti`` while it lives. Mission Control uses it for its parity fake binding and its own
conformance tests; the executor's K07 implementation is Knowledge Services'.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import uuid4

from joserfc import jws
from joserfc.errors import JoseError
from joserfc.jwk import KeySet, OKPKey

from mission_control.application.ports.knowledge import CredentialRequest, MintedCredential
from mission_control.contracts.knowledge_protocol_results import (
    CREDENTIAL_MAX_LIFETIME_SECONDS,
    CREDENTIAL_TOKEN_TYPE,
    DEFAULT_CLOCK_SKEW_SECONDS,
    CredentialClaims,
    CredentialEffect,
)

ALGORITHM: Final = "EdDSA"
ALGORITHMS: Final = frozenset({ALGORITHM})


class CredentialKeyError(ValueError):
    """A signing key file is missing, unreadable or not an Ed25519 private key."""


class CredentialRejected(ValueError):
    """A presented credential fails the pinned profile (fail closed; reason is a code)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _utcnow() -> datetime:
    return datetime.now(UTC)


@contextmanager
def _quiet() -> Iterator[None]:
    # joserfc flags `EdDSA` as superseded by the fully specified `Ed25519` name (RFC 9864).
    # The K01 profile pins `EdDSA` over Ed25519 until both sides move together.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


@dataclass(frozen=True)
class SigningKey:
    """One pinned Ed25519 signing key; the private material never renders."""

    kid: str
    key: OKPKey = field(repr=False, compare=False)

    def public_jwk(self) -> dict[str, Any]:
        public = dict(self.key.as_dict(private=False))
        return {**public, "kid": self.kid, "alg": ALGORITHM, "use": "sig"}


def _as_ed25519(key: object, source: str) -> OKPKey:
    if not isinstance(key, OKPKey) or key.as_dict(private=False).get("crv") != "Ed25519":
        raise CredentialKeyError(f"{source} is not an Ed25519 key")
    if not key.is_private:
        raise CredentialKeyError(f"{source} holds no private key")
    return key


def load_signing_key(path: Path, *, kid: str | None = None) -> SigningKey:
    """Load a private Ed25519 JWK (JSON) or PKCS#8 PEM file; ``kid`` defaults to the JWK's."""

    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CredentialKeyError(f"signing key file is unreadable: {path}") from error
    try:
        if raw.lstrip().startswith(b"{"):
            document = json.loads(raw)
            if not isinstance(document, dict):
                raise CredentialKeyError(f"{path} is not a JWK object")
            key = OKPKey.import_key(document)
            kid = kid or document.get("kid")
        else:
            key = OKPKey.import_key(raw)
    except (ValueError, JoseError) as error:
        raise CredentialKeyError(f"signing key file is not a usable key: {path}") from error
    if not kid:
        raise CredentialKeyError(f"signing key {path} names no kid; pin one")
    return SigningKey(kid=kid, key=_as_ed25519(key, str(path)))


def generate_signing_key(kid: str) -> SigningKey:
    """A fresh Ed25519 key (disposable proofs and tests only)."""

    return SigningKey(kid=kid, key=OKPKey.generate_key("Ed25519", private=True))


def write_private_jwk(key: SigningKey, path: Path) -> None:
    """Write the private JWK of a disposable key (tests and local proofs only)."""

    document = {**key.key.as_dict(private=True), "kid": key.kid, "alg": ALGORITHM}
    path.write_text(json.dumps(document), encoding="utf-8")


def publish_jwks(active: SigningKey, retiring: SigningKey | None = None) -> dict[str, Any]:
    """The public JWKS the executor pins: the active key first, then the retiring one."""

    keys = [active.public_jwk()]
    if retiring is not None:
        if retiring.kid == active.kid:
            raise CredentialKeyError("the active and retiring keys need distinct kids")
        keys.append(retiring.public_jwk())
    return {"keys": keys}


def write_jwks(path: Path, active: SigningKey, retiring: SigningKey | None = None) -> None:
    path.write_text(json.dumps(publish_jwks(active, retiring), indent=2) + "\n", encoding="utf-8")


def _compact_json(document: Mapping[str, Any]) -> bytes:
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode("utf-8")


class Ed25519CredentialMinter:
    """``CredentialMinter`` over the pinned active key (the retiring key only verifies)."""

    def __init__(
        self,
        *,
        issuer: str,
        active: SigningKey,
        retiring: SigningKey | None = None,
        lifetime_seconds: int = CREDENTIAL_MAX_LIFETIME_SECONDS,
        clock: Callable[[], datetime] = _utcnow,
        new_jti: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        if not 1 <= lifetime_seconds <= CREDENTIAL_MAX_LIFETIME_SECONDS:
            raise ValueError("credential lifetime is 1..300 seconds")
        if retiring is not None and retiring.kid == active.kid:
            raise CredentialKeyError("the active and retiring keys need distinct kids")
        self._issuer = issuer
        self._active = active
        self._retiring = retiring
        self._lifetime = lifetime_seconds
        self._clock = clock
        self._new_jti = new_jti

    def __repr__(self) -> str:
        return f"Ed25519CredentialMinter(issuer={self._issuer!r}, kid={self._active.kid!r})"

    @property
    def issuer(self) -> str:
        return self._issuer

    @property
    def active_kid(self) -> str:
        return self._active.kid

    def jwks(self) -> dict[str, Any]:
        return publish_jwks(self._active, self._retiring)

    def mint(self, request: CredentialRequest) -> MintedCredential:
        issued = int(self._clock().timestamp())
        origin = request.origin
        claims = CredentialClaims(
            typ="ks-knowledge-operation+jwt",
            iss=self._issuer,
            aud=request.audience,
            sub=origin.subject,
            jti=self._new_jti(),
            iat=issued,
            nbf=issued,
            exp=issued + self._lifetime,
            tenant=origin.tenantId,
            application=origin.applicationId,
            binding=request.binding,
            origin=origin,
            operations=list(request.operations),
            effect=None
            if request.effect_key is None or request.bound_effect_digest is None
            else CredentialEffect(
                effectKey=request.effect_key, boundEffectDigest=request.bound_effect_digest
            ),
            dispatchId=request.dispatch_id,
            recovery=request.recovery,
            evaluation=request.evaluation,
        )
        return MintedCredential(claims=claims, token=self.sign_claims(claims))

    def sign_claims(self, claims: CredentialClaims) -> str:
        """Sign already-validated claims with the active key (conformance tests re-sign)."""

        header = {"alg": ALGORITHM, "kid": self._active.kid, "typ": CREDENTIAL_TOKEN_TYPE}
        with _quiet():
            return jws.serialize_compact(
                header,
                _compact_json(claims.model_dump(mode="json")),
                self._active.key,
                algorithms=[ALGORITHM],
            )


class CredentialVerifier:
    """The K07 verifying profile over a pinned issuer and JWKS (see the module doc)."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks: Mapping[str, Any],
        skew_seconds: int = DEFAULT_CLOCK_SKEW_SECONDS,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        keys = jwks.get("keys")
        if not isinstance(keys, list) or not keys:
            raise CredentialKeyError("a pinned JWKS names at least one key")
        self._keys: dict[str, KeySet] = {}
        for item in keys:
            kid = item.get("kid") if isinstance(item, dict) else None
            if not kid or kid in self._keys:
                raise CredentialKeyError("every pinned key has a distinct kid")
            if item.get("kty") != "OKP" or item.get("crv") != "Ed25519" or "d" in item:
                raise CredentialKeyError("pinned keys are public Ed25519 keys")
            self._keys[kid] = KeySet.import_key_set({"keys": [item]})
        self._skew = skew_seconds
        self._clock = clock
        self._seen: dict[str, int] = {}

    def verify(self, token: str) -> CredentialClaims:
        try:
            compact = jws.extract_compact(token.encode("ascii"))
        except (ValueError, UnicodeEncodeError, JoseError):
            raise CredentialRejected("malformed") from None
        protected = compact.protected
        if protected.get("alg") not in ALGORITHMS:
            raise CredentialRejected("algorithm_not_allowed")
        if protected.get("typ") != CREDENTIAL_TOKEN_TYPE:
            raise CredentialRejected("wrong_token_type")
        key_set = self._keys.get(str(protected.get("kid", "")))
        if key_set is None:
            raise CredentialRejected("unknown_kid")
        try:
            with _quiet():
                verified = jws.deserialize_compact(token, key_set, algorithms=sorted(ALGORITHMS))
        except JoseError:
            raise CredentialRejected("bad_signature") from None
        try:
            claims = CredentialClaims.model_validate_json(verified.payload)
        except ValueError:
            raise CredentialRejected("claims_invalid") from None
        if claims.iss != self._issuer:
            raise CredentialRejected("wrong_issuer")
        if claims.aud != self._audience:
            raise CredentialRejected("wrong_audience")
        now = int(self._clock().timestamp())
        if now + self._skew < claims.nbf:
            raise CredentialRejected("not_yet_valid")
        if now - self._skew >= claims.exp:
            raise CredentialRejected("expired")
        self._forget(now)
        if claims.jti in self._seen:
            raise CredentialRejected("replay")
        self._seen[claims.jti] = claims.exp
        return claims

    def _forget(self, now: int) -> None:
        for jti, expires in list(self._seen.items()):
            if expires + self._skew < now:
                del self._seen[jti]


def kids(jwks: Mapping[str, Any]) -> Iterable[str]:
    return (str(item.get("kid")) for item in jwks.get("keys", []))


__all__ = [
    "ALGORITHM",
    "CredentialKeyError",
    "CredentialRejected",
    "CredentialVerifier",
    "Ed25519CredentialMinter",
    "SigningKey",
    "generate_signing_key",
    "kids",
    "load_signing_key",
    "publish_jwks",
    "write_jwks",
    "write_private_jwk",
]
