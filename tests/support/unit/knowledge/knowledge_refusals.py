"""Builders, constants and fakes that other test files import.

Moved from tests/unit/knowledge/test_knowledge_refusals.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.contracts.knowledge_protocol_results import protocol_error

ISSUES = [
    f'occurrences.{index}.span.basis: Invalid input: expected "utf16-code-units-v1"'
    for index in range(30)
]


def census_refusal() -> Any:
    return protocol_error(
        "INVALID_ENVELOPE",
        "the census is not a valid discovery",
        occurred_at="2026-10-28T22:44:00Z",
        details={"reason": "observation_invalid", "issues": ISSUES},
    )
