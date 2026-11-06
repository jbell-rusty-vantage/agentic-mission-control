"""KS trusted operation ids: Mission Control's mirror against golden vectors KS's own code made.

`trusted_operation_id` mirrors a private KS expression (knowledge-services
`packages/host/src/knowledge-operation/service.ts`, `shortDigest`). The vectors in
`tests/fixtures/knowledge_protocol/ks-operation-id-parity.json` were computed by that exact source
text with KS's built `digestCanonical` (`scripts/ks_operation_id_parity.mjs`, provenance in the
fixture), so a KS drift fails here when the fixture is regenerated. The fake KS uses the same
function, so this is the only independent check of the derivation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mission_control.contracts.knowledge_protocol import trusted_operation_id

FIXTURE = (
    Path(__file__).resolve().parents[2] / "fixtures/knowledge_protocol/ks-operation-id-parity.json"
)
DOCUMENT = json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_fixture_names_its_ks_provenance() -> None:
    provenance = DOCUMENT["provenance"]
    assert provenance["knowledgeServicesCommit"] == "f8d5e48603ee7f6b0e76d6632d04245394846c96"
    assert provenance["shortDigestBody"] == "return digestCanonical(value).slice(7, 39);"
    assert "operation.replace" in provenance["idExpression"]


@pytest.mark.parametrize("vector", DOCUMENT["vectors"], ids=lambda v: v["operation"])
def test_the_mirror_reproduces_ks_operation_ids(vector: dict[str, Any]) -> None:
    assert (
        trusted_operation_id(vector["tenant"], vector["operation"], vector["requestId"])
        == vector["operationId"]
    )
