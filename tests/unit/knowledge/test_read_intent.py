"""``knowledge.read_intent`` through the gateway and the toolset (OVE-204 slice 4).

The gateway sends the inline request under a non-effect credential granting exactly
``knowledge.read_intent``, checks the synchronous answer and records one
``retained_read_observation`` per result operation before returning it; the toolset projects
it as ``knowledge_read_intent`` and refuses it to an independent evaluator.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from mission_control.adapters.deep_agents.knowledge_tools import (
    CURRENT_INVOCATION,
    knowledge_capability_id,
    knowledge_tool_components,
)
from mission_control.application.knowledge.operations import KnowledgeRefused
from mission_control.application.knowledge.read_intent import (
    observation_id,
    read_handle,
    read_intent_request_key,
    read_observations,
)
from mission_control.application.knowledge.toolset import (
    NATIVE_CONTRACTS,
    TOOL_NAMES,
    TOOL_OPERATIONS,
    ReadScope,
)
from mission_control.contracts.knowledge_protocol import (
    EVALUATOR_OPERATIONS,
    RESULT_OPERATIONS,
    Governors,
    KnowledgeReadIntentRequest,
    KnowledgeReadIntentResult,
    Ref,
    canonical_json,
    digest_canonical,
)
from tests.fixtures.knowledge_binding import (
    BINDING,
    InMemoryRetainedReadStore,
    read_intent_answer,
)
from tests.unit.knowledge.test_gateway import TENANT, TRANSPORTS, harness
from tests.unit.knowledge.test_knowledge_tools import RUN, lane

GOVERNORS = Governors.model_validate(
    {
        "deadline": "2026-10-31T12:00:00Z",
        "maxItems": 64,
        "partialResults": "forbid",
        "budget": {"calls": 0, "tokens": 0, "costUsd": "0"},
    }
)


def request(**updates: Any) -> KnowledgeReadIntentRequest:
    document: dict[str, Any] = {
        "schemaVersion": "knowledge-read-intent-request.v1",
        "purpose": "discovery",
        "operations": [
            {"opId": "head", "kind": "named_query", "query": "knowledge.head", "params": {}},
            {
                "opId": "find",
                "kind": "named_query",
                "query": "entity.resolve",
                "params": {"text": "LangGraph"},
                "limit": 5,
            },
            {"opId": "where", "kind": "schema_search", "query": "entity", "limit": 3},
            {"opId": "page", "kind": "schema_get", "id": "rel:knowledge.entity"},
        ],
    }
    document.update(updates)
    return KnowledgeReadIntentRequest.model_validate(document)


async def read(
    h: Any, store: InMemoryRetainedReadStore, key: str = "read-intent-1", **kw: Any
) -> KnowledgeReadIntentResult:
    return await h.gateway.read_intent(
        kw.pop("req", None) or request(),
        h.access(),
        observations=store,
        capability_pin="knowledge.knowledge_read_intent@1",
        governors=GOVERNORS,
        request_key=key,
    )


# ---------------------------------------------------------------- protocol and mapping


def test_read_intent_is_a_result_operation_never_an_evaluator_operation() -> None:
    assert "knowledge.read_intent" in RESULT_OPERATIONS
    assert "knowledge.read_intent" not in EVALUATOR_OPERATIONS
    assert TOOL_OPERATIONS["knowledge_read_intent"] == "knowledge.read_intent"
    assert NATIVE_CONTRACTS["knowledge_read_intent"] == {
        "name": "knowledge-read-intent",
        "version": "v1",
    }
    assert knowledge_capability_id("knowledge_read_intent") == "tool.knowledge-read-intent"


def test_the_request_refuses_duplicates_unlisted_queries_and_extra_fields() -> None:
    base = request().model_dump(mode="json")
    duplicate = base | {"operations": [base["operations"][0], base["operations"][0]]}
    unlisted = base | {
        "operations": [{"opId": "x", "kind": "named_query", "query": "sql.raw", "params": {}}]
    }
    with pytest.raises(ValueError, match="duplicate opId"):
        KnowledgeReadIntentRequest.model_validate(duplicate)
    with pytest.raises(ValueError):
        KnowledgeReadIntentRequest.model_validate(unlisted)
    with pytest.raises(ValueError):
        KnowledgeReadIntentRequest.model_validate(base | {"tenant": TENANT})
    with pytest.raises(ValueError):
        KnowledgeReadIntentRequest.model_validate(base | {"operations": []})


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_a_read_is_sent_under_a_read_only_credential_and_every_op_is_recorded(
    transport: str,
) -> None:
    h = harness(transport)
    h.client.reader = lambda envelope: read_intent_answer(
        envelope,
        rows={"head": [{"knowledge_seq": 12}], "where": []},
        errors={"page": "PAGE_NOT_FOUND"},
    )
    store = InMemoryRetainedReadStore()

    result = await read(h, store)

    (call,) = h.client.calls_of("invoke")
    assert call.claims.operations == ["knowledge.read_intent"]
    assert call.claims.effect is None
    envelope = call.envelope
    assert envelope is not None
    assert envelope.operation == "knowledge.read_intent" and envelope.effect is None
    assert envelope.use is None and envelope.requestId == "read-intent-1"
    assert envelope.input is not None
    assert envelope.input.nativeContract.model_dump() == {
        "name": "knowledge-read-intent",
        "version": "v1",
    }
    assert envelope.input.inlinePayload == request().payload()
    assert [op.status for op in result.operations] == ["ok", "ok", "empty", "error"]

    access = h.access()
    rows = await store.observations(access.scope, access.invocation_ref)
    assert [row.read_observation_ref for row in rows] == [
        f"{result.operationId}#{op}" for op in ("head", "find", "where", "page")
    ]
    head, find, where, page = rows
    assert head.run_id == access.origin.run_id and head.source_binding_id is None
    assert head.handle == read_handle(BINDING, request().operations[0])
    assert head.handle.startswith(f"kri:{BINDING}/knowledge.head?sha256:")
    assert where.handle.startswith(f"kri:{BINDING}/schema_search?sha256:")
    assert page.handle.startswith(f"kri:{BINDING}/schema_get?sha256:")
    assert (head.readable, where.readable, page.readable) == (True, True, False)
    assert head.observed_digest == digest_canonical([{"knowledge_seq": 12}])
    assert head.expected_digest is None and not head.digest_verified
    assert head.byte_count == len(canonical_json([{"knowledge_seq": 12}]).encode())
    assert page.byte_count is None and page.consistency["errorCode"] == "PAGE_NOT_FOUND"
    assert head.observed_at == datetime(2026, 10, 31, 10, tzinfo=UTC)
    assert head.observation_id == observation_id(access.invocation_ref, head.read_observation_ref)
    assert find.consistency == {
        "ksOperationId": result.operationId,
        "snapshotId": result.snapshotId,
        "snapshotDigest": result.snapshotDigest,
        "knowledgeSeq": 12,
        "atKnowledgeSeq": 12,
        "migrationHead": "20261031000000",
        "catalogVersion": "1.0.0",
        "query": "entity.resolve",
        "kind": "named_query",
        "status": "ok",
        "rowCount": 1,
        "truncated": False,
        "bodyWithheld": False,
        "purpose": "discovery",
        "binding": BINDING,
    }
    assert set(store.actors) == {"mission-control:knowledge-gateway"}


async def test_a_replayed_request_is_the_same_operation_and_the_same_rows() -> None:
    h = harness()
    h.client.reader = read_intent_answer
    store = InMemoryRetainedReadStore()
    first = await read(h, store)
    again = await read(h, store)
    other = await read(h, store, key="read-intent-2")
    assert first.operationId == again.operationId != other.operationId
    assert len(store.rows) == 8  # four per distinct KS operation; the replay wrote none


async def test_withheld_bodies_keep_their_digest_and_persist_names_the_retained_document() -> None:
    h = harness()
    retained = Ref(
        kind="artifact",
        id="kri-result-1",
        version="knowledge-read-intent-result.v1",
        digest="sha256:" + "b" * 64,
        tenant=TENANT,
        binding=BINDING,
    )
    h.client.reader = lambda envelope: read_intent_answer(
        envelope, withheld=frozenset({"find"}), retained=retained
    )
    store = InMemoryRetainedReadStore()
    result = await read(h, store, req=request(persist=True))
    access = h.access()
    rows = {row.read_observation_ref.split("#")[1]: row for row in store.rows.values()}
    assert result.operations[1].bodyWithheld and result.operations[1].rows is None
    assert rows["find"].readable and rows["find"].byte_count is None
    assert rows["find"].observed_digest == result.operations[1].contentDigest
    assert {row.retained_ref for row in rows.values()} == {
        f"kh:{BINDING}/artifact/kri-result-1@knowledge-read-intent-result.v1"
    }
    assert rows["head"].consistency["retainedDigest"] == retained.digest
    assert all(row.invocation_ref == access.invocation_ref for row in rows.values())


async def test_an_unserved_read_is_the_bindings_refusal_and_nothing_is_recorded() -> None:
    h = harness()
    store = InMemoryRetainedReadStore()
    with pytest.raises(KnowledgeRefused) as refused:
        await read(h, store)
    assert refused.value.code == "SCHEMA_UNSUPPORTED"
    assert store.rows == {}


async def test_an_inconsistent_answer_is_refused_and_not_recorded() -> None:
    h = harness()

    def tampered(envelope: Any) -> KnowledgeReadIntentResult:
        answer = read_intent_answer(envelope)
        document = answer.model_dump(mode="json")
        document["operations"][0]["rows"] = [{"op": "forged"}]
        return KnowledgeReadIntentResult.model_validate(document)

    h.client.reader = tampered
    store = InMemoryRetainedReadStore()
    with pytest.raises(KnowledgeRefused) as refused:
        await read(h, store)
    assert refused.value.code == "INVALID_ENVELOPE"
    assert store.rows == {}


async def test_a_read_that_cannot_be_recorded_is_refused_as_retryable() -> None:
    h = harness()
    h.client.reader = read_intent_answer
    store = InMemoryRetainedReadStore()
    store.fail = RuntimeError("database down")
    with pytest.raises(KnowledgeRefused) as refused:
        await read(h, store)
    assert refused.value.code == "CAPABILITY_UNAVAILABLE"
    store.fail = None
    result = await read(h, store)  # the same request: KS answers the same operation
    assert {row.read_observation_ref.split("#")[0] for row in store.rows.values()} == {
        result.operationId
    }


def test_observations_refuse_an_answer_for_an_op_never_asked() -> None:
    answer = read_intent_answer(
        _envelope_for(request(operations=[{"opId": "x", "kind": "schema_search", "query": "e"}]))
    )
    with pytest.raises(ValueError, match="not asked"):
        read_observations(
            request(), answer, binding=BINDING, run_id=RUN, invocation_ref="mc-inv:sha256:x"
        )


def _envelope_for(req: KnowledgeReadIntentRequest) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        input=SimpleNamespace(inlinePayload=req.payload()),
        tenant=TENANT,
        operation="knowledge.read_intent",
        requestId="r-1",
    )


# ---------------------------------------------------------------- the toolset projection

ARGS = {
    "purpose": "discovery",
    "operations": [
        {"opId": "find", "kind": "named_query", "query": "entity.resolve", "params": {"text": "x"}},
        {"opId": "where", "kind": "schema_search", "query": "entity"},
    ],
}


def test_the_tool_is_projected_with_a_pinned_component() -> None:
    h = lane()
    assert "knowledge_read_intent" in TOOL_NAMES and "knowledge_read_intent" in h.support.tools
    (component,) = [
        item
        for item in knowledge_tool_components(h.support.tools)
        if item.tool_name == "knowledge_read_intent"
    ]
    assert component.ref.logical_id == "knowledge-tool.knowledge-read-intent"
    assert component.ref.revision == 1


async def test_the_tool_reads_records_and_replays_under_the_same_call_id() -> None:
    h = lane()
    h.fake.reader = read_intent_answer
    store = InMemoryRetainedReadStore()
    h.toolset.retained_reads = store
    token = CURRENT_INVOCATION.set(h.live())
    try:
        first = await h.call("knowledge_read_intent", ARGS, "c-1")
        replay = await h.call("knowledge_read_intent", ARGS, "c-1")
        # W1 D17: the operations list sent as one JSON string is parsed once.
        coerced = await h.call(
            "knowledge_read_intent", ARGS | {"operations": json.dumps(ARGS["operations"])}, "c-2"
        )
    finally:
        CURRENT_INVOCATION.reset(token)
    assert first["ok"] and first["refusal"] is None
    assert first["result"]["schemaVersion"] == "knowledge-read-intent-result.v1"
    assert replay["result"]["operationId"] == first["result"]["operationId"]
    assert coerced["ok"] and coerced["argument_coercions"][0]["field"] == "operations"
    access = h.toolset.access(h.live())
    expected = read_intent_request_key(
        access.invocation_ref,
        "c-1",
        digest_canonical(
            KnowledgeReadIntentRequest.model_validate(
                {"schemaVersion": "knowledge-read-intent-request.v1", **ARGS}
            ).payload()
        ),
    )
    sent = h.fake.calls_of("invoke")[0].envelope
    assert sent is not None and sent.requestId == expected
    assert len(store.rows) == 4  # two reads x two operations; the replay wrote none
    assert {row.run_id for row in store.rows.values()} == {RUN}


@pytest.mark.parametrize(
    "bound",
    [
        {"evaluator": True},
        {"read_scope": ReadScope(purpose="evaluation_subject", isolated=True, reports={})},
    ],
)
async def test_an_independent_evaluator_is_refused_before_any_call(bound: dict[str, Any]) -> None:
    h = lane()
    h.fake.reader = read_intent_answer
    h.toolset.retained_reads = InMemoryRetainedReadStore()
    token = CURRENT_INVOCATION.set(replace(h.live(), **bound))
    try:
        out = await h.call("knowledge_read_intent", ARGS, "c-1")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert out["ok"] is False and out["refusal"]["code"] == "SCOPE_DENIED"
    assert h.fake.calls_of("invoke") == []


async def test_without_a_retained_read_store_the_tool_is_refused() -> None:
    h = lane()
    h.fake.reader = read_intent_answer
    token = CURRENT_INVOCATION.set(h.live())
    try:
        out = await h.call("knowledge_read_intent", ARGS, "c-1")
    finally:
        CURRENT_INVOCATION.reset(token)
    assert out["refusal"]["code"] == "CAPABILITY_UNAVAILABLE"
    assert h.fake.calls_of("invoke") == []


async def test_invalid_reads_are_repairable_refusals() -> None:
    h = lane()
    h.toolset.retained_reads = InMemoryRetainedReadStore()
    token = CURRENT_INVOCATION.set(h.live())
    try:
        duplicate = await h.toolset.dispatch(
            "knowledge_read_intent",
            ARGS | {"operations": [ARGS["operations"][0], ARGS["operations"][0]]},
            h.live(),
            tool_call_id="c-1",
        )
        unlisted = await h.toolset.dispatch(
            "knowledge_read_intent",
            ARGS | {"operations": [{"opId": "x", "kind": "named_query", "query": "sql.raw"}]},
            h.live(),
            tool_call_id="c-2",
        )
    finally:
        CURRENT_INVOCATION.reset(token)
    for out in (duplicate, unlisted):
        assert out["ok"] is False and out["refusal"]["code"] == "INVALID_ENVELOPE"
    assert h.fake.calls_of("invoke") == []
