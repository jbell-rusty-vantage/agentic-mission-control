"""W1 D28 / D29 on a disposable PostgreSQL 17 through the production output service.

Recorded flow shape of run 9cc17684: a reference report promise with the trusted assessment
requirement; the bridge records the held decision (review), then the approved adjudication as a
superseding pass, then promotes; ``compose_output_fulfillment`` must decide the report fulfilled
(official use of exactly that revision), and a later revocation must end it. A submitted but
unaccepted expected summary reads ``SUBMITTED_NOT_ACCEPTED``, never ``MISSING``.
"""

from __future__ import annotations

import pytest

from mission_control.adapters.postgres.knowledge.output_contracts import (
    PostgresOutputContractStore,
)
from mission_control.adapters.postgres.knowledge.output_fulfillment import (
    compose_output_fulfillment,
)
from mission_control.domain.outputs.contracts import Enforcement, OutputForm
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.integration.postgres.runtime_common import common_db  # noqa: F401
from tests.integration.postgres.test_output_contracts_postgres import access_for
from tests.unit.outputs.scenario import Stack, build_stack, codes, fulfillment, obligation, text
from tests.unit.outputs.test_w1_d28_d29 import PIN, bridge_judges, report_candidate, report_promise

pytestmark = [pytest.mark.asyncio, pytest.mark.common_db]


async def test_review_approved_report_is_fulfilled_then_revoked_on_postgres(
    common_db: CommonDatabase,  # noqa: F811
) -> None:
    pool = await common_db.pool()
    try:
        store = PostgresOutputContractStore(pool)
        stack = await build_stack(
            store,
            store,
            access_for(common_db),
            report_promise(),
            obligation(
                "root.summary", OutputForm.TEXT, position="root", enforcement=Enforcement.EXPECTED
            ),
        )
        production = compose_output_fulfillment(pool, trusted_validators=frozenset({PIN}))
        stack = Stack(
            store, stack.submissions, production, stack.access, stack.host, stack.assessor
        )
        ack = await stack.submit("k1", "root.report", report_candidate(), position="root")
        summary = await stack.submit(
            "k2", "root.summary", text("summary", "one sentence"), position="root"
        )
        assert ack.status == summary.status == "accepted"
        await stack.submissions.finalize(stack.access.identity(("root.report", "root.summary")))
        revision = ack.revisions[0]
        held = await bridge_judges(
            stack, revision.revision_id, revision.content_digest, "review", "ud-s10"
        )
        waiting = await stack.evaluate()
        assert fulfillment(waiting, "root.report").disposition != "fulfilled"
        assert codes(waiting, "root.summary") == ["SUBMITTED_NOT_ACCEPTED"]
        approved = await bridge_judges(
            stack,
            revision.revision_id,
            revision.content_digest,
            "pass",
            "ud-s10-adjudicated",
            supersedes=held.assessment_id,
        )
        await stack.accept(ack, "root.report")
        result = await stack.evaluate()
        assert fulfillment(result, "root.report").disposition == "fulfilled", fulfillment(
            result, "root.report"
        ).unmet
        assert result.shortfalls == ("root.summary",)
        await bridge_judges(
            stack,
            revision.revision_id,
            revision.content_digest,
            "review",
            "ud-s10-revoked",
            supersedes=approved.assessment_id,
        )
        revoked = await stack.evaluate()
        assert "REFERENCE_USE_UNPROVEN" in codes(revoked, "root.report")
    finally:
        await pool.close()
