"""W1 D21 promise builders: a per-iteration progress note beside required, expected and
optional text promises at `root`.

Used by tests/unit/outputs/test_w1_convergence_fulfillment.py and
tests/integration/postgres/test_wi07_collections_postgres.py.
"""

from __future__ import annotations

from mission_control.domain.outputs.contracts import (
    Enforcement,
    EvaluationScope,
    OutputForm,
    OutputObligation,
)
from tests.unit.outputs.scenario import obligation


def note(scope: EvaluationScope = EvaluationScope.ITERATION, **extra: object) -> OutputObligation:
    return obligation("root.progress_note", OutputForm.TEXT, position="root", **extra).model_copy(
        update={"evaluation_scope": scope}
    )


def promises() -> tuple[OutputObligation, ...]:
    return (
        obligation("root.summary", OutputForm.TEXT, position="root"),
        note(),
        obligation(
            "root.appendix", OutputForm.TEXT, position="root", enforcement=Enforcement.EXPECTED
        ),
        obligation(
            "root.caveats", OutputForm.TEXT, position="root", enforcement=Enforcement.OPTIONAL
        ),
    )
