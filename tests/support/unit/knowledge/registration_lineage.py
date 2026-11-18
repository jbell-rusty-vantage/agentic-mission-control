"""Builders, constants and fakes that other test files import.

Moved from tests/unit/knowledge/test_registration_lineage.py.
"""

from mission_control.application.ports.knowledge import LineageEntry
from mission_control.domain.knowledge.lineage import ActorKind, LineageFact, ProvenanceRole


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
