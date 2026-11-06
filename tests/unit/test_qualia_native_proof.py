from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.qualia_native_proof import verify_native_scope
from tests.fixtures.qualia_web_tools import SEED_URLS

RUN = "actual-current-run"
SCOPE = {"installationId": "installation", "applicationId": "biotech", "tenantId": "tenant"}


def evidence(*, reused: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    context = {"run": {"system": "mission-control", "runId": RUN, "operationId": "ingest"}}
    subjects, canonical, nodes, relations, observations = [], [], [], [], {}
    for index, kind in enumerate(
        [
            "Product",
            "Product",
            "ChemicalSubstance",
            "ChemicalSubstance",
            "IngredientMaterial",
            "IngredientMaterial",
            "Organization",
            "Person",
        ]
    ):
        uid, ref = f"hu:{kind}:{index}", f"entity-{index}"
        properties = {"name": f"Actual captured {kind} {index}"}
        if kind == "Product":
            properties["productKind"] = "DIETARY_SUPPLEMENT"
        elif kind == "Person":
            properties.update(privacyClass="PUBLIC", publicActorBasis=["PUBLIC_AUTHOR"])
        subjects.append(
            {
                "ref": ref,
                "uid": uid,
                "nodeType": kind,
                "disposition": "use_existing" if reused else "create",
                "matches": [{"uid": uid}] if reused else [],
            }
        )
        canonical.append(
            {
                "ref": ref,
                "mode": "new",
                "nodeType": kind,
                "name": properties["name"],
                "properties": properties,
            }
        )
        if reused:
            # Actual BKS observation projection retains name but not arbitrary domain
            # fields. Fork Product/Person upserts must physically verify those fields.
            observations[f"node:{uid}"] = {"props": {"name": properties["name"]}}
            if kind in {"Product", "Person"}:
                nodes.append(
                    {"uid": uid, "label": kind, "op": "update", "properties": list(properties)}
                )
            relations.append(
                {
                    "key": f"ASSESSES|activity|{uid}",
                    "type": "ASSESSES",
                    "fromUid": "activity",
                    "toUid": uid,
                    "op": "create",
                    "relationshipUid": None,
                }
            )
        else:
            nodes.append(
                {"uid": uid, "label": kind, "op": "create", "properties": list(properties)}
            )
    sources, source_inputs = [], []
    for index, url in enumerate(SEED_URLS):
        ref, snapshot = f"source-{index}", f"snapshot-{index}"
        sources.append({"ref": ref, "canonicalUri": url, "snapshotUid": snapshot})
        source_inputs.append(
            {
                "ref": ref,
                "source": {"canonicalUri": url},
                "snapshot": {
                    "contentHash": "sha256:" + "a" * 64,
                    "storageUri": f"ks-custody:{snapshot}",
                },
            }
        )
        nodes.append(
            {
                "uid": snapshot,
                "label": "SourceSnapshot",
                "op": "create",
                "properties": ["contentHash", "storageUri"],
            }
        )
    plan = {
        "planRef": "actual-plan",
        "planDigest": "actual-plan-digest",
        "outcome": "applicable",
        "binding": {"intentId": "actual-intent", "intentDigest": "actual-intent-digest"},
        "activity": {"runId": RUN},
        "subjects": subjects,
        "sources": sources,
        "proposals": [],
        "effects": {"nodes": nodes, "relationships": relations},
    }
    stored = {
        "plan": plan,
        "frozen": {
            "intent": {
                "intentId": "actual-intent",
                "context": context,
                "subjects": canonical,
                "sources": source_inputs,
            },
            "observations": observations,
            "principal": SCOPE,
        },
    }
    receipt = {
        "receiptId": "actual-receipt",
        "outcome": "applied",
        "effect": {"effectKey": "actual-effect", "scope": SCOPE},
        "plan": {"planRef": plan["planRef"], "planDigest": plan["planDigest"]},
        "intent": plan["binding"],
        "admission": {
            "dispatchId": "actual-dispatch",
            "markerDigest": "actual-marker",
            "payloadDigest": "actual-payload",
        },
        "effects": {},
    }
    ack = {
        "effectKey": "actual-effect",
        "receiptId": "actual-receipt",
        "acknowledged": True,
        "componentState": "acknowledged",
        "outcome": "applied",
        "planDigest": plan["planDigest"],
        **receipt["admission"],
    }
    rows = [
        {"kind": "native_plan", "value": stored},
        {"kind": "native_receipt", "value": {"found": True, "receipt": receipt}},
        {"kind": "consumer", "value": {"results": [ack]}},
    ]
    report = {"id": "actual-frozen-report", "digest": "actual-report-digest"}
    results = [
        {
            "native": {
                "status": "native_applied",
                "content": "BOUNDED MODEL PREVIEW" * 1000,
                "model_excerpt_truncated": True,
            },
            "native_context": copy.deepcopy(context),
            "report": report,
            "dispatch": {
                "effectKey": "actual-effect",
                "dispatched": True,
                "decision": {
                    "disposition": "admitted",
                    "admissibility": {"status": "admitted"},
                    "reviewPending": False,
                    "report": report,
                    "subject": report,
                },
            },
        }
    ]
    rebuild(rows)
    return rows, results


def rebuild(rows: list[dict[str, Any]]) -> None:
    plan, receipt = rows[0]["value"]["plan"], rows[1]["value"]["receipt"]
    receipt["effects"] = {
        **copy.deepcopy(plan["effects"]),
        "total": len(plan["effects"]["nodes"]) + len(plan["effects"]["relationships"]),
    }
    items = [
        {
            "kind": "node",
            "key": n["uid"],
            "ok": True,
            "checks": [{"name": "exists", "ok": True}, {"name": "properties", "ok": True}],
        }
        for n in plan["effects"]["nodes"]
    ]
    items += [
        {
            "kind": "relationship",
            "key": r["key"],
            "ok": True,
            "checks": [{"name": "exists", "ok": True}, {"name": "endpoints", "ok": True}],
        }
        for r in plan["effects"]["relationships"]
    ]
    rows[:] = [row for row in rows if row["kind"] != "effect_readback"]
    rows.append(
        {
            "kind": "effect_readback",
            "value": {
                "effectKey": "actual-effect",
                "receiptId": "actual-receipt",
                "cursor": 0,
                "nextCursor": None,
                "complete": True,
                "total": len(items),
                "checked": len(items),
                "failures": 0,
                "items": items,
            },
        }
    )


def write(root: Path, rows: Any) -> None:
    (root / "ks-host.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows), encoding="utf-8"
    )


@pytest.mark.parametrize("reused", [False, True])
def test_full_scope_uses_unbounded_host_plan_and_physical_proof_including_fork_reuse(
    tmp_path, reused
):
    rows, results = evidence(reused=reused)
    results.insert(0, {"native": None, "native_context": None, "dispatch": None})
    write(tmp_path, rows)
    proof = verify_native_scope(tmp_path, RUN, results)
    assert len(proof["products"]) == 2 and len(proof["compounds"]) == 4
    assert len(proof["people"]) == 1 and len(proof["organizations"]) == 1
    assert set(proof["source_snapshots"]) == set(SEED_URLS)
    assert proof["qualified"] is False
    assert (tmp_path / f"native-scope-proof-{RUN}.json").exists()


@pytest.mark.parametrize("kind", ["Product", "ChemicalSubstance", "Organization", "Person"])
def test_omitted_domain_subject_is_not_replaced_by_model_claims(tmp_path, kind):
    rows, results = evidence()
    saved = rows[0]["value"]
    subject = next(s for s in saved["plan"]["subjects"] if s["nodeType"] == kind)
    saved["plan"]["subjects"].remove(subject)
    saved["frozen"]["intent"]["subjects"] = [
        s for s in saved["frozen"]["intent"]["subjects"] if s["ref"] != subject["ref"]
    ]
    saved["plan"]["effects"]["nodes"] = [
        n for n in saved["plan"]["effects"]["nodes"] if n["uid"] != subject["uid"]
    ]
    results[0]["native"]["content"] = "Two products; four compounds; Organization; public Person"
    rebuild(rows)
    write(tmp_path, rows)
    with pytest.raises(AssertionError, match="Full native scope lacks"):
        verify_native_scope(tmp_path, RUN, results)


@pytest.mark.parametrize(
    "corruption",
    [
        "subject_effect",
        "public_person",
        "supplement_kind",
        "study_capture",
        "source_snapshot",
        "native_plan",
        "ack",
        "page",
        "run",
        "receipt_plan",
        "reused_match",
        "reused_endpoint",
    ],
)
def test_native_scope_refuses_missing_or_foreign_authority(tmp_path, corruption):
    reused = corruption.startswith("reused")
    rows, results = evidence(reused=reused)
    plan, frozen = rows[0]["value"]["plan"], rows[0]["value"]["frozen"]
    if corruption == "subject_effect":
        plan["effects"]["nodes"] = [n for n in plan["effects"]["nodes"] if n["label"] != "Person"]
        rebuild(rows)
    elif corruption == "public_person":
        next(s for s in frozen["intent"]["subjects"] if s["nodeType"] == "Person")["properties"][
            "privacyClass"
        ] = "INTERNAL"
    elif corruption == "supplement_kind":
        next(s for s in frozen["intent"]["subjects"] if s["nodeType"] == "Product")["properties"][
            "productKind"
        ] = "OTHER"
    elif corruption == "study_capture":
        plan["sources"].pop()
    elif corruption == "source_snapshot":
        plan["effects"]["nodes"] = [n for n in plan["effects"]["nodes"] if n["uid"] != "snapshot-4"]
        rebuild(rows)
    elif corruption == "native_plan":
        rows.pop(0)
    elif corruption == "ack":
        rows[2]["value"]["results"][0]["acknowledged"] = False
    elif corruption == "page":
        rows[-1]["value"]["items"].pop()
    elif corruption == "run":
        frozen["intent"]["context"]["run"]["runId"] = "another-run"
    elif corruption == "receipt_plan":
        rows[1]["value"]["receipt"]["plan"]["planDigest"] = "another-plan"
    elif corruption == "reused_match":
        plan["subjects"][0]["matches"] = []
    elif corruption == "reused_endpoint":
        # A reused chemical has no node write; its relationship is the only physical proof.
        plan["effects"]["relationships"].pop(2)
        rebuild(rows)
    write(tmp_path, rows)
    with pytest.raises(AssertionError):
        verify_native_scope(tmp_path, RUN, results)
