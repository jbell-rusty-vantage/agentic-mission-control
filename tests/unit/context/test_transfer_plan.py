"""The sealed transfer plan's pure rules (OUTPUT-CONTRACTS §6; ADR-0061; WI-02 / OVE-164)."""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from mission_control.domain.context.transfer import (
    BackendCapabilities,
    Boundary,
    ExactMember,
    HostOverhead,
    InputSource,
    MemberDelivery,
    ReceiverRef,
    ResourceBounds,
    ResourceUsage,
    SealedTransferPlan,
    TransferInput,
    TransferRefusal,
    TransferSelection,
    account,
    readiness,
    render_index,
    render_inline_section,
    seal_plan,
)

SCOPE = "installation:1/application:biotech/tenant:2"
RECEIVER = ReceiverRef(scope=SCOPE, run_id="run-1", operation_id="op-consumer")
SANDBOX = BackendCapabilities(custody_backend="mc-custody", file_capable=True, binary_capable=True)
STATE = BackendCapabilities(custody_backend="mc-custody", file_capable=True, binary_capable=False)
TEXT_ONLY = BackendCapabilities(
    custody_backend="mc-custody", file_capable=False, binary_capable=False
)
OVERHEAD = HostOverhead(host_state_tokens=1_000, tool_schema_tokens=500, skill_tokens=200)


def bounds(window: int = 100_000, **overrides: int) -> ResourceBounds:
    values = {
        "window_tokens": window,
        "generation_reserve_tokens": 4_000,
        "tool_result_reserve_tokens": 2_000,
        "inline_bytes_ceiling": 8_000,
        "file_bytes_ceiling": 1_000_000,
        "file_count_ceiling": 16,
    } | overrides
    return ResourceBounds(**values)


def digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def member(binding: str, part: str, content: bytes, **fields: object) -> ExactMember:
    media = fields.pop("media_type", "text/markdown")
    return ExactMember.model_validate(
        {
            "member_key": f"{binding}/{part}",
            "binding": binding,
            "part": part,
            "source_kind": fields.pop("source_kind", "produced_output"),
            "source_ref": fields.pop("source_ref", f"rev-{binding}"),
            "revision": "r7@1",
            "issuer": "mission-control",
            "digest": digest(content),
            "size_bytes": len(content),
            "media_type": media,
            "file_name": fields.pop("file_name", f"{part}.md"),
            "purpose": fields.pop("purpose", "dependent_input"),
            "required": fields.pop("required", True),
            "custody_ref": fields.pop("custody_ref", f"custody://{digest(content)}"),
            "access_ref": "rev",
            **fields,
        }
    )


def selection(*inputs: TransferInput, **fields: object) -> TransferSelection:
    return TransferSelection.model_validate(
        {
            "boundary": fields.pop("boundary", Boundary.DEPENDENT_STAGE),
            "receiver_position": "consumer",
            "inputs": inputs,
            "bounds": fields.pop("bounds", bounds()),
            "backend": fields.pop("backend", SANDBOX),
            **fields,
        }
    )


def report_input(name: str = "report", **fields: object) -> TransferInput:
    return TransferInput.model_validate(
        {
            "name": name,
            "source": InputSource.produced("producer", "report"),
            "purpose": fields.pop("purpose", "dependent_input"),
            **fields,
        }
    )


def report_members(name: str = "report", body: bytes = b"# R7\nexact body\n") -> list[ExactMember]:
    return [
        member(name, "body", body, file_name="body.md"),
        member(
            name,
            "ledger",
            b'{"assertions":[]}',
            media_type="application/json",
            file_name="ledger.json",
        ),
        member(
            name,
            "manifest",
            b'{"report":"r7"}',
            media_type="application/json",
            file_name="manifest.json",
        ),
    ]


def seal(sel: TransferSelection, members: list[ExactMember], **fields: object):
    texts = fields.pop(
        "inline_texts",
        {m.member_key: '{"report":"r7"}' for m in members if m.part == "manifest"},
    )
    return seal_plan(
        plan_id="plan-1",
        receiver=RECEIVER,
        selection=sel,
        configuration_ref="erc:sha256:" + "0" * 64,
        host_state_ref=None,
        members=members,
        overhead=fields.pop("overhead", OVERHEAD),
        inline_texts=texts,
        **fields,
    )


# ---------------------------------------------------------------- sources and selection


def test_a_source_carries_exactly_its_own_kind_of_identity() -> None:
    assert InputSource.literal("text/plain@1", "x").kind == "typed_literal"
    with pytest.raises(ValidationError):
        InputSource(kind="exact_artifact", artifact_ref="artifact://a/b")  # no pinned digest
    with pytest.raises(ValidationError):
        InputSource(
            kind="produced_output", position="p", output_key="o", artifact_ref="artifact://x"
        )
    with pytest.raises(ValidationError):
        InputSource(kind="application_selector", binding_pin="app@1")


def test_first_invocation_invents_no_predecessor_and_evaluators_are_isolated() -> None:
    with pytest.raises(ValidationError, match="invents no predecessor"):
        selection(report_input(), boundary=Boundary.FIRST_INVOCATION)
    with pytest.raises(ValidationError, match="independent"):
        selection(report_input(purpose="evaluation_subject"), boundary=Boundary.EVALUATOR)
    with pytest.raises(ValidationError, match="cannot receive"):
        selection(
            report_input(purpose="evaluation_subject"),
            report_input("sibling", purpose="dependent_input"),
            boundary=Boundary.EVALUATOR,
            isolation="independent_evaluator",
        )


# ---------------------------------------------------------------- placement and sealing


def test_report_review_places_index_inline_bodies_as_files_and_seals_a_digest() -> None:
    plan = seal(selection(report_input()), report_members())
    assert isinstance(plan, SealedTransferPlan)
    placements = {item.member_key: item.placement for item in plan.placements}
    assert placements == {
        "report/body": "file",
        "report/ledger": "file",
        "report/manifest": "inline",
    }
    paths = {item.path for item in plan.placements if item.path}
    assert paths == {"/inputs/report/r7_1/body.md", "/inputs/report/r7_1/ledger.json"}
    # Immutable and self-verifying: the digest covers every member and placement.
    tampered = plan.model_dump(mode="json")
    tampered["exact_sources"][0]["digest"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError, match="digest mismatch"):
        SealedTransferPlan.model_validate(tampered)
    again = seal(selection(report_input()), report_members())
    assert isinstance(again, SealedTransferPlan) and again.digest == plan.digest


def test_prompt_index_and_files_come_from_the_identical_selection() -> None:
    plan = seal(selection(report_input()), report_members())
    assert isinstance(plan, SealedTransferPlan)
    index = render_index(plan)
    section = render_inline_section(plan, {"report/manifest": '{"report":"r7"}'})
    by_key = {item["member"]: item for item in index["inputs"]}
    for exact in plan.exact_sources:
        assert by_key[exact.member_key]["digest"] == exact.digest
        assert exact.digest in section
    assert index["plan"] == plan.ref
    assert "not instructions" in section and "```" in section


def test_index_retains_exact_report_access_separate_from_selected_part_digest() -> None:
    report_digest = "sha256:" + "a" * 64
    access_ref = f"kh:binding/report/r7@report.v1#digest={report_digest}"
    members = [item.model_copy(update={"access_ref": access_ref}) for item in report_members()]
    plan = seal(selection(report_input()), members)
    assert isinstance(plan, SealedTransferPlan)
    index = render_index(plan)
    for item in index["inputs"]:
        assert item["access_ref"] == access_ref
        assert item["digest"] != report_digest


def test_required_inline_never_silently_becomes_a_file() -> None:
    big = "x" * 9_000
    literal = TransferInput(
        name="brief",
        source=InputSource.literal("text/plain@1", big),
        purpose="dependent_input",
        placement="inline",
    )
    content = big.encode()
    item = member(
        "brief",
        "value",
        content,
        source_kind="typed_literal",
        media_type="text/plain",
        file_name="brief.txt",
    )
    refused = seal(selection(literal), [item], inline_texts={"brief/value": big})
    assert isinstance(refused, TransferRefusal) and refused.code == "INLINE_CEILING_EXCEEDED"
    # Only an authored alternative may replace it.
    allowed = literal.model_copy(update={"alternatives": ("file",)})
    plan = seal(selection(allowed), [item], inline_texts={"brief/value": big})
    assert isinstance(plan, SealedTransferPlan) and plan.placements[0].placement == "file"


def test_files_need_a_file_capable_backend_and_binary_a_byte_capable_one() -> None:
    refused = seal(selection(report_input(), backend=TEXT_ONLY), report_members())
    assert isinstance(refused, TransferRefusal) and refused.code == "FILE_UNSUPPORTED_BY_BACKEND"
    figure = TransferInput(
        name="figure",
        source=InputSource.artifact("artifact://run/fig.png", digest(b"\x89PNG")),
        purpose="dependent_input",
    )
    png = member(
        "figure",
        "artifact",
        b"\x89PNG",
        media_type="image/png",
        file_name="fig.png",
        source_kind="exact_artifact",
    )
    refused = seal(selection(figure, backend=STATE), [png], inline_texts={})
    assert isinstance(refused, TransferRefusal) and refused.code == "BINARY_UNSUPPORTED_BY_BACKEND"
    plan = seal(selection(figure), [png], inline_texts={})
    assert isinstance(plan, SealedTransferPlan)


def test_optional_unplaceable_members_are_visible_omissions() -> None:
    optional = report_input(required=False)
    members = [m.model_copy(update={"required": False}) for m in report_members()]
    plan = seal(selection(optional, backend=TEXT_ONLY), members)
    assert isinstance(plan, SealedTransferPlan)
    assert {o.member_key for o in plan.omissions} == {"report/body", "report/ledger"}
    assert "omitted `report`" in render_inline_section(plan, {"report/manifest": '{"report":"r7"}'})


def test_evidence_handles_need_a_retrieval_capability_only_when_required() -> None:
    evidence = member(
        "report",
        "evidence",
        b'["e1"]',
        media_type="application/json",
        file_name="evidence.json",
        handles=("kh:b/report/r7#evidence:e1",),
        custody_ref=None,
    )
    members = [*report_members(), evidence]
    plan = seal(selection(report_input()), members)
    assert isinstance(plan, SealedTransferPlan)
    assert [o.code for o in plan.omissions] == ["PLACEMENT_UNAVAILABLE"]
    refused = seal(selection(report_input(evidence_required=True)), members)
    assert isinstance(refused, TransferRefusal) and refused.code == "NO_RETRIEVAL_CAPABILITY"
    plan = seal(
        selection(report_input(evidence_required=True)),
        members,
        retrieval_tools=("knowledge_read",),
    )
    assert isinstance(plan, SealedTransferPlan)
    assert {p.member_key: p.placement for p in plan.placements}["report/evidence"] == "handle"


def test_unselected_members_and_evaluator_leaks_are_refused() -> None:
    stray = member("sibling", "body", b"other")
    refused = seal(selection(report_input()), [*report_members(), stray])
    assert isinstance(refused, TransferRefusal) and refused.code == "UNSELECTED_MEMBER"
    evaluator = selection(
        report_input(purpose="evaluation_subject"),
        boundary=Boundary.EVALUATOR,
        isolation="independent_evaluator",
    )
    scratch = [m.model_copy(update={"purpose": "producer_scratch"}) for m in report_members()]
    refused = seal(evaluator, scratch)
    assert isinstance(refused, TransferRefusal) and refused.code == "EVALUATOR_ISOLATION"


# ---------------------------------------------------------------- aggregate accounting


def test_accounting_counts_host_tools_skills_index_inline_files_and_reserves_once() -> None:
    files = report_members()[:2]
    plan = account(
        bounds=bounds(),
        overhead=OVERHEAD,
        index_tokens=50,
        inline_texts=["abcde"],
        file_members=files,
        counter=_Exact(),
    )
    file_tokens = sum((2 * m.size_bytes + 4) // 5 for m in files)
    assert plan.total_tokens == 1_000 + 500 + 200 + 50 + 5 + file_tokens + 4_000 + 2_000
    assert plan.file_count == 2 and plan.file_bytes == sum(m.size_bytes for m in files)
    assert plan.fits


@pytest.mark.parametrize(
    ("overrides", "overhead"),
    [
        ({"window_tokens": 7_500}, OVERHEAD),  # reserves + host overflow the window
        ({"file_bytes_ceiling": 10}, OVERHEAD),  # aggregate file bytes, not per report
        ({"file_count_ceiling": 1}, OVERHEAD),
        ({}, HostOverhead(host_state_tokens=90_000, tool_schema_tokens=5_000, skill_tokens=0)),
    ],
)
def test_combined_prompt_file_and_reserve_overflow_refuses(overrides, overhead) -> None:
    refused = seal(
        selection(report_input(), bounds=bounds(**overrides)), report_members(), overhead=overhead
    )
    assert isinstance(refused, TransferRefusal) and refused.code == "RESOURCE_EXCEEDED"


# ---------------------------------------------------------------- readiness


def _deliveries(plan: SealedTransferPlan, **broken: str) -> list[MemberDelivery]:
    out = []
    for placed in plan.placements:
        exact = plan.member(placed.member_key)
        fault = broken.get(exact.part)
        out.append(
            MemberDelivery(
                member_key=exact.member_key,
                placement=placed.placement,
                path_or_handle=placed.path or "prompt",
                required_digest=exact.digest,
                observed_digest=("sha256:" + "e" * 64) if fault == "corrupt" else exact.digest,
                probe="backend_read" if placed.placement == "file" else "prompt",
                readable=fault != "unreadable",
                access_ok=fault != "revoked",
                code={"unreadable": "BACKEND_UNREADABLE", "revoked": "ACCESS_REVOKED"}.get(
                    fault or ""
                ),
            )
        )
    return out


@pytest.mark.parametrize(
    ("fault", "code"),
    [
        ("unreadable", "BACKEND_UNREADABLE"),
        ("corrupt", "DIGEST_MISMATCH"),
        ("revoked", "ACCESS_REVOKED"),
    ],
)
def test_readiness_needs_content_access_backend_and_resources(fault, code) -> None:
    plan = seal(selection(report_input()), report_members())
    assert isinstance(plan, SealedTransferPlan)
    usage = ResourceUsage(overhead=OVERHEAD, total_tokens=10, headroom_tokens=1)
    assert readiness(plan, _deliveries(plan), usage) == ("ready", ())
    result, findings = readiness(plan, _deliveries(plan, body=fault), usage)
    assert (
        result == "refused" and findings[0].code == code and findings[0].member_key == "report/body"
    )
    over = ResourceUsage(overhead=OVERHEAD, total_tokens=10, headroom_tokens=-1)
    assert readiness(plan, _deliveries(plan), over)[1][0].code == "RESOURCE_EXCEEDED"


class _Exact:
    exact = True

    def count(self, text: str) -> int:
        return len(text)


def test_dependent_inputs_default_optional_and_required_blocks() -> None:
    """N4 (WI-03 B1, OVE-169, OVE-171 C): required now that production promotes accepted heads;
    a missing producer revision blocks the receiver; an authored optional binding (named in
    ``optional``) is the only opt-out."""

    from mission_control.domain.context import transfer_builders as builders

    assert builders.DEPENDENT_INPUT_REQUIRED is True
    optional = builders.dependent_stage(
        selection(), [("report", "draft", "draft.report")], optional={"report"}
    )
    required = builders.dependent_stage(selection(), [("report", "draft", "draft.report")])
    assert [item.required for item in optional.inputs] == [False]
    assert [item.required for item in required.inputs] == [True]
    assert not isinstance(seal(optional, []), TransferRefusal)
    blocked = seal(required, [])
    assert isinstance(blocked, TransferRefusal) and blocked.code == "REQUIRED_INPUT_UNRESOLVED"
