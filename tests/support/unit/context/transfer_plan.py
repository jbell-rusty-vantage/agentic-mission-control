"""Builders, constants and fakes that other test files import.

Moved from tests/unit/context/test_transfer_plan.py.
"""

from __future__ import annotations

import hashlib

from mission_control.domain.context.transfer import (
    BackendCapabilities,
    Boundary,
    ExactMember,
    HostOverhead,
    InputSource,
    MemberDelivery,
    ReceiverRef,
    ResourceBounds,
    SealedTransferPlan,
    TransferInput,
    TransferSelection,
    seal_plan,
)

SCOPE = "installation:1/application:biotech/tenant:2"
RECEIVER = ReceiverRef(scope=SCOPE, run_id="run-1", operation_id="op-consumer")
SANDBOX = BackendCapabilities(custody_backend="mc-custody", file_capable=True, binary_capable=True)


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
