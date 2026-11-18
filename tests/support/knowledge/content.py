"""Knowledge content builders: report packages, registrations, model reports, describe documents.

Pure value constructors the KS fake serves and the output and transfer tests build from, so a
test that needs only content never loads the fake.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mission_control.contracts.knowledge_protocol import (
    PROTOCOL_VERSION,
    KnowledgeReadIntentRequest,
    KnowledgeReadIntentResult,
    MembersSelection,
    OperationEnvelope,
    Ref,
    RevisionSelection,
    SelectedReportRead,
    digest_bytes,
    digest_canonical,
    read_intent_snapshot_digest,
)
from tests.support.knowledge.credentials import BINDING


@dataclass
class StoredPackage:
    """One exact report revision the fake serves: its body, ledger and member records."""

    report: Ref
    kind: Ref
    body: bytes
    ledger: bytes
    assertions: tuple[dict[str, Any], ...]
    evidence: tuple[dict[str, Any], ...] = ()
    # The bytes the binding actually serves (a truncated or corrupt custody copy), when they
    # differ from what the package manifest declares.
    served_body: bytes | None = None

    def member_handles(self, kind: str) -> tuple[tuple[Ref, dict[str, Any]], ...]:
        records = self.assertions if kind == "assertion" else self.evidence
        version = (
            "research-core.assertion.v2" if kind == "assertion" else "research-core.fragment.v2"
        )
        return tuple(
            (
                Ref(
                    kind=kind,  # type: ignore[arg-type]
                    id=record["id"],
                    version=version,
                    digest=digest_canonical(record),
                    tenant=self.report.tenant,
                    binding=self.report.binding,
                ),
                record,
            )
            for record in records
        )

    def artifact(self, suffix: str, content: bytes) -> dict[str, str]:
        return {
            "kind": "artifact",
            "id": f"{self.report.id}.{suffix}",
            "version": "research-core.artifact.v1",
            "digest": digest_bytes(content),
            "tenant": self.report.tenant,
            "binding": self.report.binding,
        }

    def answer(self, read: SelectedReportRead) -> dict[str, Any]:
        """``research-report-package.v2`` for exactly this read (KS readSelected semantics)."""

        whole = isinstance(read.selection, RevisionSelection)
        assertions = self.member_handles("assertion")
        evidence = self.member_handles("fragment")
        if not whole:
            assert isinstance(read.selection, MembersSelection)
            wanted_a = {h.id: h for h in read.selection.assertions}
            wanted_e = {h.id: h for h in read.selection.evidence}
            assertions = tuple(item for item in assertions if item[0].id in wanted_a)
            evidence = tuple(item for item in evidence if item[0].id in wanted_e)
        return {
            "schema": "research-report-package.v2",
            "report": self.report.model_dump(mode="json"),
            "revision": self.report.id,
            "kind": self.kind.model_dump(mode="json"),
            "purpose": read.purpose,
            "request": read.digest(),
            "selection": read.selection.model_dump(mode="json"),
            "body": {
                "path": "body.md",
                "digest": digest_bytes(self.body),
                "bytes": len(self.body),
                "artifact": self.artifact("body", self.body),
            }
            if whole
            else None,
            "ledger": {
                "path": "ledger.json",
                "digest": digest_bytes(self.ledger),
                "bytes": len(self.ledger),
                "artifact": self.artifact("ledger", self.ledger),
            }
            if whole
            else None,
            "assertions": [
                {"handle": h.model_dump(mode="json"), "record": r} for h, r in assertions
            ],
            "evidence": [{"handle": h.model_dump(mode="json"), "record": r} for h, r in evidence],
        }

    @property
    def result_ref(self) -> Ref:
        """The package of a whole-revision read under the dependent-input purpose."""

        read = SelectedReportRead(
            report=self.report, exact=True, purpose="dependent_input", selection=RevisionSelection()
        )
        return package_ref(self.report, self.answer(read))


def package_ref(report: Ref, manifest: dict[str, Any]) -> Ref:
    digest = digest_canonical(manifest)
    return Ref(
        kind="artifact",
        id=f"{report.id}.package.{digest[7:19]}",
        version="research-report-package.v2",
        digest=digest,
        tenant=report.tenant,
        binding=report.binding,
    )


def report_package(
    report_id: str,
    version: str,
    *,
    tenant: str,
    binding: str = BINDING,
    body: bytes = b"# Findings\n\nThe exact body.\n",
    ledger: bytes = b'{"assertions":["a-1"]}',
    assertions: tuple[str, ...] = ("a-1",),
    evidence: tuple[str, ...] = (),
) -> StoredPackage:
    report = Ref(
        kind="report",
        id=report_id,
        version="research-report.v2",
        digest=digest_canonical({"id": report_id, "version": version, "body": digest_bytes(body)}),
        tenant=tenant,
        binding=binding,
    )
    kind = Ref(
        kind="report_kind",
        id="evidence_report",
        version="research-report-kind.v1",
        digest=digest_canonical({"kind": "evidence_report"}),
        tenant=tenant,
        binding=binding,
    )

    def record(schema: str, item_id: str, text: str) -> dict[str, Any]:
        return {
            "schemaVersion": schema,
            "id": item_id,
            "tenant": tenant,
            "binding": binding,
            "proposition" if "assertion" in schema else "text": text,
        }

    return StoredPackage(
        report=report,
        kind=kind,
        body=body,
        ledger=ledger,
        assertions=tuple(
            record("research-core.assertion.v2", item, f"claim {item}") for item in assertions
        ),
        evidence=tuple(
            record("research-core.fragment.v2", item, f"fragment {item}") for item in evidence
        ),
    )


def describe_document(
    binding: str, application: str, auditor_kind: str = "independent", *, read_intent: bool = True
) -> dict[str, Any]:
    document = {
        "protocolVersions": [PROTOCOL_VERSION],
        "binding": binding,
        "application": application,
        "coreSchemas": ["research-report.v2"],
        "operations": [
            "knowledge.describe",
            "knowledge.read",
            "knowledge.apply",
            "report.register",
            "report.assess",
            "report.derive",
            "verify.claims",
            "operation.get",
            "operation.cancel",
            "receipt.get",
        ],
        "auditorKind": auditor_kind,
        "reportKinds": ["evidence_report", "study_appraisal"],
        "media": ["text.markdown"],
        "guarantees": {
            "exactRead": "exact_revision",
            "receiptLookup": "by_effect_key",
            "nativeCancellation": "native",
            "admission": "exact_use_decision",
            "revocation": "epoch_checked",
            "writeAtomicity": "single_transaction",
        },
        "signingIssuer": "knowledge-services",  # the binding's seal signer, not MC's issuer
        "pinnedSchema": {
            "name": "knowledge-verification-2.5.0",
            "version": "knowledge-verification.v2",
            "digest": "sha256:" + "1" * 64,
        },
        "qualification": [],
        "describedAt": "2026-10-25T00:00:00Z",
    }
    if read_intent:
        # OVE-204 slice 4: a binding with the host-injected read intent port serves it.
        document["operations"].insert(3, "knowledge.read_intent")  # type: ignore[attr-defined]
    return document


def read_intent_answer(
    envelope: OperationEnvelope,
    *,
    rows: Mapping[str, list[dict[str, Any]]] | None = None,
    errors: Mapping[str, str] | None = None,
    withheld: frozenset[str] = frozenset(),
    retained: Ref | None = None,
    knowledge_seq: int = 12,
    updated_at: str = "2026-10-31T10:00:00Z",
) -> KnowledgeReadIntentResult:
    """A consistent `knowledge-read-intent-result.v1` for the envelope's inline request: the KS
    operation id is a function of the request id (a replay answers the same id), each operation
    answers ``rows[opId]`` (default: one row naming the op), ``errors[opId]`` fails it, and an op
    in ``withheld`` keeps its digest but returns no body."""

    assert envelope.input is not None
    request = KnowledgeReadIntentRequest.model_validate(envelope.input.inlinePayload)
    operation_id = (
        "op-read_intent-"
        + digest_canonical(
            {
                "tenant": envelope.tenant,
                "operation": envelope.operation,
                "requestId": envelope.requestId,
            }
        )[7:39]
    )
    results = []
    for item in request.operations:
        query = getattr(item, "query", None) or getattr(item, "id", None)
        if errors and item.opId in errors:
            results.append(
                {
                    "opId": item.opId,
                    "kind": item.kind,
                    "query": query,
                    "status": "error",
                    "rowCount": 0,
                    "truncated": False,
                    "contentDigest": digest_canonical(None),
                    "bodyWithheld": False,
                    "error": {"code": errors[item.opId], "message": f"{item.opId} failed"},
                }
            )
            continue
        body = (rows or {}).get(item.opId, [{"op": item.opId, "n": 1}])
        document: dict[str, Any] = {
            "opId": item.opId,
            "kind": item.kind,
            "query": query,
            "status": "ok" if body else "empty",
            "rowCount": len(body),
            "truncated": False,
            "contentDigest": digest_canonical(body),
            "bodyWithheld": item.opId in withheld,
        }
        if item.opId not in withheld:
            document["columns"] = sorted({key for row in body for key in row})
            document["rows"] = body
        results.append(document)
    from mission_control.contracts.knowledge_protocol import ReadIntentOperationResult

    parsed = [ReadIntentOperationResult.model_validate(item) for item in results]
    at = request.atKnowledgeSeq if request.atKnowledgeSeq is not None else knowledge_seq
    return KnowledgeReadIntentResult.model_validate(
        {
            "schemaVersion": "knowledge-read-intent-result.v1",
            "operationId": operation_id,
            "snapshotId": "snap-" + operation_id[-12:],
            "snapshotDigest": read_intent_snapshot_digest(at, parsed),
            "knowledgeHead": {"knowledgeSeq": knowledge_seq, "updatedAt": updated_at},
            "atKnowledgeSeq": at,
            "contract": {"migrationHead": "20261031000000", "catalogVersion": "1.0.0"},
            "operations": results,
            "retainedRef": None if retained is None else retained.model_dump(mode="json"),
        }
    )


RECORD_KINDS = {"fragments": "fragment", "assertions": "assertion", "supportSets": "support_set"}


def fresh_registration(template: Mapping[str, Any], suffix: str) -> dict[str, Any]:
    """A `research-report/v2` registration with every record id made unique by ``suffix``.

    Records refer to each other by K01 `Ref` (id + canonical record digest, research-core
    `recordRef`), so after renaming the task, fragment, assertion and support-set ids each
    dependent `Ref` is recomputed until the document is stable. Artifact refs (content
    digests) and template ids (obligations, sections, premises) are unchanged. An empty
    ``suffix`` reproduces the template byte for byte.
    """

    import copy

    document = copy.deepcopy(dict(template))
    records: dict[tuple[str, str], dict[str, Any]] = {}
    renamed: dict[str, str] = {}
    task = document["task"]
    for key, kind in (("task", "task"), *RECORD_KINDS.items()):
        for record in [task] if key == "task" else document[key]:
            new = f"{record['id']}-{suffix}" if suffix else record["id"]
            renamed[record["id"]] = new
            record["id"] = new
            records[(kind, new)] = record
    document["report"]["reportId"] = (
        f"report-mc-{suffix}" if suffix else document["report"]["reportId"]
    )

    def visit(node: Any) -> bool:
        changed = False
        if isinstance(node, dict):
            if {"kind", "id", "version", "digest", "tenant", "binding"} <= set(node):
                ident = renamed.get(node["id"], node["id"])
                target = records.get((str(node["kind"]), str(ident)))
                if target is not None and target is not node:
                    digest = digest_canonical(target)
                    if node["id"] != ident or node["digest"] != digest:
                        node["id"], node["digest"] = ident, digest
                        changed = True
            for value in node.values():
                changed |= visit(value)
        elif isinstance(node, list):
            for value in node:
                changed |= visit(value)
        return changed

    for _ in range(16):
        if not visit(document):
            return document
    raise AssertionError("registration references did not converge")


def model_content(registration: Mapping[str, Any]) -> dict[str, Any]:
    """W1 D1: the model-shaped content of a complete registration (what a producer submits).

    The host binds the producer and computes every in-registration digest, so assertions lose
    their ``producer``, support sets their ``qualifiersDigest``, text-quote fragments their
    selected digest and size, and every reference to a record of the same registration becomes
    its id; references outside it (artifacts, rubric, policy) stay complete.
    """

    import copy

    document = copy.deepcopy(dict(registration))
    local = {
        (kind, str(record["id"]))
        for key, kind in RECORD_KINDS.items()
        for record in document.get(key, [])
    }
    for assertion in document.get("assertions", []):
        assertion.pop("producer", None)
    for support in document.get("supportSets", []):
        target = support.get("assertion")
        if isinstance(target, dict) and ("assertion", str(target.get("id"))) in local:
            support.pop("qualifiersDigest", None)  # an external assertion keeps its own
    for fragment in document.get("fragments", []):
        if fragment.get("selector", {}).get("kind") == "text_quote":
            fragment.pop("selectedDigest", None)
            fragment.pop("selectedSize", None)

    def visit(node: Any) -> Any:
        if isinstance(node, dict):
            if {"kind", "id", "version", "digest", "tenant", "binding"} <= set(node) and (
                str(node["kind"]),
                str(node["id"]),
            ) in local:
                return str(node["id"])
            return {key: visit(value) for key, value in node.items()}
        if isinstance(node, list):
            return [visit(value) for value in node]
        return node

    return {key: visit(value) for key, value in document.items()}


def _artifact(name: str, kind: str = "artifact") -> dict[str, str]:
    return {
        "kind": kind,
        "id": name,
        "version": "artifact.v1",
        "digest": digest_bytes(name.encode("utf-8")),
    }


def model_report(
    report_id: str,
    revision: int = 1,
    *,
    use: str | None = None,
    audience: str | None = None,
    quote: str = "Mistral 7B is a 7-billion-parameter language model.",
) -> dict[str, Any]:
    """A minimal model-shaped `research-report/v2` content (W1 D1): ids, no digests, no origin.

    External references (the task's original artifact, rubric and policy; the fragment's capture
    and representation) are complete, as the host handed them to the producer.
    """

    task: dict[str, Any] = {
        "id": f"task-{report_id}",
        "domain": "engineering",
        "originalTask": _artifact(f"task-input-{report_id}"),
        "obligations": [
            {
                "id": "finding.size",
                "description": "State the size.",
                "weight": 10000,
                "required": True,
            }
        ],
        "asOf": "2026-10-28T00:00:00Z",
        "permittedMedia": ["text_markdown"],
        "rubric": _artifact("rubric-engineering", "rubric"),
        "policy": _artifact("policy-ai-engineer", "policy"),
        "minimumRisk": "medium",
        "limits": {
            "calls": 20,
            "tokens": 300000,
            "costUsd": "1",
            "deadline": "2026-11-30T00:00:00Z",
        },
    }
    if use is not None:
        task["use"] = use
    if audience is not None:
        task["audience"] = audience
    fragment = f"frag-{report_id}"
    assertion = f"asr-{report_id}"
    claim = {
        "type": "claim",
        "occurrenceId": f"occ-{report_id}",
        "assertion": assertion,
        "text": "Mistral 7B has 7 billion parameters",
        "obligations": ["finding.size"],
        "attribution": None,
    }
    paragraph = {
        "type": "paragraph",
        "id": "p1",
        "inlines": [claim, {"type": "citation", "label": "c1", "fragment": fragment}],
        "excludedReason": None,
    }
    return {
        "task": task,
        "fragments": [
            {
                "id": fragment,
                "sourceVersion": "arxiv-2310.06825@2026-10-28",
                "capture": _artifact("capture-arxiv-2310.06825"),
                "representation": _artifact("representation-arxiv-2310.06825"),
                "selector": {
                    "kind": "text_quote",
                    "value": quote,
                    "resolverVersion": "text-quote.v3",
                    "normalizationVersion": "text-norm.v1",
                },
                "context": {
                    "header": "Mistral 7B, abstract",
                    "footnotes": [],
                    "surroundingDigest": None,
                },
                "parserLineage": ["frozen-quote.v1"],
                "captureCompleteness": "complete",
                "access": {"rights": "public", "limits": []},
                "originFamily": None,
            }
        ],
        "assertions": [
            {
                "id": assertion,
                "logicalId": "mistral-7b-size",
                "proposition": "Mistral 7B has 7 billion parameters.",
                "kind": "source_report",
                "value": {"type": "quantity", "amount": "7000000000", "unit": "parameters"},
                "subject": "mistral-7b",
                "object": None,
                "qualifiers": {
                    "profile": "engineering.v2",
                    "entity": "mistral-7b",
                    "unit": "parameters",
                },
                "riskReasons": [],
            }
        ],
        "supportSets": [
            {
                "id": f"ss-{report_id}",
                "assertion": assertion,
                "provenance": "declared_citation",
                "required": [{"premise": "size", "evidence": [fragment], "derivedFrom": []}],
                "contrary": [],
            }
        ],
        "report": {
            "reportId": report_id,
            "revision": revision,
            "kind": "evidence_report",
            "structuredBody": {
                "sections": [
                    {
                        "id": "findings",
                        "heading": [{"type": "text", "text": "Findings"}],
                        "headingExcludedReason": None,
                        "blocks": [paragraph],
                    }
                ]
            },
        },
    }


__all__ = [
    "RECORD_KINDS",
    "StoredPackage",
    "describe_document",
    "fresh_registration",
    "model_content",
    "model_report",
    "package_ref",
    "read_intent_answer",
    "report_package",
]
