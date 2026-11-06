"""Exercise the existing explicit adoption service under an actual receiver invocation."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from mission_control.adapters.postgres.knowledge.output_contracts import PostgresOutputContractStore
from mission_control.application.context.linked_transfer import LinkedExportResolver
from mission_control.application.context.materialization import (
    ResolutionContext,
    TransferMaterializer,
)
from mission_control.application.outputs.adoption import OutputAdoptionService, exact_ref
from mission_control.application.outputs.linked_adoption import LinkedOutputAdoptionService
from mission_control.domain.knowledge.lineage import ProvenanceRole


class LinkedAdoptionProbe:
    target = "consume.adopted_report"

    def __init__(self) -> None:
        self.capture: Any = None
        self.proof: dict[str, Any] = {}
        self.done = False

    def install(self, monkeypatch: Any, lane: Any, pool: Any) -> None:
        seal = TransferMaterializer.seal
        dispatch = lane.toolset.dispatch

        async def capture_real_selection(materializer: TransferMaterializer, request: Any) -> Any:
            plan = await seal(materializer, request)
            linked = [
                item for item in request.selection.inputs if item.source.kind == "linked_export"
            ]
            if linked:
                assert len(linked) == 1
                resolver = materializer._resolvers["linked_export"]
                assert isinstance(resolver, LinkedExportResolver)
                self.capture = (request, linked[0], resolver)
                self.proof["sealed_plan"] = plan.model_dump(mode="json")
            return plan

        async def adopt_after_real_read(tool: str, arguments: Any, live: Any, **kwargs: Any) -> Any:
            result = await dispatch(tool, arguments, live, **kwargs)
            if tool != "knowledge_read" or ":stage:consume:" not in live.operation_id or self.done:
                return result
            assert result.get("ok"), result
            assert self.capture is not None, (
                "adoption requires the actual sealed receiver selection"
            )
            request, binding, resolver = self.capture
            access = lane.toolset.access(await lane.toolset.locate(live))
            assert request.receiver.run_id == live.run_id
            assert request.receiver.operation_id == live.operation_id
            context = ResolutionContext(
                scope=request.receiver.scope,
                run_id=request.receiver.run_id,
                receiver_position=request.selection.receiver_position,
                access=access,
                boundary=request.selection.boundary,
                isolation=request.selection.isolation,
                receiver_operation_id=request.receiver.operation_id,
            )
            store = PostgresOutputContractStore(pool)
            obligations = await store.active_obligations(access.scope, live.run_id)
            target = next(item for item in obligations if item.key == self.target)
            assert target.enforcement.value == "required"
            accepted = await store.accepted_outputs(access.scope, live.run_id)
            assert not any(item.obligation_key == self.target for item in accepted)
            before = await store.latest_fulfillment(
                access.scope, live.run_id, target.key, target.revision
            )
            assert before is None or before[1].disposition != "fulfilled"
            self.proof.update(
                mode="fixture-invoked explicit host adoption under actual live receiver access",
                receiver_origin=access.origin.model_dump(mode="json"),
                binding=binding.model_dump(mode="json"),
                before={"target_accepted": False, "target_fulfilled": False},
            )
            recheck = resolver._recheck
            assert recheck is not None
            rechecks: list[dict[str, Any]] = []

            async def record_actual_recheck(actual_access: Any, revision: Any) -> None:
                await recheck(actual_access, revision)
                native_handle = revision.candidate["ref"]
                assert isinstance(native_handle, str)
                facts = await lane.toolset.lineage.facts(actual_access.scope, native_handle)
                self.proof["native_source_handle"] = native_handle
                self.proof["native_source_producer_before"] = [
                    fact.model_dump(mode="json")
                    for fact in facts
                    if fact.role is ProvenanceRole.PRODUCER
                ]
                rechecks.append(
                    {
                        "receiver_run_id": actual_access.origin.run_id,
                        "receiver_operation_id": actual_access.origin.operation_id,
                        "source": revision.model_dump(mode="json"),
                    }
                )

            probe = self

            class ObservedSubmission:
                async def submit_output(
                    self,
                    access: Any,
                    request: Any,
                    *,
                    position: str | None,
                    bindings: tuple[Any, ...] = (),
                    caller_origin_ref: str | None = None,
                ) -> Any:
                    probe.proof["submission_request"] = request.document()
                    ack = await lane.toolset.submissions.submit_output(
                        access,
                        request,
                        position=position,
                        bindings=bindings,
                        caller_origin_ref=caller_origin_ref,
                    )
                    probe.proof["submission_ack"] = ack.model_dump(mode="json")
                    return ack

            resolver._recheck = record_actual_recheck
            try:
                act = await LinkedOutputAdoptionService(
                    resolver,
                    OutputAdoptionService(
                        outputs=store,
                        submissions=ObservedSubmission(),
                        lineage=lane.toolset.lineage,
                    ),
                ).adopt(binding, context, target_obligation=self.target, at=datetime.now(UTC))
            finally:
                resolver._recheck = recheck
            self.proof["act"] = asdict(act)
            self.proof["current_use_rechecks"] = rechecks
            assert act.adopted and len(act.revisions) == 1, act
            assert len(rechecks) == 1
            revision_id = act.revisions[0].removeprefix("output:").split("@", 1)[0]
            draft = await store.output_revision(access.scope, revision_id)
            assert (
                draft is not None
                and draft.run_id == live.run_id
                and draft.obligation_key == self.target
            )
            accepted = await store.accepted_outputs(access.scope, live.run_id)
            assert not any(item.revision_id == draft.revision_id for item in accepted), (
                "adoption records a draft; normal trusted settlement owns promotion"
            )
            after = await store.latest_fulfillment(
                access.scope, live.run_id, target.key, target.revision
            )
            assert after is None or after[1].disposition != "fulfilled"
            self.proof["draft_after_act"] = draft.model_dump(mode="json")
            self.proof["immediately_after"] = {"accepted": False, "fulfilled": False}
            self.done = True
            return result

        monkeypatch.setattr(TransferMaterializer, "seal", capture_real_selection)
        lane.toolset.dispatch = adopt_after_real_read

    async def verify(self, stack: Any, scope: str, runs: dict[str, str], lane: Any) -> None:
        assert self.done and self.proof["act"]["adopted"]
        store = PostgresOutputContractStore(stack.worker_pool)
        source = next(
            item
            for item in await store.accepted_outputs(scope, runs["source"])
            if item.obligation_key == "root.report"
        )
        target = next(
            item
            for item in await store.accepted_outputs(scope, runs["consumer"])
            if item.obligation_key == self.target
        )
        assert target.revision_id != source.revision_id
        assert self.proof["submission_request"]["derivation_refs"] == [exact_ref(source)]
        assert target.candidate["ref"] == source.candidate["ref"]
        assert target.content_digest == source.content_digest
        assert target.revision_id == self.proof["draft_after_act"]["revision_id"]
        obligation = next(
            item
            for item in await store.active_obligations(scope, runs["consumer"])
            if item.key == self.target
        )
        decision = await store.latest_fulfillment(
            scope, runs["consumer"], self.target, obligation.revision
        )
        assert decision is not None and decision[1].disposition == "fulfilled"
        facts = await lane.toolset.lineage.facts(scope, exact_ref(source))
        adopted = [
            fact
            for fact in facts
            if fact.role is ProvenanceRole.ADOPTER
            and fact.actor_ref == f"{runs['consumer']}:{self.target}"
        ]
        assert len(adopted) == 1
        assert adopted[0].fact["revisions"] == [exact_ref(target)]
        assert not any(fact.role is ProvenanceRole.PRODUCER for fact in facts)
        native_facts = await lane.toolset.lineage.facts(scope, self.proof["native_source_handle"])
        original_producers = [fact for fact in native_facts if fact.role is ProvenanceRole.PRODUCER]
        assert len(original_producers) == 1
        assert original_producers[0].actor_origin is not None
        assert original_producers[0].actor_origin.run_id == runs["source"]
        assert [fact.model_dump(mode="json") for fact in original_producers] == self.proof[
            "native_source_producer_before"
        ]
        self.proof.update(
            accepted_after_normal_settlement=target.model_dump(mode="json"),
            fulfillment=decision[1].model_dump(mode="json"),
            adopter_lineage=[fact.model_dump(mode="json") for fact in adopted],
            verified=True,
        )
