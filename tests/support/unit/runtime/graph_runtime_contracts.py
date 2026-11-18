"""Builders, constants and fakes that other test files import.

Moved from tests/unit/runtime/test_graph_runtime_contracts.py.
"""

from __future__ import annotations

from mission_control.domain.graph_runtime.definitions import (
    ContentAddressedRef,
    RuntimeDefinitionKind,
)

DIGEST = "sha256:" + "a" * 64


def ref(kind: RuntimeDefinitionKind, name: str, digest: str = DIGEST) -> ContentAddressedRef:
    return ContentAddressedRef(
        kind=kind,
        logical_id=name,
        schema_version="1",
        digest=digest,
    )
