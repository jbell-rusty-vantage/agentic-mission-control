"""``knowledge.read_intent`` observations (OVE-204 slice 4): every served read is recorded.

Knowledge Services records the read as one ``knowledge_verification.operation`` row; Mission
Control records what the invocation read as one ``retained_read_observation`` per result
operation (:func:`read_observations`). The mapping:

* ``observation_id``: UUIDv5 of ``<invocation_ref>/<read_observation_ref>``, so a replayed
  read (same request id, same KS operation id) is the same row;
* ``source_binding_id``: None (a discovery read names no bound source in this slice);
* ``handle``: ``kri:<binding>/<named query | schema_search | schema_get>?<digest>`` where the
  digest is ``digest_canonical`` of the request operation without its ``opId``;
* ``read_observation_ref``: ``<KS operationId>#<opId>``;
* ``retained_ref``: the custody handle of the frozen result document when ``persist``;
* ``expected_digest`` None, ``observed_digest`` the operation's ``contentDigest``;
* ``readable``: the status is ``ok``, ``empty`` or ``truncated``;
* ``byte_count``: UTF-8 length of the canonical body returned inline (None when withheld or
  absent);
* ``consistency``: the snapshot, head, contract and per-operation facts of the read;
* ``observed_at``: the KS knowledge head's ``updatedAt``.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Any, Final
from uuid import NAMESPACE_URL, uuid5

from mission_control.contracts.knowledge_protocol import (
    READ_INTENT_READABLE,
    KnowledgeReadIntentRequest,
    KnowledgeReadIntentResult,
    ReadIntentNamedQueryOperation,
    ReadIntentOperationResult,
    canonical_json,
    digest_canonical,
)
from mission_control.domain.knowledge.reads import (
    READ_INTENT_HANDLE_PREFIX,
    RetainedReadObservation,
)

_NAMESPACE: Final = uuid5(NAMESPACE_URL, "mission-control:retained-read-observation")


def observation_id(invocation_ref: str, read_observation_ref: str) -> str:
    return str(uuid5(_NAMESPACE, f"{invocation_ref}/{read_observation_ref}"))


def read_intent_request_key(invocation_ref: str, tool_call_id: str, payload_digest: str) -> str:
    """The K01 request id of one ``knowledge_read_intent`` tool call: a replayed tool call (same
    invocation, call id and payload) is the same KS request, so KS answers the same operation."""

    material = f"{invocation_ref}\n{tool_call_id}\n{payload_digest}".encode()
    return "read-intent-" + sha256(material).hexdigest()[:48]


def read_handle(binding: str, operation: Any) -> str:
    """``kri:<binding>/<query or kind>?<digest of the request operation without its opId>``."""

    document = operation.model_dump(mode="json")
    document.pop("opId", None)
    named = isinstance(operation, ReadIntentNamedQueryOperation)
    name = operation.query if named else operation.kind
    return f"{READ_INTENT_HANDLE_PREFIX}{binding}/{name}?{digest_canonical(document)}"


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _byte_count(operation: ReadIntentOperationResult) -> int | None:
    if operation.bodyWithheld or (operation.rows is None and operation.value is None):
        return None
    return len(canonical_json(operation.body).encode("utf-8"))


def read_observations(
    request: KnowledgeReadIntentRequest,
    result: KnowledgeReadIntentResult,
    *,
    binding: str,
    run_id: str,
    invocation_ref: str,
) -> tuple[RetainedReadObservation, ...]:
    """One observation per result operation (see the module docstring for the mapping)."""

    requested = {operation.opId: operation for operation in request.operations}
    retained = result.retainedRef
    retained_ref = (
        None
        if retained is None
        else f"kh:{retained.binding}/{retained.kind}/{retained.id}@{retained.version}"
    )
    observed_at = _instant(result.knowledgeHead.updatedAt)
    rows = []
    for operation in result.operations:
        source = requested.get(operation.opId)
        if source is None:
            raise ValueError(f"the read answered an operation it was not asked: {operation.opId}")
        reference = f"{result.operationId}#{operation.opId}"
        consistency: dict[str, Any] = {
            "ksOperationId": result.operationId,
            "snapshotId": result.snapshotId,
            "snapshotDigest": result.snapshotDigest,
            "knowledgeSeq": result.knowledgeHead.knowledgeSeq,
            "atKnowledgeSeq": result.atKnowledgeSeq,
            "migrationHead": result.contract.migrationHead,
            "catalogVersion": result.contract.catalogVersion,
            "query": operation.query,
            "kind": operation.kind,
            "status": operation.status,
            "rowCount": operation.rowCount,
            "truncated": operation.truncated,
            "bodyWithheld": operation.bodyWithheld,
            "purpose": request.purpose,
            "binding": binding,
        }
        if retained is not None:
            consistency["retainedDigest"] = retained.digest
        if operation.error is not None:
            consistency["errorCode"] = operation.error.code
        rows.append(
            RetainedReadObservation(
                observation_id=observation_id(invocation_ref, reference),
                run_id=run_id,
                invocation_ref=invocation_ref,
                handle=read_handle(binding, source),
                read_observation_ref=reference,
                readable=operation.status in READ_INTENT_READABLE,
                observed_at=observed_at,
                retained_ref=retained_ref,
                observed_digest=operation.contentDigest,
                byte_count=_byte_count(operation),
                consistency=consistency,
            )
        )
    return tuple(rows)


__all__ = ["observation_id", "read_handle", "read_intent_request_key", "read_observations"]
