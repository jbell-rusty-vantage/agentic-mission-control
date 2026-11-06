"""A new registration may reuse immutable bytes without assigning a second creator."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from mission_control.application.ports.knowledge import LineageEntry
from mission_control.domain.knowledge.lineage import ActorKind, LineageFact, ProvenanceRole
from tests.fixtures.knowledge_binding import InMemoryLineageStore, model_report, report_package
from tests.unit.knowledge.test_knowledge_tools import lane
from tests.unit.knowledge.test_w1_tool_boundary import _calls


def registration_entries(origin, handle, digest, receipt):
    common = {"subject_kind": "artifact", "subject_digest": digest}
    return [
        LineageEntry(
            fact=LineageFact(
                subject_handle=handle,
                role=role,
                actor_kind=ActorKind.RECEIPT
                if role is ProvenanceRole.RECEIPT
                else ActorKind.ORIGIN,
                actor_ref=receipt
                if role is ProvenanceRole.RECEIPT
                else "mc-inv:" + origin.digest(),
                actor_origin=None if role is ProvenanceRole.RECEIPT else origin,
                fact={"receipt": receipt},
            ),
            **common,
        )
        for role in (ProvenanceRole.PRODUCER, ProvenanceRole.CALLER, ProvenanceRole.RECEIPT)
    ]


async def test_two_registrations_shared_body_keep_original_producer_and_new_report_producer():
    h = lane()
    access = h.toolset.access(h.live())
    second = h.toolset.access(h.live(attempt=2))
    body = report_package("shared-body", "1", tenant=access.origin.tenant_id).report.model_copy(
        update={"kind": "artifact", "version": "artifact.v1"}
    )
    reports = [
        report_package(name, "1", tenant=access.origin.tenant_id).report
        for name in ("report-first", "report-second")
    ]
    for number, (caller, report) in enumerate(zip((access, second), reports, strict=True)):
        receipt = SimpleNamespace(
            affectedRefs=[body, report],
            nativeReceiptRef=report,
            digest="sha256:" + str(number) * 64,
        )
        result = SimpleNamespace(
            receipt=receipt,
            journal=SimpleNamespace(
                originating_origin=caller.wire_origin(),
                terminal_receipt_ref=f"receipt:{number}",
                knowledge_operation_id=f"operation:{number}",
                effect_key=f"effect:{number}",
            ),
        )
        await h.toolset._record_production(caller, result, replayed=False)
        await h.toolset._record_production(caller, result, replayed=True)
    store = h.toolset.lineage
    facts = await store.facts(
        access.scope, f"kh:{body.binding}/{body.kind}/{body.id}@{body.version}"
    )
    assert [f.actor_ref for f in facts if f.role is ProvenanceRole.PRODUCER] == [
        access.invocation_ref
    ]
    assert {f.actor_ref for f in facts if f.role is ProvenanceRole.CALLER} == {
        access.invocation_ref,
        second.invocation_ref,
    }
    assert len([f for f in facts if f.role is ProvenanceRole.RECEIPT]) == 2
    assert not any(f.role is ProvenanceRole.ADOPTER for f in facts)
    for caller, report in zip((access, second), reports, strict=True):
        facts = await store.facts(
            access.scope, f"kh:{report.binding}/{report.kind}/{report.id}@{report.version}"
        )
        assert [f.actor_ref for f in facts if f.role is ProvenanceRole.PRODUCER] == [
            caller.invocation_ref
        ]


async def test_registration_integrity_refuses_atomically_and_generic_writer_stays_strict():
    h = lane()
    access = h.toolset.access(h.live())
    store = InMemoryLineageStore()
    entries = registration_entries(
        access.origin, "kh:test/artifact/shared@artifact.v1", "sha256:" + "1" * 64, "r1"
    )
    assert (
        await store.record_registration(access.scope, entries, actor_ref="test", at=h.clock.now)
        == 3
    )
    assert (
        await store.record_registration(access.scope, entries, actor_ref="test", at=h.clock.now)
        == 0
    )
    second = registration_entries(
        access.origin.model_copy(update={"attempt": 2}),
        entries[0].fact.subject_handle,
        entries[0].subject_digest,
        "r2",
    )
    with pytest.raises(ValueError, match="one producer"):
        await store.record(access.scope, second, actor_ref="test", at=h.clock.now)
    for field, value in (("subject_digest", "sha256:" + "2" * 64), ("subject_kind", "report")):
        conflicting = [replace(entry, **{field: value}) for entry in second]
        with pytest.raises(ValueError, match="immutable subject identity"):
            await store.record_registration(
                access.scope, conflicting, actor_ref="test", at=h.clock.now
            )
    assert len(store.entries) == 3


async def test_replay_after_native_commit_before_lineage_uses_original_journal_producer():
    h = lane()
    original = h.toolset.access(h.live())
    (first,) = await _calls(h, ("report_register", {"report": model_report("crash-gap")}, "c1"))
    assert first["ok"]
    # Native receipt and journal survived; no lineage transaction committed.
    h.toolset.lineage = InMemoryLineageStore()
    recovered = await h.toolset.dispatch(
        "report_register",
        {"report": model_report("crash-gap")},
        h.live(attempt=2),
        tool_call_id="c2",
    )
    assert recovered["ok"]
    current = h.toolset.access(h.live(attempt=2))
    for item in recovered["result"]["affected"]:
        facts = await h.toolset.lineage.facts(original.scope, item["handle"])
        assert [f.actor_ref for f in facts if f.role is ProvenanceRole.PRODUCER] == [
            original.invocation_ref
        ]
        assert [f.actor_ref for f in facts if f.role is ProvenanceRole.CALLER] == [
            current.invocation_ref
        ]
