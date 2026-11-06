"""W1 D1: the host computes every digest of a report registration; the model supplies content.

The parity fixture (``ks-registration-parity.json``) is one complete ``research-report/v2``
registration built and schema-checked by the KS libraries themselves (``recordRef``,
``qualifiersDigest``, ``digestBytes``, research-core strict schemas). Its model-shaped content
(no producer, no in-registration digests, references by id) must canonicalize to exactly those
bytes; tampering with any submitted content changes the digests that depend on it, and a stale
or forged digest is refused, typed.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import CURRENT_INVOCATION
from mission_control.application.knowledge.report_registration import (
    RegistrationRefused,
    canonical_registration,
)
from mission_control.contracts.knowledge_protocol import Origin, digest_bytes, digest_canonical
from tests.fixtures.knowledge_binding import BINDING, model_content, model_report
from tests.unit.knowledge.test_gateway import TENANT
from tests.unit.knowledge.test_knowledge_tools import lane

PARITY = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "knowledge_protocol")
    .joinpath("ks-registration-parity.json")
    .read_text(encoding="utf-8")
)
EXPECTED: dict[str, Any] = PARITY["expected"]
PRODUCER = Origin.model_validate(PARITY["producer"])


def canonical(content: dict[str, Any]) -> dict[str, Any]:
    return canonical_registration(
        content, tenant=PARITY["tenant"], binding=PARITY["binding"], producer=PRODUCER
    )


def refused(content: dict[str, Any]) -> str:
    with pytest.raises(RegistrationRefused) as error:
        canonical(content)
    return error.value.code


def content() -> dict[str, Any]:
    return model_content(EXPECTED)


def test_model_shaped_content_is_exactly_the_ks_built_registration() -> None:
    shaped = content()
    # The model's content carries no digest of the registration's own records and no origin.
    assert "producer" not in json.dumps(shaped)
    # Only an external assertion keeps its qualifier digest; only a non-quote fragment its own.
    assert ["qualifiersDigest" in item for item in shaped["supportSets"]] == [False, False, True]
    assert ["selectedDigest" in item for item in shaped["fragments"]] == [False, False, True]
    assert shaped["supportSets"][0]["assertion"] == "asr-mistral-7b"
    assert canonical(shaped) == EXPECTED
    assert digest_canonical(canonical(shaped)) == digest_canonical(EXPECTED)
    # Deterministic: the same content, scope and producer give the same bytes.
    assert canonical(content()) == canonical(shaped)


def test_a_supplied_digest_equal_to_the_exact_one_is_accepted() -> None:
    shaped = content()
    shaped["supportSets"][0]["assertion"] = EXPECTED["supportSets"][0]["assertion"]
    shaped["supportSets"][0]["qualifiersDigest"] = EXPECTED["supportSets"][0]["qualifiersDigest"]
    shaped["fragments"][0]["selectedDigest"] = EXPECTED["fragments"][0]["selectedDigest"]
    assert canonical(shaped) == EXPECTED


def test_tampered_content_changes_every_digest_that_depends_on_it() -> None:
    shaped = content()
    shaped["assertions"][0]["proposition"] = "Mistral 7B has 8 billion parameters."
    tampered = canonical(shaped)
    original = EXPECTED["supportSets"][0]["assertion"]["digest"]
    assert tampered["supportSets"][0]["assertion"]["digest"] != original
    # The derivation names it as a premise, so the derivation's own digest moves too.
    assert tampered["assertions"][2]["premises"][0]["digest"] != original
    assert (
        tampered["supportSets"][1]["assertion"]["digest"]
        != EXPECTED["supportSets"][1]["assertion"]["digest"]
    )

    quoted = content()
    quote = quoted["fragments"][0]["selector"]["value"]
    quoted["fragments"][0]["selector"]["value"] = quote.replace("7-billion", "7 billion")
    moved = canonical(quoted)
    exact = moved["fragments"][0]["selector"]["value"].encode("utf-8")
    assert moved["fragments"][0]["selectedDigest"] == digest_bytes(exact)
    assert moved["fragments"][0]["selectedDigest"] != EXPECTED["fragments"][0]["selectedDigest"]
    cited = moved["report"]["structuredBody"]["sections"][0]["blocks"][0]["inlines"][1]
    assert (
        cited["fragment"]["digest"]
        != EXPECTED["supportSets"][0]["required"][0]["evidence"][0]["digest"]
    )


def test_registration_shapes_beyond_text_quotes() -> None:
    """A page-region fragment keeps its given digest and size (the host holds no capture), a
    support set for an earlier report's assertion keeps its external ref and qualifier digest,
    and table cells and captions resolve their claims and citations."""

    shaped = content()
    region = shaped["fragments"][2]
    assert region["selector"]["kind"] == "page_region" and "selectedDigest" in region
    external = shaped["supportSets"][2]
    assert isinstance(external["assertion"], dict) and "qualifiersDigest" in external
    assert external["contrary"] == ["frag-mistral-7b"]
    table = shaped["report"]["structuredBody"]["sections"][0]["blocks"][2]
    assert table["rows"][0][1][0]["assertion"] == "asr-gemma-2-27b"
    done = canonical(shaped)
    assert done["fragments"][2] == EXPECTED["fragments"][2]
    assert done["supportSets"][2] == EXPECTED["supportSets"][2]
    assert done["report"] == EXPECTED["report"]


def test_selected_bytes_are_exact_utf8_never_normalized() -> None:
    gemma = EXPECTED["fragments"][1]
    raw = gemma["selector"]["value"].encode("utf-8")
    assert gemma["selectedSize"] == len(raw) > len(gemma["selector"]["value"])  # non-ASCII
    assert canonical(content())["fragments"][1]["selectedDigest"] == digest_bytes(raw)


def test_a_stale_or_forged_digest_is_refused() -> None:
    stale = content()
    stale["supportSets"][0]["assertion"] = EXPECTED["supportSets"][0]["assertion"]
    stale["assertions"][0]["proposition"] = "Mistral 7B has 8 billion parameters."
    assert refused(stale) == "REF_DIGEST_MISMATCH"

    forged = content()
    forged["fragments"][0]["selectedDigest"] = digest_bytes(b"another quote")
    assert refused(forged) == "SELECTED_DIGEST_MISMATCH"

    qualifiers = content()
    qualifiers["supportSets"][0]["qualifiersDigest"] = digest_bytes(b"x")
    assert refused(qualifiers) == "REF_DIGEST_MISMATCH"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda c: c["assertions"][0].update(producer=PARITY["producer"]), "PRODUCER_HOST_OWNED"),
        (lambda c: c.update(extra=1), "REGISTRATION_MALFORMED"),
        (lambda c: c["assertions"][0].update(riskReasons=[0.5]), "REGISTRATION_MALFORMED"),
        (lambda c: c["fragments"][0].update(tenant="another-tenant"), "RECORD_SCOPE_MISMATCH"),
        (lambda c: c["supportSets"][0].update(assertion="asr-unknown"), "REF_UNRESOLVED"),
        # S1: an external reference never names another tenant or binding.
        (lambda c: c["task"]["rubric"].update(tenant="another-tenant"), "RECORD_SCOPE_MISMATCH"),
        (
            lambda c: c["supportSets"][2]["assertion"].update(binding="biotech-graph"),
            "RECORD_SCOPE_MISMATCH",
        ),
        (lambda c: c["fragments"][2]["capture"].update(tenant="x"), "RECORD_SCOPE_MISMATCH"),
        (lambda c: c["supportSets"][2].pop("qualifiersDigest"), "REF_UNRESOLVED"),
        (lambda c: c["fragments"][2].pop("selectedDigest"), "SELECTED_DIGEST_REQUIRED"),
        (lambda c: c["task"].update(rubric={"id": "rubric-engineering"}), "REF_UNRESOLVED"),
        (
            lambda c: c["fragments"][0]["selector"].update(kind="xpath"),
            "SELECTED_DIGEST_REQUIRED",
        ),
        (
            lambda c: c["assertions"][0].update(premises=["asr-ratio"]),
            "REF_CYCLE",
        ),
        (
            lambda c: c["fragments"].append(copy.deepcopy(c["fragments"][0])),
            "REGISTRATION_MALFORMED",
        ),
    ],
)
def test_malformed_content_is_refused_typed(mutate: Any, code: str) -> None:
    shaped = content()
    mutate(shaped)
    assert refused(shaped) == code


async def test_a_model_shaped_report_registers_through_the_tool_with_host_digests() -> None:
    """The ordinary `report_register` act: no digest from the model; the binding receives the
    host-canonical payload whose producer is the attempt's origin; a replay is the same effect."""

    h = lane()
    token = CURRENT_INVOCATION.set(h.live())
    try:
        first = await h.call("report_register", {"report": model_report("report-d1")}, "c-1")
        replay = await h.call("report_register", {"report": model_report("report-d1")}, "c-2")
        malformed = await h.call(
            "report_register", {"report": {**model_report("report-x"), "origin": {}}}, "c-3"
        )
    finally:
        CURRENT_INVOCATION.reset(token)
    assert first["ok"] and first["result"]["journal_state"] == "applied"
    assert replay["ok"] and replay["result"]["effect_key"] == first["result"]["effect_key"]
    assert malformed["refusal"]["code"] == "REGISTRATION_MALFORMED"
    (sent,) = h.fake.calls_of("invoke")  # the replay settled from the journal; nothing resent
    assert sent.envelope is not None and sent.envelope.input is not None
    payload = sent.envelope.input.inlinePayload
    assert isinstance(payload, dict)
    (assertion,) = payload["assertions"]
    assert assertion["producer"]["mission"]["operationId"] == "stage/draft"
    assert assertion["producer"]["installationId"] == sent.claims.origin.installationId
    assert (assertion["tenant"], assertion["binding"]) == (TENANT, BINDING)
    (support,) = payload["supportSets"]
    assert support["assertion"]["digest"] == digest_canonical(assertion)
    assert support["qualifiersDigest"] == digest_canonical(assertion["qualifiers"])
    (fragment,) = payload["fragments"]
    assert support["required"][0]["evidence"][0]["digest"] == digest_canonical(fragment)
    quote = fragment["selector"]["value"].encode("utf-8")
    assert (fragment["selectedDigest"], fragment["selectedSize"]) == (
        digest_bytes(quote),
        len(quote),
    )


@pytest.mark.parametrize("pair", [True, False])
def test_predecessor_receipt_is_completed_with_host_scope(pair: bool) -> None:
    shaped = content()
    predecessor = {
        "kind": "report",
        "id": "prior-r1",
        "version": "research-report.v2",
        "digest": "sha256:" + "a" * 64,
    }
    shaped["report"]["supersedes"] = (
        {
            "handle": f"kh:{PARITY['binding']}/report/prior-r1@research-report.v2",
            "digest": predecessor["digest"],
        }
        if pair
        else predecessor
    )
    assert canonical(shaped)["report"]["supersedes"] == {
        **predecessor,
        "tenant": PARITY["tenant"],
        "binding": PARITY["binding"],
    }


@pytest.mark.parametrize(
    ("predecessor", "code"),
    [
        (
            {"handle": "kh:other/report/r1@research-report.v2", "digest": "sha256:" + "a" * 64},
            "RECORD_SCOPE_MISMATCH",
        ),
        (
            {
                "handle": "kh:" + PARITY["binding"] + "/assertion/r1@research-report.v2",
                "digest": "sha256:" + "a" * 64,
            },
            "REGISTRATION_MALFORMED",
        ),
        ({"handle": "not-a-handle", "digest": "sha256:" + "a" * 64}, "REF_UNRESOLVED"),
        (
            {
                "handle": "kh:" + PARITY["binding"] + "/report/r1@research-report.v2",
                "digest": "not-a-digest",
            },
            "REF_UNRESOLVED",
        ),
        (
            {
                "kind": "report",
                "id": "r1",
                "version": "research-report.v2",
                "digest": "sha256:" + "a" * 64,
                "tenant": "other",
            },
            "RECORD_SCOPE_MISMATCH",
        ),
    ],
)
def test_predecessor_cannot_widen_scope_or_omit_exact_identity(predecessor, code):
    shaped = content()
    shaped["report"]["supersedes"] = predecessor
    assert refused(shaped) == code


async def test_successor_registration_uses_public_prior_receipt_through_real_tool_binding():
    h = lane()
    token = CURRENT_INVOCATION.set(h.live())
    try:
        first = await h.call("report_register", {"report": model_report("predecessor")}, "r1")
        receipt = first["result"]["affected"][0]
        successor = model_report("successor")
        # The fake registry keys refs by reportId only (unlike KS revision IDs); use a new
        # fake ID here. The real-service joined test proves same logical report repair.
        successor["report"].update(revision=2, supersedes=receipt)
        second = await h.call("report_register", {"report": successor}, "r2")
        assert second["ok"], second
    finally:
        CURRENT_INVOCATION.reset(token)
    sent = h.fake.calls_of("invoke")[-1]
    predecessor = sent.envelope.input.inlinePayload["report"]["supersedes"]
    assert predecessor["tenant"] == TENANT and predecessor["binding"] == BINDING
    assert predecessor["kind"] == "report" and predecessor["digest"] == receipt["digest"]
    assert "handle" not in predecessor
