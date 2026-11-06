"""Pure trusted-judgment rules (WI-03): independence, verdict mapping, supersession, use gate."""

from __future__ import annotations

import pytest

from mission_control.domain.knowledge.judgment import (
    CognitionIdentity,
    EvaluatorPin,
    JudgmentRefusal,
    assessment_result,
    decision_evidence,
    evaluator_refusals,
    supersession_refusal,
    use_gate,
)

PRODUCER = CognitionIdentity(
    "producer.default", "mc-runtime", "op-1", "anthropic", "claude-sonnet-5-5"
)
PIN = EvaluatorPin("judge.default", "openai", "gpt-5.6-terra")


def judge(**changes: str | None) -> CognitionIdentity:
    values = {
        "credential_ref": "judge.default",
        "subject": "mc-judge",
        "operation_ref": "op-judge",
        "vendor": "openai",
        "model_id": "gpt-5.6-terra",
    } | changes
    return CognitionIdentity(**values)  # type: ignore[arg-type]


def test_a_separate_judge_on_the_pinned_other_vendor_is_independent() -> None:
    assert evaluator_refusals(PRODUCER, judge(), role="judge", judge_pin=PIN) == ()
    assert evaluator_refusals(
        PRODUCER, judge(model_id="gpt-5.6-luna"), role="judge", judge_pin=PIN
    ) == (JudgmentRefusal.JUDGE_PIN_MISMATCH,)
    # The auditor needs its own credential and origin; its vendor may be the producer's.
    auditor = judge(
        credential_ref="auditor.default", vendor="anthropic", model_id="claude-haiku-5-5"
    )
    assert evaluator_refusals(PRODUCER, auditor, role="auditor", judge_pin=PIN) == ()
    assert JudgmentRefusal.EVALUATOR_IS_PRODUCER in evaluator_refusals(
        PRODUCER, judge(operation_ref="op-1"), role="judge", judge_pin=PIN
    )


@pytest.mark.parametrize(
    ("disposition", "admissible", "pending", "expected"),
    [
        (None, False, False, "unavailable"),
        ("rejected", False, False, "fail"),
        ("held", False, False, "review"),
        ("admitted", False, True, "review"),
        ("admitted", True, False, "pass"),
    ],
)
def test_only_a_ks_rejection_fails(disposition, admissible, pending, expected) -> None:  # type: ignore[no-untyped-def]
    assert assessment_result(disposition, admissible=admissible, review_pending=pending) == expected


def test_supersession_needs_the_bridge_the_same_subject_and_ks_lineage() -> None:
    subject = ("output_revision", "rev-1", "sha256:" + "a" * 64)
    evidence = (decision_evidence("ud-1", "sha256:" + "b" * 64),)
    ok = {
        "prior_subject": subject,
        "new_subject": subject,
        "prior_evidence": evidence,
        "successor_chain": ("ud-1", "ud-1-rv"),
    }
    assert supersession_refusal(role="assessor", **ok) is None  # type: ignore[arg-type]
    assert supersession_refusal(role="host", **ok) is JudgmentRefusal.SUPERSESSION_UNAUTHORIZED  # type: ignore[arg-type]
    other_actor = supersession_refusal(role="assessor", actor_ref="assessor:other", **ok)  # type: ignore[arg-type]
    assert other_actor is JudgmentRefusal.SUPERSESSION_UNAUTHORIZED
    assert supersession_refusal(role="assessor", **ok | {"successor_chain": ("ud-9",)}) is (  # type: ignore[arg-type]
        JudgmentRefusal.SUPERSESSION_NOT_A_SUCCESSOR
    )
    other = ("output_revision", "rev-2", subject[2])
    assert supersession_refusal(role="assessor", **ok | {"new_subject": other}) is (  # type: ignore[arg-type]
        JudgmentRefusal.SUPERSESSION_SUBJECT_MISMATCH
    )
    # An evaluator-unavailable wait record is replaced by the bridge's later judgment.
    assert (
        supersession_refusal(
            role="assessor",
            prior_subject=subject,
            new_subject=subject,
            prior_evidence=(),
            successor_chain=("ud-2",),
            prior_result="unavailable",
        )
        is None
    )


@pytest.mark.parametrize("application", ["ai-engineer", "biotech"])
def test_official_use_versus_authorized_held_repair(application: str) -> None:
    # Both applications pin required_review_classes=[official, consequential] and sign-off for
    # consequential (deployments/<app>/application.toml).
    minimums = {
        "required_review_classes": ("official", "consequential"),
        "signoff_classes": ("consequential",),
    }
    unreviewed = use_gate(
        purpose="official",
        use_class="official",
        admissible=True,
        reviewed=False,
        repair_authorized=False,
        **minimums,
    )
    assert unreviewed.reason == "review_required" and not unreviewed.official_use
    reviewed = use_gate(
        purpose="official",
        use_class="consequential",
        admissible=True,
        reviewed=True,
        repair_authorized=False,
        **minimums,
    )
    assert reviewed.official_use
    internal = use_gate(
        purpose="official",
        use_class="internal",
        admissible=True,
        reviewed=False,
        repair_authorized=False,
        **minimums,
    )
    assert internal.official_use
    held = use_gate(
        purpose="official",
        use_class="official",
        admissible=False,
        reviewed=True,
        repair_authorized=True,
        **minimums,
    )
    assert held.reason == "use_ineligible"
    repair = use_gate(
        purpose="review_repair",
        use_class="official",
        admissible=False,
        reviewed=False,
        repair_authorized=True,
        **minimums,
    )
    assert (repair.read_bytes, repair.official_use) == (True, False)
    refused = use_gate(
        purpose="review_repair",
        use_class="official",
        admissible=False,
        reviewed=False,
        repair_authorized=False,
        **minimums,
    )
    assert refused.reason == "repair_unauthorized"
