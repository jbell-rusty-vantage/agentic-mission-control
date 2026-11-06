"""Usage settled only when the provider reports it (ADR-0052; MP-05 usage dispositions).

A Remote Session Lane reports tokens as `settled` only from a provider usage record that names
this turn (or the session, when no turn is asked for), and cost only when a cost source reports
a value. Anything the provider does not report is `unknown`, never zero: an agent total is never
attributed to one turn, and a missing price never becomes a free turn.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple

from mission_control.domain.execution.lanes import UsageReport


class TokenFields(NamedTuple):
    """The provider's names for input, output and total tokens."""

    input: str = "input_tokens"
    output: str = "output_tokens"
    total: str = "total_tokens"


SNAKE_CASE_TOKENS = TokenFields()


def reported_usage(
    tokens: Mapping[str, Any] | None,
    *,
    fields: TokenFields = SNAKE_CASE_TOKENS,
    cost_micros_usd: int | None = None,
) -> UsageReport:
    """`settled` from a reported token record; `unknown` when there is none. A missing total
    is the sum of input and output."""

    if not tokens:
        return UsageReport(disposition="unknown")
    input_tokens = int(tokens.get(fields.input, 0) or 0)
    output_tokens = int(tokens.get(fields.output, 0) or 0)
    return UsageReport(
        disposition="settled",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=int(tokens.get(fields.total, 0) or input_tokens + output_tokens),
        cost_micros_usd=cost_micros_usd,
    )


__all__ = ["SNAKE_CASE_TOKENS", "TokenFields", "reported_usage"]
