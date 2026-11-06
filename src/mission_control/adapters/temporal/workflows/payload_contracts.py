"""Decode sites that fail their workflow typed on a payload contract violation (W1 D10/S3).

A family decodes an activity result it scheduled. When those bytes break a structural payload
bound (`PayloadBoundViolation`: an oversized string, an unbounded structure, a secret field
name) no retry and no redeploy can ever make them decode, so the workflow fails at once with a
typed, non-retryable `ApplicationError` and the root terminalizes the run (D15). Any other
validation error (for example a field a newer worker added during a rolling deploy) is
re-raised unchanged: it stays a retryable workflow-task failure that a deploy can repair.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError
from temporalio.exceptions import ApplicationError

from mission_control.domain.policies.payload_bounds import PayloadBoundViolation

PAYLOAD_BOUND_VIOLATION = "payload_bound_violation"


def bound_violation(error: ValidationError) -> str | None:
    """The first payload-bound violation inside a validation error, else None."""

    for item in error.errors(include_url=False):
        cause = (item.get("ctx") or {}).get("error")
        if isinstance(cause, PayloadBoundViolation):
            return str(cause)
    return None


def decode_contract[M: BaseModel](model: type[M], payload: Any, *, site: str) -> M:
    try:
        return model.model_validate(payload)
    except ValidationError as error:
        violation = bound_violation(error)
        if violation is None:
            raise
        raise ApplicationError(
            f"{site} payload breaks its contract bounds: {violation}",
            type=PAYLOAD_BOUND_VIOLATION,
            non_retryable=True,
        ) from None


__all__ = ["PAYLOAD_BOUND_VIOLATION", "bound_violation", "decode_contract"]
