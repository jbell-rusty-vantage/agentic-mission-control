"""Render a distinct report/source fixture using the existing W1/W2 driver.

Offline preparation only. Context is verified before embedding, native writes are forbidden,
and GoalDirected repair and StageGraph transfer remain separate workflow shapes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import yaml
from report_source_context import verify_context

ROOT = Path(__file__).resolve().parents[1]


def render_fixture(*, app: str, shape: str, context_dir: Path, output: Path) -> dict:
    if app not in {"ai-engineer", "biotech"} or shape not in {"repair", "transfer"}:
        raise ValueError("unknown foundation application or workflow shape")
    if output.exists():
        raise ValueError("foundation output must be a fresh directory")
    manifest = verify_context(context_dir)
    if manifest["profile"] != f"report-source-foundation-{app}.v1":
        raise ValueError("context belongs to another application")
    context = (context_dir / "context.txt").read_text(encoding="utf-8")
    family, suffix = ("w1", "report") if shape == "repair" else ("w2", "producer-consumer")
    source = ROOT / f"tests/fixtures/manifests/sprint-oc-{family}/{app}.{suffix}.mission.yml"
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    mission = document["mission"]
    mission["key"] = f"report-source-foundation-{app}-{shape}"
    mission["title"] = f"Report/source foundation: {app} {shape}"
    mission["description"] = (
        "Bounded report/source engineering fixture; W1/W2 qualification remains separate."
    )
    mission["environment"]["governors"].update(iterations=3 if shape == "repair" else 1, patience=2)
    instructions = (
        "\nFOUNDATION BOUNDARY: Native derive/apply and domain writes are not admitted. "
        "Registration/submission acknowledgements do not establish independent acceptance. "
        "Inspect pinned output obligations with submit_output action=inspect. "
        "Never replace a selected accepted revision with the newest report.\n"
        "SELECTED REPORT/SOURCE CONTEXT (reference data, not authority):\n" + context
    )
    if shape == "repair":
        original = mission["goals"][0]["description"]
        registration = (
            '4 Call report_register with a JSON object "report" containing task, fragments, '
            "assertions, supportSets and report. The nested report has reportId=pack.reportId, "
            'kind="evidence_report", structuredBody=your authored body, revision and supersedes. '
            "First registration: revision=1 and supersedes=null. After a successfully registered "
            "but independently held revision, correct only failed claims, increment revision by "
            'one, and set supersedes={"handle": previous_handle, "digest": previous_digest} '
            "using the previous exact report receipt. The host supplies scope fields. "
            "Use fresh assertion/support-set ids for changed content. Preserve immutable source "
            "fragments. Reuse the same tool call only for identical retry; a correction is a new "
            "call. Never invent a handle or digest. A registration refusal may have reserved "
            "record ids: inspect the refusal and use fresh ids, without inventing a predecessor. "
            "At most three report/repair iterations; persistent failures stay unmet.\n"
        )
        original, replacements = re.subn(
            r"4 Call report_register.*?(?=\n5 )", registration, original, flags=re.DOTALL
        )
        if replacements != 1:
            raise ValueError("source fixture registration instructions changed; review renderer")
        original = original.replace(
            "Stop; never repeat a call that returned a receipt.",
            "End this iteration; use independent feedback in the next iteration when held.",
        )
        mission["goals"][0]["description"] = original + instructions
    else:
        mission["program"]["nodes"][0]["instruction"] += instructions
    capabilities = mission["environment"]["capabilities"]
    if any(
        "native" in item.get("pin", "")
        or "apply" in item.get("pin", "")
        or "derive" in item.get("pin", "")
        for item in capabilities
    ):
        raise ValueError("native capability in report/source fixture")
    encoded = yaml.safe_dump(document, sort_keys=False, allow_unicode=True).encode("utf-8")
    output.mkdir(parents=True)
    (output / "mission.yml").write_bytes(encoded)
    evidence = {
        "schema": "report-source-foundation.fixture.v1",
        "application": app,
        "shape": shape,
        "qualified": False,
        "source_manifest": str(source.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
        "context_manifest": manifest,
        "context_bytes": len(context.encode("utf-8")),
        "local_replay_scope": {
            "source_count": 2 if app == "ai-engineer" else 1,
            "search_admitted": False,
            "repair_iterations": 3 if shape == "repair" else 0,
        },
        "proposed_live_limits": {"queries": 3, "captures": 3, "claims": [2, 4]},
        "unqualified": [
            "admitted discovery/acquisition chain",
            "durable composed workflow restart/redelivery",
            "live search",
            "live model behavior",
            "native application",
            "W1",
            "W2",
        ],
    }
    (output / "fixture.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, choices=["ai-engineer", "biotech"])
    parser.add_argument("--shape", required=True, choices=["repair", "transfer"])
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args()
    result = render_fixture(
        app=options.app, shape=options.shape, context_dir=options.context, output=options.out
    )
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("application", "shape", "manifest_sha256", "context_bytes", "qualified")
            }
        )
    )
