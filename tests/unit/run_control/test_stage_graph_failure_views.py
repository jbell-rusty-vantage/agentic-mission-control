"""F1-G5: a Stage Graph that concluded failed names its causes in inspection.

The live fork of 2026-11-06 (ITER-3 F1-G4/G5): the reused ``collect_a`` settled ``completed``
but the family rejected its result (no accepted ``notes_a``), so ``synthesize`` and ``review``
were skipped and the run failed with ``unit_failures: []`` and ``unmet_reasons: []``. The
recorded family decisions name every cause.
"""

from __future__ import annotations

from typing import Any

from mission_control.adapters.postgres.run_control.inspection_repository import (
    stage_graph_failure_views,
)


def decided(stage: str, decision: str, **extra: Any) -> dict[str, Any]:
    return {
        "decision_kind": "result_decided",
        "decision_payload": {
            "proposal": {
                "identity": {"candidate": {"stage_id": stage}},
                "decision": decision,
                "matched_veto": extra.get("veto"),
                "dependency_dispositions": extra.get("dispositions", {}),
            },
            "completion_validation": {"reason_codes": extra.get("reasons", [])},
        },
    }


def completed(**completion: Any) -> dict[str, Any]:
    return {"decision_kind": "completion_proposed", "decision_payload": {"completion": completion}}


LIVE = [
    decided("collect_b", "admit", dispositions={"collect_b:to:synthesize": "fulfilled"}),
    decided(
        "collect_a",
        "reject",
        veto="required_dependency_output_missing",
        reasons=["outputs_missing:notes_a"],
        dispositions={"collect_a:to:synthesize": "failed"},
    ),
    completed(failed=True, skipped_stage_ids=["review", "synthesize"]),
]


def test_the_rejected_producer_and_every_starved_stage_are_typed() -> None:
    views = [view.model_dump() for view in stage_graph_failure_views(LIVE)]
    assert views == [
        {
            "unit": "stage/collect_a",
            "reason": "required_dependency_output_missing",
            "failure_ref": (
                "stage_rejected:collect_a:required_dependency_output_missing:"
                "outputs_missing:notes_a"
            ),
        },
        {
            "unit": "stage/review",
            "reason": "dependency_unresolved",
            "failure_ref": "dependency_unresolved:review:producer_skipped",
        },
        {
            "unit": "stage/synthesize",
            "reason": "dependency_unresolved",
            "failure_ref": "dependency_unresolved:synthesize:collect_a:to:synthesize=failed",
        },
    ]


def test_a_later_admit_supersedes_a_reject_and_success_reports_nothing() -> None:
    retried = [
        decided("collect_a", "reject", veto="completion_requirement_failed"),
        decided("collect_a", "admit"),
        completed(failed=True, skipped_stage_ids=[]),
    ]
    assert stage_graph_failure_views(retried) == []
    assert (
        stage_graph_failure_views([*LIVE[:2], completed(required_obligations_accepted=True)]) == []
    )


def test_governed_unmet_reasons_become_family_failures() -> None:
    views = stage_graph_failure_views(
        [completed(failed=True, unmet_reasons=["revisit-cap-exhausted:r1:visit-3-of-3"])]
    )
    assert [(view.unit, view.reason) for view in views] == [
        ("family/stagegraph", "revisit-cap-exhausted")
    ]
