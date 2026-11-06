"""Inject a genuine KS source correction after sealing, before actual receiver delivery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mission_control.application.context.materialization import (
    ContextDeliveryBlocked,
    MaterializeRequest,
    TransferMaterializer,
)
from mission_control.application.knowledge.trusted_settlement import report_ref
from mission_control.domain.knowledge.judgment import head_demoted


@dataclass
class LinkedSourceRevocation:
    corrected: bool = False
    proof: dict[str, Any] = field(default_factory=dict)

    def install(self, monkeypatch: Any, process: Any, pool: Any) -> None:
        from tests.integration.deep_agents.test_report_source_real_service import command

        from mission_control.adapters.postgres.knowledge.output_contracts import (
            PostgresOutputContractStore,
        )

        seal = TransferMaterializer.seal
        deliver = TransferMaterializer.deliver

        async def seal_then_correct(
            materializer: TransferMaterializer, request: MaterializeRequest
        ) -> Any:
            plan = await seal(materializer, request)
            linked = [member for member in plan.exact_sources if member.linked_source is not None]
            if not linked or self.corrected:
                return plan
            identities = {
                member.linked_source.output_revision_id
                for member in linked
                if member.linked_source is not None
            }
            assert len(identities) == 1, "this bounded fixture corrects exactly one exported report"
            store = PostgresOutputContractStore(pool)
            revision = await store.output_revision(request.receiver.scope, identities.pop())
            assert revision is not None and request.access is not None
            ref = report_ref(revision, tenant=request.access.origin.tenant_id)
            assert ref is not None
            self.proof.update(
                plan_before=plan.model_dump(mode="json"),
                receiver=request.receiver.model_dump(mode="json"),
                attempt=request.attempt.model_dump(mode="json"),
                source=revision.model_dump(mode="json"),
                assessments_before=[
                    item.model_dump(mode="json")
                    for item in await store.output_assessments(
                        request.receiver.scope, revision.run_id
                    )
                ],
            )
            correction = await command(
                process, {"action": "correct-source", "report": ref.model_dump(mode="json")}
            )
            self.proof["correction"] = correction
            assert correction["afterEpoch"] == correction["beforeEpoch"] + 1
            closure = correction["closure"]
            assert closure["epoch"] == correction["afterEpoch"] and closure["rechecked"]
            assert {"kind": "report", "id": ref.id} in closure["affected"]
            assert any(
                item["manifest"]["snapshot"] == "correction_snapshot"
                for item in correction["manifests"]
            )
            self.corrected = True
            return plan

        async def record_actual_delivery(
            materializer: TransferMaterializer, plan: Any, request: Any, backend: Any
        ) -> Any:
            try:
                result = await deliver(materializer, plan, request, backend)
            except ContextDeliveryBlocked as error:
                if self.corrected and plan.plan_id == self.proof["plan_before"]["plan_id"]:
                    self.proof["delivery_refusal"] = {
                        "code": error.code,
                        "reason": error.reason,
                        "refusals": [item.model_dump(mode="json") for item in error.refusals],
                        "plan_digest": plan.digest,
                    }
                    self.proof["receipts_after"] = [
                        item.model_dump(mode="json")
                        for item in await materializer._store.receipts(
                            request.receiver.scope, plan.plan_id
                        )
                    ]
                    source = self.proof["source"]
                    assessments = await PostgresOutputContractStore(pool).output_assessments(
                        request.receiver.scope, source["run_id"]
                    )
                    self.proof["assessments_after"] = [
                        item.model_dump(mode="json") for item in assessments
                    ]
                    self.proof["source_head_demoted"] = head_demoted(
                        assessments, source["revision_id"], source["content_digest"]
                    )
                raise
            if self.corrected and plan.plan_id == self.proof["plan_before"]["plan_id"]:
                self.proof["unexpected_delivery"] = result.receipt.model_dump(mode="json")
                raise AssertionError("revoked exact linked source reached a ready receiver")
            return result

        monkeypatch.setattr(TransferMaterializer, "seal", seal_then_correct)
        monkeypatch.setattr(TransferMaterializer, "deliver", record_actual_delivery)

    def verify(self, script: Any) -> None:
        assert self.corrected and "delivery_refusal" in self.proof, self.proof
        assert "unexpected_delivery" not in self.proof
        assert self.proof["source_head_demoted"], "current-use recheck did not demote exact source"
        assert not script.consumer.calls and not script.consumer.reads
        assert self.proof["receipts_after"]
        assert all(receipt["result"] != "ready" for receipt in self.proof["receipts_after"])
