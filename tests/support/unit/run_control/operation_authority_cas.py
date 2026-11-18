"""Builders, constants and fakes that other test files import.

Moved from tests/unit/run_control/test_operation_authority_cas.py.
"""

from __future__ import annotations

from mission_control.domain.policies.contracts import ClaimEffectAction
from tests.support.run_control import DIGEST, command


def claim(run_id: str, name: str):  # type: ignore[no-untyped-def]
    return command(
        run_id,
        2,
        f"claim:{name}",
        ClaimEffectAction(
            effect_id=f"effect:{name}",
            effect_kind="operation.runtime",
            operation_ref=f"binding:{name}",
            provider_idempotency_key=f"provider:{name}",
            reservation_id="baseline",
            claim_payload_digest=DIGEST,
        ),
    ).model_copy(update={"idempotency_issuer": "operation-journal"})
