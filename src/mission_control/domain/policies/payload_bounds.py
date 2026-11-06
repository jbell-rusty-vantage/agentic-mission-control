"""The structural limits and secret key-name scan every persisted run-control payload obeys.

Shared by the run-control contracts (`domain/policies/contracts.Contract`) and by a sealed lane
binding's decoded payload (`domain/resolution/sealed.SealedLaneBinding`, OC-R2), so opaque bytes
cannot carry what an expanded payload could not: a raw secret, PHI or content field name, an
oversized string, an unbounded structure or an integer that does not fit signed 64-bit storage.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

MAX_NODES: Final = 20_000
MAX_DEPTH: Final = 32
MAX_STRING_CHARS: Final = 8_192
# W1 D10/S1: the string ceiling inside an embedded operation request or result, which carry
# their own segment and byte ceilings; every other structural and secret-name rule still holds.
EMBEDDED_MAX_STRING_CHARS: Final = 2_000_000
MAX_ENTRIES: Final = 1_024
SECRET_KEYS: Final = frozenset(
    {
        "secret",
        "password",
        "api_key",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "patient_id",
        "phi",
        "raw_content",
        "raw_output",
    }
)
SECRET_KEY_SUFFIXES: Final = ("_password", "_api_key", "_access_token", "_refresh_token")


class PayloadBoundViolation(ValueError):
    """A payload breaks a structural limit or names a secret field (deterministic: a retry of
    the same bytes can never pass, so a decode site may fail its workflow typed on it)."""


def is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in SECRET_KEYS or normalized.endswith(SECRET_KEY_SUFFIXES)


def check_payload_bounds(
    value: object,
    *,
    skip: Callable[[object], tuple[object, ...] | None] | None = None,
    max_string_chars: int = MAX_STRING_CHARS,
) -> None:
    """Raise `ValueError` when `value` breaks a structural limit or names a secret field.

    `skip(item)` may return the parts of an item to inspect instead of the item itself (the
    run-control contracts walk only a sealed binding's envelope, whose payload was already
    bounded when it was sealed).
    """

    nodes = 0

    def inspect(item: object, depth: int = 0) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise PayloadBoundViolation("run-control payload exceeds structural limits")
        if skip is not None:
            parts = skip(item)
            if parts is not None:
                for part in parts:
                    inspect(part, depth + 1)
                return
        if isinstance(item, str) and len(item) > max_string_chars:
            raise PayloadBoundViolation(
                f"run-control strings cannot exceed {max_string_chars} characters"
            )
        if isinstance(item, int) and not -(2**63) <= item < 2**63:
            raise PayloadBoundViolation("run-control integers must fit signed 64-bit storage")
        if isinstance(item, dict):
            if len(item) > MAX_ENTRIES:
                raise PayloadBoundViolation("run-control mappings cannot exceed 1024 entries")
            for key, nested in item.items():
                if isinstance(key, str) and is_secret_key(key):
                    raise PayloadBoundViolation(
                        "run-control records cannot contain raw secrets, PHI, or content"
                    )
                inspect(key, depth + 1)
                inspect(nested, depth + 1)
        elif isinstance(item, list | tuple | set | frozenset):
            if len(item) > MAX_ENTRIES:
                raise PayloadBoundViolation("run-control collections cannot exceed 1024 entries")
            for nested in item:
                inspect(nested, depth + 1)

    inspect(value)


__all__ = [
    "EMBEDDED_MAX_STRING_CHARS",
    "PayloadBoundViolation",
    "check_payload_bounds",
    "is_secret_key",
]
