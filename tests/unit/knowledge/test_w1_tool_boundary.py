"""W1 D11/D12/D13/D17: what the first real model runs needed from the knowledge tool boundary.

- D17: Claude Haiku 5.5 sent `report` (an object) as a JSON string in 9 of 10 calls and the
  tool schema refused it. The boundary parses a JSON-object string for an object-typed argument
  exactly once (strict, object required, size bounded), records the coercion in the result, and
  the host-computed bytes and digests are those of the parsed object.
- D11: a KS refusal reached the model with `message: null`; the code, message and field paths
  pass through, bounded and redacted.
- D12: an identical retry of a refused registration replayed the stored rejection as
  `ok: true` without a handle; it now replays the same refusal, a corrected payload registers,
  and an identical retry of a success stays idempotent.
- D13: `submit_output` with a bare promise name is refused with the valid `root.<promise>`-form
  keys of this invocation; the key semantics are unchanged.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from langchain_core.tools import StructuredTool

from mission_control.adapters.deep_agents.knowledge_tools import (
    CURRENT_INVOCATION,
    KnowledgeStructuredTool,
    served_knowledge_tools,
)
from mission_control.adapters.deep_agents.materializer import tool_schema_digest
from mission_control.application.knowledge.toolset import (
    MAX_COERCED_ARGUMENT_BYTES,
    TOOL_DESCRIPTIONS,
    ArgumentCoercionRefused,
    coerce_object_arguments,
    object_argument_shapes,
    refusal_view,
)
from mission_control.application.outputs.fulfillment import OutputFulfillmentService
from mission_control.application.outputs.submission_service import SubmissionService
from mission_control.application.ports.knowledge import KnowledgeProtocolRefusal
from mission_control.contracts.knowledge_protocol import digest_canonical
from mission_control.domain.outputs.contracts import OutputForm
from tests.fixtures.knowledge_binding import model_report
from tests.fixtures.output_contracts import InMemoryOutputContractStore
from tests.unit.knowledge.test_knowledge_tools import BINDING, RUN, Lane, lane
from tests.unit.outputs.scenario import host_access, obligation, promises

pytestmark = pytest.mark.asyncio


async def _calls(h: Lane, *calls: tuple[str, dict[str, Any], str]) -> list[dict[str, Any]]:
    token = CURRENT_INVOCATION.set(h.live())
    try:
        return [await h.call(name, args, call_id) for name, args, call_id in calls]
    finally:
        CURRENT_INVOCATION.reset(token)


# -- D17: object arguments given as JSON strings ------------------------------------------------


def test_only_object_typed_arguments_are_coercible() -> None:
    assert object_argument_shapes("report_register") == {"report": "object"}
    assert object_argument_shapes("report_derive") == {"mapping": "object"}
    assert object_argument_shapes("verify_claims") == {"claims": "object_items"}
    assert object_argument_shapes("knowledge_read") == {"members": "object_items"}
    assert object_argument_shapes("submit_output") == {"items": "object_items"}
    assert object_argument_shapes("knowledge_apply") == {}
    # A string where a string is valid is never reinterpreted.
    same, records = coerce_object_arguments("knowledge_apply", {"decision": '{"a": 1}'})
    assert same == {"decision": '{"a": 1}'} and records == ()


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("not json", "not strict JSON"),
        ("[1, 2]", "is a list, not an object"),
        ('"text"', "is a str, not an object"),
        ('{"a": 1, "a": 2}', "duplicate key"),
        ('{"a": NaN}', "not strict JSON"),
        ('{"a": 1} trailing', "not strict JSON"),
    ],
)
def test_a_string_that_is_not_one_strict_json_object_is_refused(text: str, reason: str) -> None:
    with pytest.raises(ArgumentCoercionRefused, match=reason) as raised:
        coerce_object_arguments("report_register", {"report": text})
    assert raised.value.field == "report"


def test_the_coerced_string_is_size_bounded_and_parsed_once() -> None:
    huge = json.dumps({"x": "y" * MAX_COERCED_ARGUMENT_BYTES})
    with pytest.raises(ArgumentCoercionRefused, match="limit"):
        coerce_object_arguments("report_register", {"report": huge})
    parsed, records = coerce_object_arguments("report_register", {"report": '{"a": "1"}'})
    assert parsed == {"report": {"a": "1"}} and [r.document() for r in records] == [
        {"field": "report", "from": "json_string", "to": "object", "bytes": 10}
    ]
    # Already parsed: a second pass coerces nothing (never twice).
    again, more = coerce_object_arguments("report_register", parsed)
    assert again == parsed and more == ()


async def test_a_report_given_as_a_json_string_registers_with_the_exact_host_digests() -> None:
    as_object, as_string = lane(), lane()
    report = model_report("report-d17")
    (direct,) = await _calls(as_object, ("report_register", {"report": report}, "c-1"))
    (coerced,) = await _calls(as_string, ("report_register", {"report": json.dumps(report)}, "c-1"))
    assert direct["ok"] and coerced["ok"], coerced
    assert "argument_coercions" not in direct
    assert coerced["argument_coercions"] == [
        {
            "field": "report",
            "from": "json_string",
            "to": "object",
            "bytes": len(json.dumps(report).encode()),
        }
    ]
    # The canonical bytes and digests are the parsed object's.
    assert coerced["result"]["effect_key"] == direct["result"]["effect_key"]
    # The effect key is minted over the parsed content's canonical digest (identical above);
    # the host-computed digests of the sent payload are exact over the parsed records.
    (sent,) = as_string.fake.calls_of("invoke")
    assert sent.envelope is not None and sent.envelope.input is not None
    payload = sent.envelope.input.inlinePayload
    assert isinstance(payload, dict)
    (assertion,) = payload["assertions"]
    (support,) = payload["supportSets"]
    (fragment,) = payload["fragments"]
    assert support["assertion"]["digest"] == digest_canonical(assertion)
    assert support["required"][0]["evidence"][0]["digest"] == digest_canonical(fragment)
    assert fragment["selector"]["value"] == report["fragments"][0]["selector"]["value"]


async def test_an_unparseable_object_string_is_a_typed_refusal_without_dispatch() -> None:
    h = lane()
    (refused,) = await _calls(h, ("report_register", {"report": "{not json"}, "c-1"))
    assert refused["ok"] is False
    assert refused["refusal"]["code"] == "INVALID_ENVELOPE"
    assert refused["refusal"]["field_paths"] == ["report"]
    assert "send a JSON object" in refused["refusal"]["message"]
    assert h.fake.calls_of("invoke") == []


async def test_submit_output_items_given_as_json_strings_are_coerced_and_recorded() -> None:
    h = lane()
    (registered,) = await _calls(h, ("report_register", {"report": model_report("r-17")}, "c-1"))
    affected = registered["result"]["affected"]
    report = next(item for item in affected if "/report/" in item["handle"])
    item = json.dumps({"kind": "handle", "ref": report["handle"], "digest": report["digest"]})
    (submitted,) = await _calls(
        h, ("submit_output", {"obligation": "report", "items": [item]}, "c-2")
    )
    assert submitted["ok"], submitted
    assert submitted["argument_coercions"][0]["field"] == "items[0]"


async def test_a_list_of_objects_sent_whole_as_a_json_string_is_coerced() -> None:
    """Review N3: `items` (a list of objects) given as one JSON-array string."""

    h = lane()
    (registered,) = await _calls(h, ("report_register", {"report": model_report("r-n3")}, "c-1"))
    report = next(i for i in registered["result"]["affected"] if "/report/" in i["handle"])
    items = json.dumps([{"kind": "handle", "ref": report["handle"], "digest": report["digest"]}])
    (submitted,) = await _calls(
        h, ("submit_output", {"obligation": "report", "items": items}, "c-2")
    )
    assert submitted["ok"], submitted
    assert submitted["argument_coercions"] == [
        {"field": "items", "from": "json_string", "to": "array", "bytes": len(items.encode())}
    ]
    for bad in ('["not an object"]', '{"kind": "handle"}', "[1, 2"):
        with pytest.raises(ArgumentCoercionRefused, match="items"):
            coerce_object_arguments("submit_output", {"obligation": "report", "items": bad})


def test_the_model_facing_schema_and_its_digest_are_unchanged() -> None:
    served = served_knowledge_tools()
    for tool in served.values():
        assert isinstance(tool, KnowledgeStructuredTool)
        plain = StructuredTool(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            coroutine=tool.coroutine,
        )
        assert tool_schema_digest(tool) == tool_schema_digest(plain)


# -- D11 and D12: KS refusals reach the model; a refusal is never replayed as success ---------


def _refuse_first_register(h: Lane) -> dict[str, int]:
    """The binding refuses the first registration as KS does for a schema miss (issues);
    returns the count of registrations transmitted to it."""

    original = h.fake.invoke
    state = {"sent": 0}

    async def invoke(envelope: Any, credential: str) -> Any:
        if envelope.operation == "report.register":
            state["sent"] += 1
        if envelope.operation == "report.register" and state["sent"] == 1:
            h.fake.authorize(credential, envelope.operation)
            error = h.fake.error(
                "INVALID_ENVELOPE",
                "request outside the K01 schema (dsn postgres://user:secret@db/x)",
            ).model_copy(
                update={
                    "details": {
                        "issues": [
                            "evidence: Required",
                            "findings.0.excludedReason: Expected null, received string",
                        ]
                    }
                }
            )
            raise KnowledgeProtocolRefusal(error)
        return await original(envelope, credential)

    h.fake.invoke = invoke  # type: ignore[method-assign]
    return state


async def test_a_ks_refusal_passes_its_code_message_and_field_paths() -> None:
    h = lane()
    _refuse_first_register(h)
    (refused,) = await _calls(h, ("report_register", {"report": model_report("r-11")}, "c-1"))
    assert refused["ok"] is False and refused["result"]["journal_state"] == "rejected"
    refusal = refused["refusal"]
    assert refusal["code"] == "INVALID_ENVELOPE"
    assert refusal["message"].startswith("request outside the K01 schema")
    assert "secret" not in json.dumps(refusal)  # credential-shaped text is redacted
    assert refusal["field_paths"] == ["evidence", "findings.0.excludedReason"]
    assert refusal["issues"][0] == "evidence: Required"


async def test_a_refused_registration_replays_as_the_same_refusal_and_a_fix_registers() -> None:
    h = lane()
    sent = _refuse_first_register(h)
    bad = model_report("r-12")
    fixed = model_report("r-12-fixed")
    first, retry, corrected, again = await _calls(
        h,
        ("report_register", {"report": bad}, "c-1"),
        ("report_register", {"report": bad}, "c-2"),  # identical retry, same attempt
        ("report_register", {"report": fixed}, "c-3"),
        ("report_register", {"report": fixed}, "c-4"),  # identical retry of the success
    )
    assert first["ok"] is False
    # D12: the stored rejection is the same refusal, never ok:true without a handle.
    assert retry["ok"] is False and retry["refusal"]["code"] == "INVALID_ENVELOPE"
    assert retry["refusal"]["replayed"] is True
    assert retry["result"]["effect_key"] == first["result"]["effect_key"]
    # The corrected payload is a new effect and registers.
    assert corrected["ok"] and corrected["result"]["journal_state"] == "applied"
    assert corrected["result"]["effect_key"] != first["result"]["effect_key"]
    assert corrected["result"]["affected"]
    # An identical retry of the success is idempotent: same key and outcome, nothing resent.
    assert again["ok"] and again["result"]["effect_key"] == corrected["result"]["effect_key"]
    assert again["result"]["receipt_ref"] == corrected["result"]["receipt_ref"]
    assert sent["sent"] == 2  # the refused first call and the corrected call; no replay resent


async def test_an_identical_successful_registration_replays_with_the_same_handles() -> None:
    """Review S1: the replay of a settled success carries the original's affected handles and
    receipt digest (read back from the binding, nothing re-sent), also from a fresh attempt,
    and `submit_output` accepts those handles."""

    h = lane()
    report = model_report("r-s1")
    first, again = await _calls(
        h,
        ("report_register", {"report": report}, "c-1"),
        ("report_register", {"report": report}, "c-2"),
    )
    assert first["ok"] and again["ok"]
    assert again["result"]["affected"] == first["result"]["affected"] != []
    assert again["result"]["receipt_digest"] == first["result"]["receipt_digest"] is not None
    assert again["result"]["effect_key"] == first["result"]["effect_key"]
    registers = [
        call
        for call in h.fake.calls_of("invoke")
        if call.envelope is not None and call.envelope.operation == "report.register"
    ]
    assert len(registers) == 1  # the replay read the receipt; it never re-sent the effect
    handle = next(i for i in again["result"]["affected"] if "/report/" in i["handle"])
    (submitted,) = await _calls(
        h,
        (
            "submit_output",
            {
                "obligation": "report",
                "items": [{"kind": "handle", "ref": handle["handle"], "digest": handle["digest"]}],
            },
            "c-3",
        ),
    )
    assert submitted["ok"], submitted
    # One producer per subject (0051): the replay recorded no second producer.
    assert h.toolset.lineage is not None
    facts = await h.toolset.lineage.facts(h.toolset.access(h.live()).scope, handle["handle"])
    assert [fact.role.value for fact in facts].count("producer") == 1

    # A fresh attempt of the same operation replays the same handles too.
    token = CURRENT_INVOCATION.set(h.live(attempt=2))
    try:
        fresh = await h.call("report_register", {"report": report}, "c-4")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert fresh["ok"] and fresh["result"]["affected"] == first["result"]["affected"]


async def _replay_after(h: Lane, report: dict[str, Any]) -> dict[str, Any]:
    first, again = await _calls(
        h,
        ("report_register", {"report": report}, "c-1"),
        ("report_register", {"report": report}, "c-2"),
    )
    assert first["ok"], first
    return again


@pytest.mark.parametrize(
    ("setup", "code", "retryable"),
    [
        ("lookup_refused", "RECEIPT_UNAVAILABLE", False),
        ("lookup_unreachable", "RECEIPT_UNAVAILABLE", True),
        ("transport_raised", "RECEIPT_UNAVAILABLE", True),
        ("not_found", "RECEIPT_UNAVAILABLE", False),
        ("unresolved", "RECEIPT_UNAVAILABLE", True),
        ("digest_mismatch", "RECEIPT_DIGEST_MISMATCH", False),
        ("digest_missing", "RECEIPT_DIGEST_MISSING", False),
    ],
)
async def test_a_replayed_success_whose_receipt_cannot_be_proven_is_a_typed_refusal(
    monkeypatch: pytest.MonkeyPatch, setup: str, code: str, retryable: bool
) -> None:
    """Review S1-residual: never `ok: true` with empty handles on a replay."""

    from dataclasses import replace as replace_record

    from mission_control.application.knowledge.operations import KnowledgeRefused
    from mission_control.application.ports.knowledge import KnowledgeTransportError
    from mission_control.contracts.knowledge_protocol_results import (
        ReceiptFound,
        ReceiptNotFound,
        ReceiptUnresolved,
    )

    h = lane()
    gateway = h.toolset.gateway
    original_receipt = gateway.receipt
    journal_lookup = h.journal.lookup

    async def receipt(effect_key: str, access: Any) -> Any:
        found = await original_receipt(effect_key, access)
        if setup == "lookup_refused":
            raise KnowledgeRefused("SCOPE_DENIED", "recovery scope differs", effect_key=effect_key)
        if setup == "lookup_unreachable":
            return None
        if setup == "transport_raised":
            raise KnowledgeTransportError("connection reset")
        if setup == "not_found":
            return ReceiptNotFound(disposition="not_found", checkedAt="2026-10-28T00:00:00Z")
        if setup == "unresolved":
            return ReceiptUnresolved(
                disposition="unresolved", error=h.fake.error("UNRESOLVED_EFFECT", "unknown")
            )
        if setup == "digest_mismatch":
            assert isinstance(found, ReceiptFound)
            forged = found.receipt.model_copy(update={"digest": "sha256:" + "f" * 64})
            return ReceiptFound(disposition="found", receipt=forged)
        return found

    async def lookup(scope: str, effect_key: str) -> Any:
        record = await journal_lookup(scope, effect_key)
        if setup == "digest_missing" and record is not None and record.state.value == "applied":
            return replace_record(record, receipt_digest=None)
        return record

    monkeypatch.setattr(gateway, "receipt", receipt)
    monkeypatch.setattr(h.journal, "lookup", lookup)
    again = await _replay_after(h, model_report(f"r-{setup}"))
    assert again["ok"] is False, again
    assert again["refusal"]["code"] == code
    assert again["refusal"]["retryable"] is retryable
    assert again["refusal"]["replayed"] is True
    assert again["result"]["effect_key"].startswith("ek1:")


def test_redaction_covers_credentials_keys_and_local_paths() -> None:
    """Review N4."""

    from mission_control.application.knowledge.toolset import _redacted

    for secret in (
        "redis://user:p4ss@cache:6379/0",
        "sb_secret_abcdEFGH1234",
        "sb_publishable_abcdEFGH1234",
        "AKIAABCDEFGHIJKLMNOP",
        "password=hunter2",
        'api_key: "xyz123abc"',
        r"C:\Users\someone\project\.env",
        "/home/someone/.ssh/id_ed25519",
    ):
        assert secret not in _redacted(f"before {secret} after", 500), secret
    kept = "task.limits.tokens: Expected number, received string"
    assert _redacted(kept, 500) == kept


def test_the_refusal_view_is_bounded() -> None:
    from mission_control.contracts.knowledge_protocol_results import protocol_error

    error = protocol_error(
        "INVALID_ENVELOPE", "m" * 2000, occurred_at="2026-10-28T00:00:00Z"
    ).model_copy(update={"details": {"issues": [f"p{i}: " + "x" * 900 for i in range(40)]}})
    view = refusal_view("INVALID_ENVELOPE", error)
    assert len(view["message"]) == 500
    assert len(view["issues"]) == 10 and all(len(item) <= 300 for item in view["issues"])
    assert refusal_view("INVALID_ENVELOPE", None) == {"code": "INVALID_ENVELOPE", "message": None}


# -- D13: the undeclared promise key names the valid keys ---------------------------------------


async def test_an_undeclared_promise_key_lists_this_invocations_valid_keys() -> None:
    h = lane()
    contracts = InMemoryOutputContractStore()
    submissions = SubmissionService(contracts.submissions, contracts=contracts, clock=h.clock)
    toolset = replace(h.toolset, submissions=submissions)
    live = replace(h.live(), position="stage/draft")
    access = toolset.access(live)
    await OutputFulfillmentService(contracts, submissions).register_promises(
        host_access(access.scope),
        RUN,
        promises(
            obligation("stage.report", OutputForm.REFERENCE, position="stage/draft"),
            obligation("stage.summary", OutputForm.TEXT, position="stage/draft"),
            obligation("other.note", OutputForm.TEXT, position="other"),
        ),
    )
    live = await toolset.begin(live)
    item = {
        "kind": "handle",
        "ref": f"kh:{BINDING}/report/report-7@research-report.v2",
        "digest": "sha256:" + "a" * 64,
    }
    refused = await toolset.dispatch(
        "submit_output", {"obligation": "report", "items": [item]}, live, tool_call_id="c-1"
    )
    refusal = refused["refusal"]
    assert refusal["code"] == "OBLIGATION_UNDECLARED"
    # Only this position's pinned promises, in their full key form.
    assert refusal["valid_obligations"] == ["stage.report", "stage.summary"]
    assert "stage.report, stage.summary" in refusal["message"]
    # The key semantics are unchanged: the bare name still does not submit.
    accepted = await toolset.dispatch(
        "submit_output", {"obligation": "stage.report", "items": [item]}, live, tool_call_id="c-2"
    )
    assert accepted["ok"], accepted


def test_the_submit_output_description_states_the_key_form() -> None:
    description = TOOL_DESCRIPTIONS["submit_output"]
    assert "<owner position>.<promise name>" in description and "root.report" in description
