"""Retained read observations (release 1.5.0 ``retained_read_observation``; OVE-204 slice 4).

One observation is one read an invocation actually made: the handle it read, the digest it
observed, whether that content was readable and the consistency facts of the read. A
``knowledge.read_intent`` writes one per result operation. A discovery read names no source
binding (``source_binding_id`` None) and expects no digest, so ``digest_verified`` stays false:
the observation records what was read, it never claims the read matched a bound handle.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

READ_INTENT_HANDLE_PREFIX: Final = "kri:"
MAX_HANDLE_LENGTH: Final = 2048


@dataclass(frozen=True)
class RetainedReadObservation:
    """One row of ``mission_control.retained_read_observation`` (scope comes from the store)."""

    observation_id: str
    run_id: str
    invocation_ref: str
    handle: str
    read_observation_ref: str
    readable: bool
    observed_at: datetime
    source_binding_id: str | None = None
    retained_ref: str | None = None
    expected_digest: str | None = None
    observed_digest: str | None = None
    byte_count: int | None = None
    consistency: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.handle or len(self.handle) > MAX_HANDLE_LENGTH:
            raise ValueError("an observation handle is 1..2048 characters")
        if self.readable and self.observed_digest is None:
            # The table's CHECK: content that was read has an observed digest.
            raise ValueError("a readable observation carries its observed digest")
        if self.byte_count is not None and self.byte_count < 0:
            raise ValueError("byte_count cannot be negative")

    @property
    def digest_verified(self) -> bool:
        """The generated column: an expected digest was given and the observed one equals it."""

        return (
            self.expected_digest is not None
            and self.observed_digest is not None
            and self.observed_digest == self.expected_digest
        )


__all__ = ["MAX_HANDLE_LENGTH", "READ_INTENT_HANDLE_PREFIX", "RetainedReadObservation"]
