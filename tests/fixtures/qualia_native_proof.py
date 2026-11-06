"""Full-run scope from trusted BKS saved plans and exact physical effect readback.

Model previews/accepted prose are deliberately not an authority for graph presence.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from tests.fixtures.qualia_web_tools import SEED_URLS


def _physical(receipt: dict[str, Any], pages: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    effects = receipt["effects"]
    expected = Counter(
        [("node", n["uid"]) for n in effects["nodes"]]
        + [("relationship", r["key"]) for r in effects["relationships"]]
    )
    checked: Counter[tuple[str, str]] = Counter()
    nodes: set[str] = set()
    endpoints: set[str] = set()
    cursor = 0
    assert pages, "Native scope has no physical readback"
    for index, page in enumerate(pages):
        assert page["effectKey"] == receipt["effect"]["effectKey"]
        assert page["receiptId"] == receipt["receiptId"]
        assert page["cursor"] == cursor and page["total"] == sum(expected.values())
        assert page["checked"] == len(page["items"]) and not page["failures"]
        for item in page["items"]:
            assert item["ok"] is True and all(c["ok"] is True for c in item["checks"])
            assert any(c["name"] == "exists" for c in item["checks"]), "No physical existence check"
            checked[(item["kind"], item["key"])] += 1
            if item["kind"] == "node":
                assert any(c["name"] == "properties" for c in item["checks"])
                nodes.add(item["key"])
            else:
                for relation in effects["relationships"]:
                    if relation["key"] == item["key"] and relation["op"] == "create":
                        if relation.get("relationshipUid"):
                            assert any(c["name"] == "endpoints" for c in item["checks"])
                        endpoints.update((relation["fromUid"], relation["toUid"]))
        if page["complete"]:
            assert index == len(pages) - 1 and page["nextCursor"] is None
        else:
            assert isinstance(page["nextCursor"], int) and page["nextCursor"] > cursor
            cursor = page["nextCursor"]
    assert pages[-1]["complete"] is True and checked == expected, (
        "Incomplete/foreign native readback"
    )
    assert effects["total"] == sum(expected.values())
    return nodes, endpoints


def verify_native_scope(root: Path, run_id: str, results: Any) -> dict[str, Any]:
    """Full fixture only. A current-run admitted effect must prove every counted entity.

    Append-only host records retain the unbounded saved plan/receipt even when the model's
    16KB tool preview was truncated. Exact plan, intent, effect, dispatch, run and scope
    links select those records; the BKS host already verifies canonical plan digests.
    """
    rows = [
        json.loads(line)
        for line in (root / "ks-host.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    entities: dict[str, dict[str, Any]] = {}
    snapshots: dict[str, str] = {}
    applied = []
    for result in results:
        if (result.get("native") or {}).get("status") != "native_applied" or (
            result.get("native_context") or {}
        ).get("run", {}).get("runId") != run_id:
            continue
        dispatch = result["dispatch"]
        assert dispatch["dispatched"] is True and dispatch["decision"]["disposition"] == "admitted"
        assert dispatch["decision"]["admissibility"]["status"] == "admitted"
        assert dispatch["decision"]["reviewPending"] is False
        assert dispatch["decision"]["report"] == result["report"] == dispatch["decision"]["subject"]
        effect = dispatch["effectKey"]
        receipts = [
            row["value"]["receipt"]
            for row in rows
            if row["kind"] == "native_receipt"
            and row["value"].get("found")
            and row["value"].get("receipt", {}).get("effect", {}).get("effectKey") == effect
        ]
        assert receipts and all(r == receipts[-1] for r in receipts), (
            "Missing/conflicting native receipt"
        )
        receipt = receipts[-1]
        assert receipt["outcome"] in {"applied", "duplicate", "noop"}
        plans = [
            row["value"]
            for row in rows
            if row["kind"] == "native_plan"
            and row["value"]["plan"]["planRef"] == receipt["plan"]["planRef"]
            and row["value"]["plan"]["planDigest"] == receipt["plan"]["planDigest"]
        ]
        assert plans and all(p == plans[-1] for p in plans), "Missing/conflicting saved native plan"
        saved = plans[-1]
        plan, intent = saved["plan"], saved["frozen"]["intent"]
        assert plan["outcome"] in {"applicable", "noop"} and not plan.get("errors")
        assert all(p["disposition"] in {"admitted", "noop_duplicate"} for p in plan["proposals"])
        assert intent["context"]["run"] == result["native_context"]["run"]
        assert plan["activity"]["runId"] == run_id
        assert plan["binding"]["intentId"] == intent["intentId"] == receipt["intent"]["intentId"]
        assert plan["binding"]["intentDigest"] == receipt["intent"]["intentDigest"]
        for key in ("installationId", "applicationId", "tenantId"):
            assert saved["frozen"]["principal"][key] == receipt["effect"]["scope"][key]
        assert receipt["effect"]["scope"]["applicationId"] == "biotech"
        assert plan["effects"] == {k: receipt["effects"][k] for k in ("nodes", "relationships")}
        acks = [
            a
            for row in rows
            if row["kind"] == "consumer"
            for a in row["value"].get("results", [])
            if a.get("effectKey") == effect and a.get("receiptId") == receipt["receiptId"]
        ]
        assert acks and any(
            a.get("acknowledged") is True
            and a.get("componentState") == "acknowledged"
            and a.get("outcome") in {"applied", "duplicate"}
            and a.get("planDigest") == receipt["plan"]["planDigest"]
            and all(
                a.get(k) == receipt["admission"].get(k)
                for k in ("dispatchId", "markerDigest", "payloadDigest")
            )
            for a in acks
        )
        # Repeated complete pages from an exact idempotent consume are harmless. Conflicting
        # versions are refused; no joining partial evidence across different readbacks.
        pages_by_cursor: dict[int, dict[str, Any]] = {}
        for row in rows:
            if row["kind"] != "effect_readback":
                continue
            page = row["value"]
            if page.get("effectKey") != effect or page.get("receiptId") != receipt["receiptId"]:
                continue
            previous = pages_by_cursor.setdefault(page["cursor"], page)
            assert previous == page, "Conflicting native readback"
        nodes, endpoints = _physical(receipt, [pages_by_cursor[k] for k in sorted(pages_by_cursor)])
        declared = {subject["ref"]: subject for subject in intent["subjects"]}
        for subject in plan["subjects"]:
            uid, kind = subject["uid"], subject["nodeType"]
            assert subject["disposition"] in {"create", "use_existing"} and uid
            canonical = declared[subject["ref"]]
            assert canonical["nodeType"] == kind
            own_nodes = [
                n for n in receipt["effects"]["nodes"] if n["uid"] == uid and n["label"] == kind
            ]
            if subject["disposition"] == "create":
                assert any(n["op"] == "create" for n in own_nodes) and uid in nodes
            else:
                assert any(m["uid"] == uid for m in subject["matches"])
                assert (own_nodes and uid in nodes) or uid in endpoints, (
                    "Reused subject not physically verified"
                )
            observed = saved["frozen"]["observations"].get(f"node:{uid}") or {}
            properties = dict(observed.get("props", {}))
            if canonical["mode"] == "new":
                values = {"name": canonical["name"], **canonical.get("properties", {})}
                written = {p for node in own_nodes for p in node["properties"]}
                properties.update({k: v for k, v in values.items() if k in written})
            entry = {"node_type": kind, "properties": properties}
            assert uid not in entities or entities[uid]["node_type"] == kind
            entities[uid] = entry
        canonical_sources = {source["ref"]: source for source in intent["sources"]}
        for source in plan["sources"]:
            uid = source["snapshotUid"]
            canonical = canonical_sources[source["ref"]]
            snapshot = canonical.get("snapshot")
            assert (
                snapshot and uid and canonical["source"]["canonicalUri"] == source["canonicalUri"]
            )
            assert snapshot["contentHash"].startswith("sha256:") and snapshot["storageUri"]
            assert uid in nodes or uid in endpoints, "Source snapshot not physically verified"
            snapshots[source["canonicalUri"]] = uid
        applied.append(
            {
                "effect_key": effect,
                "receipt_id": receipt["receiptId"],
                "plan_ref": plan["planRef"],
                "plan_digest": plan["planDigest"],
            }
        )
    assert applied, "No current-run admitted native graph proof"
    products = {
        uid
        for uid, e in entities.items()
        if e["node_type"] == "Product"
        and e["properties"].get("productKind") == "DIETARY_SUPPLEMENT"
    }
    compounds = {
        uid
        for uid, e in entities.items()
        if e["node_type"] in {"ChemicalSubstance", "IngredientMaterial"}
    }
    organizations = {uid for uid, e in entities.items() if e["node_type"] == "Organization"}
    people = {
        uid
        for uid, e in entities.items()
        if e["node_type"] == "Person"
        and e["properties"].get("privacyClass") == "PUBLIC"
        and e["properties"].get("publicActorBasis")
    }
    assert len(products) >= 2, "Full native scope lacks two supplement Products"
    assert len(compounds) >= 4, "Full native scope lacks four chemical/material subjects"
    assert organizations, "Full native scope lacks an Organization"
    assert people, "Full native scope lacks a public Person"
    assert set(SEED_URLS) <= snapshots.keys(), (
        "Full native scope lacks product/study SourceSnapshots"
    )
    proof = {
        "run_id": run_id,
        "qualified": False,
        "effects": applied,
        "products": sorted(products),
        "compounds": sorted(compounds),
        "organizations": sorted(organizations),
        "people": sorted(people),
        "source_snapshots": snapshots,
    }
    (root / f"native-scope-proof-{run_id}.json").write_text(
        json.dumps(proof, indent=2), encoding="utf-8"
    )
    return proof
