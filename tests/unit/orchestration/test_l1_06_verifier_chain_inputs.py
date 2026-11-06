"""OVE-169 L1-06: the Goal Loop verifier receives the chain inputs the executor received.

E4 consumer 2a6bc6a7: the executor read the chain-supplied evidence map under ``inputs/``; the
verifier's packet held only the executor's outputs, so it searched for the map it was asked to
check against and hit the tool-call budget. The verifier's ``iteration_start`` packet now carries
the run's released chain supply (the supplied artifacts, the supplier disposition and the chain
identity) as read-only context under its own role root, beside the executor's outputs. The
supplier's checkpoint and journal references (``missionctl`` commands a sandbox cannot run) stay
out; the executor's handoff and reasoning still never cross (REQ-BP-GD-004).
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any

import pytest

from mission_control.application.context.pack_service import (
    ChainSupply,
    ContextPackService,
)
from mission_control.domain.context.packet import (
    ContextBinding,
    ContextSourceKind,
    ContextTrust,
    ExpandMode,
    ItemProvenance,
    PackCandidate,
    RetrievalInstruction,
    RetrievalKind,
)
from tests.unit.operations.test_ft_b2_stage_handoff import (
    FakeArtifacts,
    FakeSelections,
    FakeStaging,
)
from tests.unit.orchestration.test_ft_b3_goal_iteration_packet import _executor_result
from tests.unit.orchestration.test_rrm_016_goal_directed_settlement import _claim, _preparation

MAP = b"| model | quoted size | source id |\n| Mistral 7B | 7-billion-parameter | arxiv |\n"
BINDING = "e4-evidence.evidence_map"


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


class FakeChainSupplies:
    def __init__(self, supply: ChainSupply) -> None:
        self.supply = supply
        self.asked: list[str] = []

    async def supply_for(self, run_id: str, *, request_scope: str) -> ChainSupply | None:
        del request_scope
        self.asked.append(run_id)
        return self.supply


async def _supply(staging: FakeStaging) -> ChainSupply:
    locator = await staging.stage(
        request_scope="scope", name="evidence_map.txt", content=MAP, media_type="text/plain"
    )
    # As `application/chains/packet.py` seals a released, accepted supply.
    provenance = ItemProvenance(
        producer_activation_id="supplier-run",
        accepted_decision_ref="chain-link:link-1:goal_accepted:evidence",
        chain_link_id="link-1",
        provisional=False,
    )
    text = "Mission Chain identity (you are the consumer; the suppliers are read-only)"
    return ChainSupply(
        bindings=(
            ContextBinding(binding_name=BINDING, expand=ExpandMode.MATERIALIZE, mandatory=True),
        ),
        candidates=(
            PackCandidate(
                source_kind=ContextSourceKind.CHAIN_SUPPLY,
                source_ref="artifact://supplier/evidence_map",
                binding_name=BINDING,
                content_digest=_digest(MAP),
                bytes=len(MAP),
                media_type="text/plain",
                trust=ContextTrust.UNTRUSTED_CONTENT,
                mandatory=True,
                file_name="evidence_map.txt",
                durable_ref=locator,
                provenance=provenance,
            ),
            PackCandidate(
                source_kind=ContextSourceKind.CHAIN_SUPPLY,
                source_ref="chain://chain-1/links/e4-brief",
                content_digest=_digest(text.encode()),
                bytes=len(text.encode()),
                media_type="text/plain",
                trust=ContextTrust.AUTHORITATIVE,
                expand=ExpandMode.INLINE,
                text=text,
                provenance=provenance,
            ),
            PackCandidate(
                source_kind=ContextSourceKind.JOURNAL_DIGEST,
                source_ref="journal://supplier-run/final",
                content_digest=_digest(b"frontier"),
                bytes=0,
                media_type="application/json",
                trust=ContextTrust.AUTHORITATIVE,
                mandatory=True,
                expand=ExpandMode.REFERENCE,
                summary="journal digest of supplier `e4-evidence`",
                retrieval=RetrievalInstruction(
                    kind=RetrievalKind.MISSIONCTL, command="missionctl run transcript supplier-run"
                ),
            ),
        ),
    )


async def _service() -> tuple[ContextPackService, FakeChainSupplies]:
    staging = FakeStaging()
    supplies = FakeChainSupplies(await _supply(staging))
    service = ContextPackService(
        artifacts=FakeArtifacts({}, scope=None),
        selections=FakeSelections(),
        staging=staging,
        chain_supplies=supplies,
    )
    return service, supplies


def _template() -> Any:
    from tests.acceptance.control_plane.test_wp_cp_040 import exact_fixture
    from tests.fixtures.goal_directed_journaled import goal_templates

    binding, _profile, _bundle = exact_fixture()
    return goal_templates(binding)["verifier"]


@pytest.mark.asyncio
async def test_the_verifier_packet_carries_the_chain_supply_the_executor_received() -> None:
    run_id = "l1-06-chain-verifier"
    service, supplies = await _service()
    claim = await _claim(run_id)
    result = replace(_executor_result(claim, run_id), workspace_id=claim.workspace_namespace)
    request = _preparation(run_id, claim, "verifier", 3, 1, result)

    sealed = await service.pack_for_iteration(request, _template(), role_root="/goal/1/verifier")

    assert supplies.asked == [run_id]
    items = sealed.packet.items
    supplied = [item for item in items if item.binding_name == BINDING]
    assert len(supplied) == 1
    (artifact,) = supplied
    assert artifact.materialize is not None
    assert artifact.materialize.path.startswith(f"/goal/1/verifier/inputs/{BINDING}/")
    assert any(item.source_ref == "chain://chain-1/links/e4-brief" for item in items)
    # The supplier's history references are not the verifier's evidence.
    assert not any(item.source_ref.startswith("journal://supplier-run") for item in items)
    # Its subject still crosses, and the executor's handoff never does.
    kinds = {item.source_kind for item in items}
    assert ContextSourceKind.ACCEPTED_OUTPUT in kinds
    assert ContextSourceKind.PROGRESS_REVIEW not in kinds
    assert ContextSourceKind.JOURNAL_DIGEST not in kinds


@pytest.mark.asyncio
async def test_the_verifier_goal_text_is_framed_as_the_executor_specification() -> None:
    run_id = "l1-06-goal-frame"
    service, _supplies = await _service()
    claim = await _claim(run_id)
    result = replace(_executor_result(claim, run_id), workspace_id=claim.workspace_namespace)
    sealed = await service.pack_for_iteration(
        _preparation(run_id, claim, "verifier", 3, 1, result),
        _template(),
        role_root="/goal/1/verifier",
    )
    (goals,) = [
        item
        for item in sealed.packet.items
        if item.source_kind == ContextSourceKind.GOALS_AND_CRITERIA
    ]
    assert goals.inline is not None
    assert goals.inline.text.startswith(
        "Goal specification (the executor's instruction; judge its outputs against it, "
        "do not perform its steps): "
    )
    executor = await service.pack_for_iteration(
        _preparation(run_id, claim, "executor", 2, 0), _template(), role_root="/goal/1/executor"
    )
    (executor_goals,) = [
        item
        for item in executor.packet.items
        if item.source_kind == ContextSourceKind.GOALS_AND_CRITERIA
    ]
    assert executor_goals.inline is not None
    assert executor_goals.inline.text.startswith("Objective: ")
