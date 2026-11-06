"""WI-02 readSelected: Python reproduces KS ``selected-report-read.v2`` and
``research-report-package.v2`` (golden vectors mirrored from KS ``b046088``).

The fixtures are byte copies of Knowledge Services'
``packages/knowledge-operation-protocol/{fixtures,schemas}``. The MC read client
(:func:`mission_control.application.context.resolution.selected_read`) must produce exactly the
canonical bytes and digest of the vectors; the package model must round-trip the published
package and refuse a widened or inexact one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from mission_control.application.context.resolution import selected_read, selected_read_payload
from mission_control.contracts.knowledge_protocol import (
    SELECTED_READ_CONTRACT,
    Ref,
    ResearchReportPackage,
    SelectedReportRead,
    canonical_json,
    digest_canonical,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_protocol"
GOLDEN = json.loads(
    (FIXTURES / "knowledge-operation-protocol.v2.golden.json").read_text(encoding="utf-8")
)
VECTORS = {vector["id"]: vector for vector in GOLDEN["vectors"]}
INDEX = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))


def _schema(name: str) -> dict:
    return json.loads((FIXTURES / INDEX["schemas"][name]).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "vector_id", ["selected-report-read-members", "selected-report-read-revision"]
)
def test_the_mc_read_client_reproduces_the_ks_canonical_read(vector_id: str) -> None:
    vector = VECTORS[vector_id]
    assert vector["nativeContract"] == SELECTED_READ_CONTRACT
    expected = SelectedReportRead.model_validate(vector["read"])
    selection = vector["read"]["selection"]
    built = selected_read(
        Ref.model_validate(vector["read"]["report"]),
        purpose=vector["read"]["purpose"],
        assertions=None
        if selection["mode"] == "revision"
        else tuple(Ref.model_validate(item) for item in reversed(selection["assertions"])),
        evidence=None
        if selection["mode"] == "revision"
        else tuple(Ref.model_validate(item) for item in selection["evidence"]),
    )
    assert built == expected
    assert canonical_json(built.model_dump(mode="json")) == vector["canonical"]
    assert built.digest() == vector["digest"]
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator(_schema("selected-report-read.v2")).validate(
        selected_read_payload(
            built.report,
            purpose=built.purpose,
            assertions=getattr(built.selection, "assertions", None),
            evidence=getattr(built.selection, "evidence", None),
        )
    )


def test_the_members_package_round_trips_and_answers_its_request() -> None:
    vector = VECTORS["research-report-package-members"]
    package = ResearchReportPackage.model_validate(vector["package"])
    assert package.model_dump(mode="json", by_alias=True) == vector["package"]
    assert digest_canonical(vector["package"]) == vector["digest"]
    assert package.request == VECTORS["selected-report-read-members"]["digest"]
    assert [item.handle.digest for item in (*package.assertions, *package.evidence)] == vector[
        "memberRecordDigests"
    ]
    assert package.body is None and package.ledger is None
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator(_schema("research-report-package.v2")).validate(
        vector["package"]
    )


def _read() -> dict:
    return json.loads(json.dumps(VECTORS["selected-report-read-members"]["read"]))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda read: read | {"purpose": "Not A Purpose"},  # undeclared/unshaped purpose
        lambda read: read | {"exact": False},
        lambda read: read | {"extra": 1},
        lambda read: read | {"selection": {"mode": "members", "assertions": [], "evidence": []}},
        lambda read: (
            read
            | {"selection": {"mode": "members", "assertions": ["assertion-a-1"], "evidence": []}}
        ),
        lambda read: (
            read
            | {
                "selection": {
                    "mode": "members",
                    "assertions": read["selection"]["evidence"],  # a fragment named as an assertion
                    "evidence": [],
                }
            }
        ),
    ],
    ids=["purpose", "inexact", "extra", "empty-members", "bare-id", "wrong-kind"],
)
def test_a_widened_or_malformed_read_is_refused(mutate) -> None:
    with pytest.raises(ValidationError):
        SelectedReportRead.model_validate(mutate(_read()))


def test_a_package_record_that_is_not_its_handle_is_refused() -> None:
    package = json.loads(json.dumps(VECTORS["research-report-package-members"]["package"]))
    package["assertions"][0]["record"]["proposition"] = "A different claim."
    with pytest.raises(ValidationError, match="does not digest to its handle"):
        ResearchReportPackage.model_validate(package)
    whole = json.loads(json.dumps(VECTORS["research-report-package-members"]["package"]))
    whole["selection"] = {"mode": "revision"}
    with pytest.raises(ValidationError, match="revision read carries body and ledger"):
        ResearchReportPackage.model_validate(whole)
