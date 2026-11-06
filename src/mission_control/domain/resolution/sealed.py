"""The opaque lane binding the resolution seam returns and the operation request carries.

`SealedLaneBinding` is a lane's typed binding sealed as canonical UTF-8 JSON under its raw
SHA-256 digest (ADR-0063, design §6.1). It is its own module so that the execution contracts
can carry it without importing the resolution types (`resolved.py` re-exports it).
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from functools import lru_cache
from typing import TYPE_CHECKING, ClassVar, Final, Protocol, TypeVar, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from mission_control.domain.authoring.canonical import stable_json_dump
from mission_control.domain.policies.payload_bounds import check_payload_bounds

if TYPE_CHECKING:
    from mission_control.domain.execution.lanes import LaneDispatch

DIGEST_PATTERN: Final = r"^sha256:[0-9a-f]{64}$"
# The largest sealed payload: half the operation workflow's 2,000,000-byte payload ceiling
# (`domain/execution/contracts.MAX_OPERATION_WORKFLOW_PAYLOAD_BYTES`), because the payload
# travels base64 (4/3 larger) inside a request that also carries prompts and its envelope.
MAX_SEALED_PAYLOAD_BYTES: Final = 1_000_000


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def payload_digest(payload: bytes) -> str:
    """The digest of a sealed binding's canonical bytes (raw SHA-256 of the bytes)."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


_Contract = TypeVar("_Contract", bound=BaseModel)


def canonical_contract_bytes(contract: BaseModel) -> bytes:
    """Canonical UTF-8 JSON of a contract: sorted keys, sets in canonical order, no whitespace."""

    return json.dumps(
        stable_json_dump(contract),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class SealedLaneBinding(_Frozen):
    """Opaque to every caller except the lane that produced it.

    `payload` is the canonical UTF-8 JSON the lane alone parses; the core moves it under its
    digest and never reads it (design §6.1: what never crosses the port). In every dump
    (persisted templates, Temporal payloads, Python-mode copies) the payload travels as base64
    and is decoded back on load, and a canonical digest of any contract that carries one
    covers that form.
    """

    canonical_json_mode: ClassVar[bool] = True

    lane_profile: str = Field(min_length=1, max_length=64)
    # e.g. `belllabs.deep-agent-binding.v1`, `mc.cursor_binding.v2`, `mc.execution_binding.v2`.
    # (`schema` in the sketch: renamed because it shadows a `BaseModel` attribute.)
    schema_id: str = Field(min_length=1, max_length=128)
    # Raw SHA-256 of the payload bytes, not the canonical-JSON envelope of `sha256_digest`.
    digest: str = Field(pattern=DIGEST_PATTERN)
    payload: bytes

    @field_validator("payload", mode="before")
    @classmethod
    def decode_base64(cls, value: object) -> object:
        if isinstance(value, str):
            return base64.b64decode(value.encode("ascii"), validate=True)
        return value

    @field_serializer("payload")
    def encode_base64(self, payload: bytes) -> str:
        return base64.b64encode(payload).decode("ascii")

    @model_validator(mode="after")
    def exact_payload(self) -> SealedLaneBinding:
        if len(self.payload) > MAX_SEALED_PAYLOAD_BYTES:
            raise ValueError(
                f"sealed {self.lane_profile} binding exceeds {MAX_SEALED_PAYLOAD_BYTES} bytes"
            )
        if payload_digest(self.payload) != self.digest:
            raise ValueError(f"sealed {self.lane_profile} binding digest mismatch")
        _bounded(self.lane_profile, self.payload)
        return self

    @classmethod
    def seal(cls, *, lane_profile: str, schema_id: str, payload: bytes) -> SealedLaneBinding:
        return cls(
            lane_profile=lane_profile,
            schema_id=schema_id,
            digest=payload_digest(payload),
            payload=payload,
        )

    @classmethod
    def seal_contract(
        cls, contract: BaseModel, *, lane_profile: str, schema_id: str
    ) -> SealedLaneBinding:
        """Seal a lane's typed binding as its canonical JSON (the lane that owns the type)."""

        return cls.seal(
            lane_profile=lane_profile,
            schema_id=schema_id,
            payload=canonical_contract_bytes(contract),
        )

    def unseal(
        self, model: type[_Contract], *, schema_ids: frozenset[str] | tuple[str, ...]
    ) -> _Contract:
        """The lane's typed binding back from its bytes; only the producing lane calls this."""

        if self.schema_id not in schema_ids:
            raise ValueError(
                f"{self.lane_profile} binding {self.schema_id} is not one of {sorted(schema_ids)}"
            )
        return cast(_Contract, _decoded(model, self))

    def ref(self) -> dict[str, str]:
        """The digest-only reference a transcript, receipt or replay names."""

        return {
            "lane_profile": self.lane_profile,
            "schema_id": self.schema_id,
            "digest": self.digest,
        }


def verified_serialized_binding(item: Mapping[str, object]) -> bool:
    """Whether a serialized binding's payload is the bytes its digest names.

    The run-control contracts walk a sealed binding's envelope instead of its base64 payload
    (`domain/policies/contracts.Contract`), but only once the shape is backed by its bytes: the
    payload decodes and its raw SHA-256 equals `digest`. The verified payload is then bounded and
    scanned as `SealedLaneBinding` scans it (raising `ValueError` when refused), so a dict that
    merely mimics the envelope, nested anywhere in a contract, cannot carry what an expanded
    payload could not. `False`: not a genuine binding, and the caller scans it as ordinary data.
    """

    raw = item.get("payload")
    digest = item.get("digest")
    if isinstance(raw, str):
        try:
            payload = base64.b64decode(raw.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError):
            return False
    elif isinstance(raw, bytes):
        payload = raw
    else:
        return False
    if not isinstance(digest, str) or payload_digest(payload) != digest:
        return False
    lane_profile = str(item.get("lane_profile"))
    if len(payload) > MAX_SEALED_PAYLOAD_BYTES:
        raise ValueError(f"sealed {lane_profile} binding exceeds {MAX_SEALED_PAYLOAD_BYTES} bytes")
    _bounded(lane_profile, payload)
    return True


@lru_cache(maxsize=256)
def _bounded(lane_profile: str, payload: bytes) -> None:
    """The payload is UTF-8 JSON within the run-control structural limits and names no raw
    secret, PHI or content field (the shared scan); checked once per exact payload."""

    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError(f"sealed {lane_profile} binding is not UTF-8 JSON") from error
    try:
        check_payload_bounds(document)
    except ValueError as error:
        raise ValueError(f"sealed {lane_profile} binding payload refused: {error}") from error


@lru_cache(maxsize=256)
def _decoded(model: type[BaseModel], binding: SealedLaneBinding) -> BaseModel:
    """Typed bindings are frozen, so a lane may share one decode of the same exact bytes."""

    return model.model_validate_json(binding.payload)


class CarriesLaneBinding(Protocol):
    """An operation request or bound operation: what carries one sealed lane binding."""

    @property
    def lane_binding(self) -> SealedLaneBinding | None: ...

    @property
    def lane_dispatch(self) -> LaneDispatch | None: ...


__all__ = [
    "MAX_SEALED_PAYLOAD_BYTES",
    "CarriesLaneBinding",
    "SealedLaneBinding",
    "canonical_contract_bytes",
    "payload_digest",
    "verified_serialized_binding",
]
