"""W1 D28 / D29: official use of a review-approved report, and visible unaccepted submissions.

D28 (run 9cc17684): seal -> decide (admitted, official, review required) -> held -> reviewer
approved -> bridge pass -> promoted, yet the reference promise stayed ``REFERENCE_USE_UNPROVEN``:
production composed no ``ReferenceUsePort``. ``TrustedReferenceUses`` answers official use from
the bridge's standing adjudicated assessment of exactly that revision and digest.

D29: a submitted, finalized but unaccepted promise read ``MISSING`` ("0 accepted"); it now reads
``SUBMITTED_NOT_ACCEPTED`` and an expected shortfall stays visible (OUTPUT-CONTRACTS §2).
"""

from __future__ import annotations

import pytest

from mission_control.domain.knowledge.judgment import (
    decision_evidence,
    official_use_evidence,
)
from mission_control.domain.outputs.contracts import (
    Enforcement,
    OutputForm,
)
from tests.support.unit.outputs.official_use import (
    bridge_judges,
    make_stack,
    report_candidate,
    report_promise,
)
from tests.unit.outputs.scenario import (
    codes,
    fulfillment,
    obligation,
    text,
)

pytestmark = pytest.mark.asyncio


async def test_an_approved_review_makes_the_exact_promoted_revision_officially_usable() -> None:
    stack = await make_stack(report_promise())
    ack = await stack.submit("k1", "root.report", report_candidate(), position="root")
    revision = ack.revisions[0]
    held = await bridge_judges(
        stack, revision.revision_id, revision.content_digest, "review", "ud-1"
    )
    approved = await bridge_judges(
        stack,
        revision.revision_id,
        revision.content_digest,
        "pass",
        "ud-1-adjudicated",
        supersedes=held.assessment_id,
    )
    await stack.accept(ack, "root.report")
    result = await stack.evaluate()
    decided = fulfillment(result, "root.report")
    assert decided.disposition == "fulfilled", decided.unmet
    # The official-use evidence is the adjudicated decision of exactly this revision.
    assert decision_evidence("ud-1-adjudicated", revision.content_digest) in decided.assessment_refs
    # Revoked after promotion: the bridge's superseding non-pass ends official use.
    await bridge_judges(
        stack,
        revision.revision_id,
        revision.content_digest,
        "review",
        "ud-1-revoked",
        supersedes=approved.assessment_id,
    )
    revoked = await stack.evaluate()
    assert "REFERENCE_USE_UNPROVEN" in codes(revoked, "root.report")


async def test_held_or_unjudged_or_another_revision_is_not_official_use() -> None:
    stack = await make_stack(report_promise())
    ack = await stack.submit("k1", "root.report", report_candidate(), position="root")
    revision = ack.revisions[0]
    await stack.accept(ack, "root.report")
    unjudged = await stack.evaluate()
    assert "REFERENCE_USE_UNPROVEN" in codes(unjudged, "root.report")
    await bridge_judges(stack, revision.revision_id, revision.content_digest, "review", "ud-1")
    held = await stack.evaluate()
    assert "REFERENCE_USE_UNPROVEN" in codes(held, "root.report")
    # The same digest under another revision id never borrows the judgment.
    assessments = await stack.store.output_assessments(stack.host.scope, stack.run_id)
    assert official_use_evidence(assessments, "another-revision", revision.content_digest) is None


async def test_a_submitted_unaccepted_expected_text_is_visible_not_missing() -> None:
    stack = await make_stack(
        obligation(
            "root.summary", OutputForm.TEXT, position="root", enforcement=Enforcement.EXPECTED
        ),
        obligation(
            "root.extra", OutputForm.TEXT, position="root", enforcement=Enforcement.EXPECTED
        ),
    )
    ack = await stack.submit("k1", "root.summary", text("summary", "one line"), position="root")
    assert ack.status == "accepted"
    await stack.submissions.finalize(stack.access.identity(("root.summary",)))
    result = await stack.evaluate()
    summary = fulfillment(result, "root.summary")
    assert codes(result, "root.summary") == ["SUBMITTED_NOT_ACCEPTED"]
    assert "1 submitted but not accepted" in summary.unmet[0].message
    assert summary.submitted and summary.disposition == "unfulfilled"
    assert codes(result, "root.extra") == ["MISSING"]  # nothing submitted: still missing
    assert result.shortfalls == ("root.summary", "root.extra")
    assert result.completion == "satisfied"  # expected shortfalls never block


async def test_official_use_is_worst_wins_a_forked_failure_beside_a_later_pass_gives_none() -> None:
    """D28 review: every standing trusted row for the exact revision must be a cited pass; the
    evidence is the newest one's decision. A forked, unsuperseded fail blocks a later pass, and
    the head is demoted the same way."""

    from mission_control.domain.knowledge.judgment import head_demoted

    stack = await make_stack(report_promise())
    ack = await stack.submit("k1", "root.report", report_candidate(), position="root")
    revision = ack.revisions[0]
    await bridge_judges(stack, revision.revision_id, revision.content_digest, "fail", "ud-fork")
    await bridge_judges(stack, revision.revision_id, revision.content_digest, "pass", "ud-later")
    rows = await stack.store.output_assessments(stack.host.scope, stack.run_id)
    assert official_use_evidence(rows, revision.revision_id, revision.content_digest) is None
    assert head_demoted(rows, revision.revision_id, revision.content_digest)
    only_passes = [row for row in rows if row.result == "pass"]
    assert official_use_evidence(
        only_passes, revision.revision_id, revision.content_digest
    ) == decision_evidence("ud-later", revision.content_digest)
    assert not head_demoted(only_passes, revision.revision_id, revision.content_digest)
