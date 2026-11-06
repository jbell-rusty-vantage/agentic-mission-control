"""WI-05 (OVE-167): Mission Control runs only against Knowledge Services component 2.5.0 or later.

The startup ``knowledge.describe`` preflight refuses a binding whose pinned component predates the
dispatch journal (2.5.0, migration 0008): without it a native commit whose protocol receipt was
lost cannot be reconstructed and would stay unresolved.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_control.bootstrap.composition import (
    MIN_KNOWLEDGE_COMPONENT,
    knowledge_component_supported,
)
from mission_control.contracts.knowledge_protocol_results import BindingDescriptor
from tests.fixtures.knowledge_binding import describe_document

# Captured from the REAL Knowledge Services executor composition (KS `sprint-oc-wi05`,
# `createAiEngineerPostgresBackend` over a disposable component 2.5.0 installation, then
# `KnowledgeOperationService.describe`). The name is produced by KS
# `packages/bindings/aiengineer-postgres/src/component-backend.ts`:
# ``name: `knowledge-verification-${component.componentVersion}` ``.
REAL_DESCRIPTOR = (
    Path(__file__).resolve().parents[2]
    / "fixtures"
    / "knowledge_protocol"
    / "real-describe.aiengineer-postgres.json"
)


@pytest.mark.parametrize(
    ("name", "supported"),
    [
        ("knowledge-verification-2.5.0", True),
        ("knowledge-verification-2.10.1", True),
        ("knowledge-verification-3.0.0", True),
        ("knowledge-verification-2.4.0", False),
        ("knowledge-verification-1.9.9", False),
        ("knowledge-verification-in-memory", False),
        ("knowledge-verification", False),
        ("biotech-graph-unwired", False),
    ],
)
def test_the_component_gate_requires_2_5_0_or_later(name: str, supported: bool) -> None:
    assert MIN_KNOWLEDGE_COMPONENT == (2, 5, 0)
    assert knowledge_component_supported(name) is supported


def test_the_parity_fake_describes_a_supported_component() -> None:
    descriptor = describe_document("biotech-graph", "biotech", "independent")
    assert knowledge_component_supported(descriptor["pinnedSchema"]["name"])


def test_the_real_ks_descriptor_passes_the_gate_and_an_older_component_does_not() -> None:
    document = json.loads(REAL_DESCRIPTOR.read_text(encoding="utf-8"))
    descriptor = BindingDescriptor.model_validate(document)
    assert descriptor.pinnedSchema.name == "knowledge-verification-2.5.0"
    assert knowledge_component_supported(descriptor.pinnedSchema.name)
    older = dict(
        document, pinnedSchema=dict(document["pinnedSchema"], name="knowledge-verification-2.4.0")
    )
    assert not knowledge_component_supported(
        BindingDescriptor.model_validate(older).pinnedSchema.name
    )
