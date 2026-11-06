#!/usr/bin/env python3
"""Run the retrieval fixtures (.sdlc/fixtures/retrieval/queries.json) against okf_search.py.

Usage:
  python docs/tools/bench_retrieval.py --out .sdlc/fixtures/retrieval/baseline.json
  python docs/tools/bench_retrieval.py --repo ../mc-bench-before --out baseline-before.json
  python docs/tools/bench_retrieval.py --gate   # compare with baseline.json, exit 1 on regression

Scoring (documented in .sdlc/fixtures/retrieval/README.md):
  query cases   hit@3, hit@10 (any expected document in the top k), reciprocal rank of the first.
  task cases    set recall per expect field over the top 10 (concepts, modules, research, facts).
  negative      passes when search returns no result at all (okf_search never abstains today).
  critical      query: hit@3; task: every gate threshold in the case's `gate` met.
                `--gate` fails on a regression or new failure against the baseline;
                known failures are only listed.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_QUERIES = REPO_ROOT / ".sdlc" / "fixtures" / "retrieval" / "queries.json"
DEFAULT_BASELINE = REPO_ROOT / ".sdlc" / "fixtures" / "retrieval" / "baseline.json"


def run_search(repo: Path, text: str, limit: int = 10) -> list[dict]:
    proc = subprocess.run(
        [
            sys.executable,
            str(repo / "docs" / "tools" / "okf_search.py"),
            "--limit",
            str(limit),
            "--json",
            text,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    out = proc.stdout.strip()
    if not out.startswith("["):
        return []
    return json.loads(out)


def tracked_guides(repo: Path) -> set[str]:
    proc = subprocess.run(
        ["git", "ls-files", "*AGENTS.md"], cwd=repo, capture_output=True, text=True, check=False
    )
    return {
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip()
        and "tests/fixtures" not in line
        and line.strip() != "AGENTS.md"
        and not line.startswith("docs/")
    }


def covering_guide(module: str, guides: set[str]) -> str | None:
    """Nearest existing module guide at or above `module` (excluding the root guide)."""
    parts = module.strip("/").split("/")
    while parts:
        candidate = "/".join(parts) + "/AGENTS.md"
        if candidate in guides:
            return candidate
        parts.pop()
    return None


def result_paths(results: list[dict]) -> list[str]:
    return [r["path"].split("#")[0] for r in results]


def concept_hit(path: str, slug: str) -> bool:
    return path == f"docs/knowledge/{slug}.md"


def research_hit(path: str, slug: str) -> bool:
    return path == f"docs/research/{slug}.md"


def module_hit(path: str, module: str, guides: set[str], covering: bool) -> bool:
    if covering:
        guide = covering_guide(module, guides)
        return guide is not None and path == guide
    return path == module.strip("/") + "/AGENTS.md"


def fact_found(repo: Path, paths: list[str], probes: list[str]) -> bool:
    for rel in paths:
        file = repo / rel
        if not file.is_file():
            continue
        text = file.read_text(encoding="utf-8", errors="replace").lower()
        if all(p.lower() in text for p in probes):
            return True
    return False


def score_case(repo: Path, case: dict, guides: set[str]) -> dict:
    text = case.get("query") or case["task"]
    results = run_search(repo, text)
    paths = result_paths(results)
    expect = case["expect"]
    kinds: dict[str, list[tuple[str, callable]]] = {
        "concepts": [(s, lambda p, s=s: concept_hit(p, s)) for s in expect["concepts"]],
        "research": [(s, lambda p, s=s: research_hit(p, s)) for s in expect["research"]],
        "modules": [(m, lambda p, m=m: module_hit(p, m, guides, True)) for m in expect["modules"]],
    }
    ranks: list[int] = []
    set_recall: dict[str, float | None] = {}
    found: dict[str, list[str]] = {}
    for kind, items in kinds.items():
        hits = []
        for name, test in items:
            where = [i + 1 for i, p in enumerate(paths) if test(p)]
            if where:
                hits.append(name)
                ranks.append(where[0])
        found[kind] = hits
        set_recall[kind] = (len(hits) / len(items)) if items else None
    strict_modules = [
        m for m in expect["modules"] if any(module_hit(p, m, guides, False) for p in paths)
    ]
    facts = expect["facts"]
    probes = case.get("fact_probes", {})
    fact_hits = [f for f in facts if fact_found(repo, paths, probes.get(f, []))] if facts else []
    set_recall["facts"] = (len(fact_hits) / len(facts)) if facts else None
    found["facts"] = fact_hits
    best = min(ranks) if ranks else None
    record = {
        "id": case["id"],
        "kind": case["kind"],
        "partition": case["partition"],
        "critical": case.get("critical", False),
        "top10": paths,
        "best_rank": best,
        "hit_at_3": bool(best and best <= 3),
        "hit_at_10": bool(best and best <= 10),
        "rr": (1.0 / best) if best else 0.0,
        "set_recall": set_recall,
        "found": found,
        "strict_modules_found": strict_modules,
    }
    if case["partition"] == "negative":
        record["pass"] = len(results) == 0
    elif case["kind"] == "task":
        gate = case.get("gate", {})
        ok = True
        if "concepts_recall_at_10" in gate:
            ok &= (set_recall["concepts"] or 0) >= gate["concepts_recall_at_10"]
        if "modules_recall_at_10" in gate:
            ok &= (set_recall["modules"] or 0) >= gate["modules_recall_at_10"]
        if gate.get("facts") == "all" and facts:
            ok &= set_recall["facts"] == 1.0
        record["pass"] = bool(ok)
    else:
        record["pass"] = record["hit_at_3"]
    return record


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def aggregate(records: list[dict]) -> dict:
    out: dict = {}
    for part in ("screening", "heldout", "negative"):
        rows = [r for r in records if r["partition"] == part]
        if part == "negative":
            out[part] = {"cases": len(rows), "abstained": sum(1 for r in rows if r["pass"])}
            continue
        queries = [r for r in rows if r["kind"] == "query"]
        tasks = [r for r in rows if r["kind"] == "task"]
        entry: dict = {
            "queries": len(queries),
            "recall_at_3": mean([1.0 if r["hit_at_3"] else 0.0 for r in queries]),
            "recall_at_10": mean([1.0 if r["hit_at_10"] else 0.0 for r in queries]),
            "mrr": mean([r["rr"] for r in queries]),
            "tasks": len(tasks),
        }
        for kind in ("concepts", "modules", "research", "facts"):
            entry[f"task_{kind}_set_recall"] = mean(
                [r["set_recall"][kind] for r in tasks if r["set_recall"][kind] is not None]
            )
        out[part] = entry
    critical = [r for r in records if r["critical"]]
    out["critical"] = {
        "passed": sum(1 for r in critical if r["pass"]),
        "total": len(critical),
        "cases": {r["id"]: ("pass" if r["pass"] else "fail") for r in critical},
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--repo", type=Path, default=REPO_ROOT, help="repository whose okf_search.py is measured"
    )
    ap.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    ap.add_argument("--out", type=Path)
    ap.add_argument(
        "--gate",
        action="store_true",
        help="fail on a critical failure or a drop against the baseline",
    )
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    repo = args.repo.resolve()
    cases = json.loads(args.queries.read_text(encoding="utf-8"))["cases"]
    guides = tracked_guides(repo)
    records = [score_case(repo, c, guides) for c in cases]
    report = {
        "schema": "mc.retrieval-baseline.v1",
        "repo_head": subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=False
        ).stdout.strip(),
        "summary": aggregate(records),
        "cases": records,
    }
    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    elif not args.gate:
        print(text)
    if args.gate:
        failed = False
        base = (
            json.loads(args.baseline.read_text(encoding="utf-8"))
            if args.baseline.exists()
            else None
        )
        known = {c["id"]: c for c in base["cases"]} if base else {}
        for r in records:
            before = known.get(r["id"])
            if r["pass"]:
                continue
            if before is not None and not before["pass"]:
                if r["critical"]:
                    print(f"known critical failure (in the baseline): {r['id']}")
                continue
            print(f"{'critical ' if r['critical'] else ''}regression or new failure: {r['id']}")
            failed = True
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
