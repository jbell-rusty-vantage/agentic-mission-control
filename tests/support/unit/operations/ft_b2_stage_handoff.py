"""Builders, constants and fakes that other test files import.

Moved from tests/unit/operations/test_ft_b2_stage_handoff.py.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

from mission_control.application.context.pack_service import (
    ArtifactContent,
    ContextPackService,
    StaticModelBudgetProfiles,
)
from mission_control.domain.context.packet import ContextPacket, ModelBudgetProfile
from mission_control.domain.context.refs import durable_input_locator, workspace_candidate_ref
from mission_control.domain.context.render import ContextSelectionRecord
from mission_control.domain.execution.contracts import (
    OperationExecutionRequest,
    WorkspaceContract,
    WorkspaceOwner,
    WorkspaceOwnerKind,
    WorkspaceSlotBinding,
)
from mission_control.domain.programs.contracts import (
    ExecutionIdentity,
    LateResultFacts,
    StageGraphAdmissionActivityRequest,
    StageResultObservation,
)
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from tests.integration.temporal.test_wp_bp_010_temporal import DIGEST, NOW, _blueprint, _operation

RUN_ID = "run-ft-b2"
SCOPE = "mc/0192a4f0-0000-7000-8000-00000000b10e/biotech/6f1e2d3c-0000-5000-8000-000000000001"
FAST_TEXT = '{"sources": [{"pmid": "1"}, {"pmid": "2"}]}'
FAST_REF = workspace_candidate_ref("cand-fast-result")


def _bytes_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class FakeArtifacts:
    def __init__(self, contents: dict[str, ArtifactContent], *, scope: str | None = SCOPE) -> None:
        self.contents = contents
        self.scope = scope

    async def capture(
        self, source_ref: str, *, request_scope: str, max_text_bytes: int
    ) -> ArtifactContent | None:
        assert self.scope is None or request_scope == self.scope
        content = self.contents.get(source_ref)
        if content is None or content.text is None or content.size_bytes <= max_text_bytes:
            return content
        return replace(content, text=None)


class FakeSelections:
    def __init__(self) -> None:
        self.rows: dict[tuple[object, ...], tuple[ContextPacket, ContextSelectionRecord]] = {}

    async def record(
        self, packet: ContextPacket, selection: ContextSelectionRecord, *, request_scope: str
    ) -> ContextPacket:
        target = packet.target
        key = (
            request_scope,
            target.run_id,
            target.activation_id,
            target.attempt_no,
            target.generation,
            target.purpose,
        )
        stored = self.rows.setdefault(key, (packet, selection))
        if stored[0].packet_digest != packet.packet_digest:
            raise AssertionError("conflicting packet for target")
        return stored[0]

    async def get(self, packet_id: str, *, request_scope: str) -> ContextPacket | None:
        return next((p for p, _ in self.rows.values() if p.packet_id == packet_id), None)


class FakeStaging:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def stage(self, *, request_scope: str, name: str, content: bytes, media_type: str) -> str:
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        object_ref = f"file-artifact://{digest.removeprefix('sha256:')}"
        self.objects[object_ref] = content
        return durable_input_locator(object_ref, digest, len(content))

    async def retrieve(self, durable_ref: str) -> bytes:
        return self.objects[durable_ref.partition("#")[0]]


def _service(
    contents: dict[str, ArtifactContent] | None = None,
    profile: ModelBudgetProfile | None = None,
) -> tuple[ContextPackService, FakeSelections, FakeStaging]:
    selections = FakeSelections()
    staging = FakeStaging()
    service = ContextPackService(
        artifacts=FakeArtifacts(
            contents
            if contents is not None
            else {
                FAST_REF: ArtifactContent(
                    source_ref=FAST_REF,
                    durable_ref=durable_input_locator(
                        "file-artifact://fast", _bytes_digest(FAST_TEXT), len(FAST_TEXT)
                    ),
                    content_digest=_bytes_digest(FAST_TEXT),
                    size_bytes=len(FAST_TEXT),
                    media_type="application/json",
                    file_name="sources.json",
                    text=FAST_TEXT,
                )
            }
        ),
        selections=selections,
        staging=staging,
        profiles=StaticModelBudgetProfiles(default=profile) if profile else None,
    )
    return service, selections, staging


def _admit(interpreter: StageGraphInterpreter, projection: Any, proposal: Any) -> Any:
    return interpreter.apply_admission(
        projection,
        proposal,
        next_run_version=projection.run_version + 1,
        next_family_version=projection.family_version + 1,
    )


def _downstream_request(output_refs: list[str]) -> StageGraphAdmissionActivityRequest:
    """Admit and accept the `fast` producer, then return the `downstream` admission."""

    graph = _blueprint()
    interpreter = StageGraphInterpreter(graph, effective_max_concurrency=3)
    projection = interpreter.initial_projection(identity=ExecutionIdentity(RUN_ID), run_version=2)
    frontier = interpreter.frontier(projection, available_concurrency=3)
    fast = next(item for item in frontier if item.identity.stage_id == "fast")
    projection = _admit(interpreter, projection, fast)
    observation = StageResultObservation(
        identity=fast.identity,
        operation_result={"output_refs": output_refs},
        child_closed_or_quiesced=True,
        reservations_and_usage_settled=True,
        effects_settled=True,
        cancellation_reconciled=True,
        accepted_order=1,
    )
    decision = interpreter.result_decision(fast.identity, LateResultFacts())
    projection = interpreter.apply_result_decision(
        projection,
        observation,
        decision,
        next_run_version=projection.run_version + 1,
        next_family_version=projection.family_version + 1,
    )
    frontier = interpreter.frontier(projection, available_concurrency=3)
    downstream = next(item for item in frontier if item.identity.stage_id == "downstream")
    return StageGraphAdmissionActivityRequest(
        run_id=RUN_ID,
        request_scope=SCOPE,
        projection=projection,
        proposal=downstream,
        operation=None,
        blueprint=graph.model_dump(mode="json"),
        effective_max_concurrency=3,
        occurred_at=NOW,
        idempotency_issuer="stagegraph-worker",
        correlation_id="stagegraph:ft-b2",
        semantic_input_binding_ref="semantic-input:test",
        effective_configuration_digest=DIGEST,
    )


def _compiled_template(request: StageGraphAdmissionActivityRequest) -> OperationExecutionRequest:
    template = _operation(request).operation
    stage_path = f"/stages/{request.proposal.identity.stage_id}"
    owner = WorkspaceOwner(kind=WorkspaceOwnerKind.STAGE, owner_id="compiled")
    workspace = WorkspaceContract.model_validate(
        {
            **template.workspace.model_dump(mode="python"),
            "workflow_contract_digest": DIGEST,
            "slot_bindings": (
                WorkspaceSlotBinding(
                    slot_name="output",
                    logical_path=stage_path,
                    access="exclusive_write",
                    owner=owner,
                ),
            ),
        }
    )
    return template.model_copy(update={"workspace": workspace})
