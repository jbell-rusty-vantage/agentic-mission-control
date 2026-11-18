"""Builders, constants and fakes that other test files import.

Moved from tests/unit/subscriptions/test_coordinator_attention.py.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from mission_control.domain.outputs.contracts import ExactOutput, OutputForm
from mission_control.domain.outputs.rules import text_digest, value_digest
from tests.unit.subscriptions.coordinator_fakes import RUN

DIGEST = "sha256:" + "0" * 64


def output(
    key: str,
    text: str | None = None,
    *,
    value: Any = None,
    ref: str | None = None,
    revision: int = 1,
    digest: str | None = None,
) -> ExactOutput:
    if text is not None:
        candidate: dict[str, Any] = {"kind": "inline", "text": text}
        form = OutputForm.TEXT
        content_digest = digest or text_digest(text)
    elif value is not None:
        candidate = {"kind": "inline", "value": value}
        form = OutputForm.STRUCTURED
        content_digest = digest or value_digest(value)
    else:
        candidate = {"kind": "handle", "ref": ref}
        form = OutputForm.REFERENCE
        content_digest = digest or DIGEST
    candidate.update(
        {"deliverable_id": f"{key}.main", "form": form.value, "digest": content_digest}
    )
    return ExactOutput(
        revision_id=str(uuid4()),
        run_id=str(RUN),
        obligation_key=key,
        obligation_revision=1,
        deliverable_id=f"{key}.main",
        revision=revision,
        form=form,
        content_digest=content_digest,
        candidate=candidate,
        producer_origin_ref="mission-invocation:producer-1",
    )


class Outputs:
    def __init__(self, *items: ExactOutput) -> None:
        self.items = items

    async def accepted_outputs(self, scope: str, run_id: str) -> tuple[ExactOutput, ...]:
        return self.items
