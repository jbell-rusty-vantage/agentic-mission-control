"""Verify held cross-run repair from durable source and receiver facts."""

from __future__ import annotations

from typing import Any

from mission_control.adapters.postgres.chains.exports import PostgresLinkedExports
from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
from mission_control.adapters.postgres.knowledge.output_contracts import PostgresOutputContractStore
from mission_control.adapters.postgres.run_control import canonical as mc
from mission_control.domain.context.transfer import SealedTransferPlan
from mission_control.domain.knowledge.lineage import ProvenanceRole


class LinkedRepairProbe:
    def __init__(self) -> None:
        self.proof: dict[str, Any] = {"verified": False}

    async def verify(
        self, stack: Any, scope: str, runs: dict[str, str], script: Any, lane: Any
    ) -> None:
        from tests.acceptance.mission_control.test_overnight_goal_directed import goal_records

        store = PostgresOutputContractStore(stack.worker_pool)
        held_receipt = script.source.registered[1]
        finalized = await store.finalized_outputs(scope, runs["source"])
        held = [item for item in finalized if item.obligation_key == "root.report"]
        assert len(held) == 1
        source = held[0]
        assert source.candidate["ref"] == held_receipt["handle"]
        assert source.content_digest == held_receipt["digest"]
        assert not any(
            item.obligation_key == "root.report"
            for item in await store.accepted_outputs(scope, runs["source"])
        )
        assessments = await store.output_assessments(scope, runs["source"])
        superseded = {item.supersedes for item in assessments if item.supersedes}
        standing = [
            item
            for item in assessments
            if item.subject_id == source.revision_id
            and item.subject_digest == source.content_digest
            and item.method_pin == "knowledge.report.assess@1"
            and item.assessment_id not in superseded
        ]
        assert standing and all(item.result in {"review", "fail"} for item in standing)
        decision = await store.latest_fulfillment(
            scope, runs["source"], source.obligation_key, source.obligation_revision
        )
        assert decision is not None and decision[1].disposition != "fulfilled"
        retained = await goal_records(stack, scope, runs["source"])
        assert retained["result"] is not None
        family = retained["result"]["family_result"]
        assert family["goal_iterations"] == 1
        assert [item["decision"] for item in family["verification_results"]] == ["repair_required"]
        assert script.source.feedback in family["verification_results"][0]["findings"]
        exports = await PostgresLinkedExports(stack.worker_pool).released_for(
            scope, runs["consumer"], "consume"
        )
        assert len(exports) == 1
        export = exports[0]
        assert export.admission == "subject" and export.purpose == "repair"
        assert export.release_gate == "execution_complete"
        assert export.source_run_id == runs["source"]
        assert [(item.revision_id, item.content_digest) for item in export.outputs] == [
            (source.revision_id, source.content_digest)
        ]
        assert export.outputs[0].acceptance_ref is None
        assert export.outputs[0].goal_findings
        async with stack.worker_pool.acquire() as connection, connection.transaction():
            args = await mc.begin(connection, scope)
            rows = await connection.fetch(
                "SELECT plan FROM mission_control.transfer_plan WHERE installation_id=$1 "
                "AND application_id=$2 AND tenant_id=$3 AND run_id=$4::uuid "
                "AND receiver_position='consume'",
                *args,
                runs["consumer"],
            )
        assert len(rows) == 1
        plan = SealedTransferPlan.model_validate(mc.load(rows[0]["plan"]))
        assert plan.exact_sources and all(
            item.admission == "subject" for item in plan.exact_sources
        )
        assert all(
            item.linked_source is not None and item.linked_source.export_digest == export.digest
            for item in plan.exact_sources
        )
        receipts = await PostgresTransferPlanStore(stack.worker_pool).receipts(scope, plan.plan_id)
        assert receipts and all(item.result == "ready" for item in receipts)
        assert len(script.repair_observations) == 1
        findings = script.repair_observations[0]["findings"]
        assert findings["official_use"] is False
        assert findings["goal_findings"] == [
            item.model_dump(mode="json") for item in export.outputs[0].goal_findings
        ]
        accepted = await store.accepted_outputs(scope, runs["consumer"])
        target = next(item for item in accepted if item.obligation_key == "consume.report")
        assert target.candidate["ref"] == script.registered_successor["handle"]
        assert target.content_digest == script.registered_successor["digest"]
        assert target.content_digest != source.content_digest
        assert not any(item.candidate.get("ref") == source.candidate["ref"] for item in accepted)
        required = {"consume.report", "consume.progress_note", "consume.comparison"}
        assert required <= {item.obligation_key for item in accepted}
        fulfillments = []
        for item in await store.active_obligations(scope, runs["consumer"]):
            if item.key in required:
                result = await store.latest_fulfillment(
                    scope, runs["consumer"], item.key, item.revision
                )
                assert result is not None and result[1].disposition == "fulfilled"
                fulfillments.append(result[1].model_dump(mode="json"))
        lineage = {}
        for label, output, owner in (
            ("source", source, runs["source"]),
            ("successor", target, runs["consumer"]),
        ):
            facts = await lane.toolset.lineage.facts(scope, output.candidate["ref"])
            producers = [item for item in facts if item.role is ProvenanceRole.PRODUCER]
            assert len(producers) == 1 and producers[0].actor_origin is not None
            assert producers[0].actor_origin.run_id == owner
            assert not any(item.role is ProvenanceRole.ADOPTER for item in facts)
            lineage[label] = [item.model_dump(mode="json") for item in facts]
        self.proof.update(
            verified=True,
            source=source.model_dump(mode="json"),
            source_assessments=[item.model_dump(mode="json") for item in standing],
            source_fulfillment=decision[1].model_dump(mode="json"),
            source_result=family,
            export=export.model_dump(mode="json"),
            export_digest=export.digest,
            plan=plan.model_dump(mode="json"),
            receipts=[item.model_dump(mode="json") for item in receipts],
            actual_reads=script.repair_observations,
            successor=target.model_dump(mode="json"),
            receiver_fulfillments=fulfillments,
            lineage=lineage,
        )

    def evidence(self) -> dict[str, Any]:
        return self.proof
