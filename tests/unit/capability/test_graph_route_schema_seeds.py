"""OVE-171 / WI-08: the W2 graph-variant schemas ship as `mc.catalog.artifact-schemas@1.0.1`, a
successor of the applied 1.0.0 bundle that carries only new logical keys; every schema is in the
validator's supported subset and every W2 fixture's structured output names one of them."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from mission_control.application.programs.artifact_validation import supported_schema

ROOT = Path(__file__).resolve().parents[3]
SEEDS = ROOT / "packages/mission-control-db-contract/seeds"
SUCCESSOR = "common/mc.catalog.artifact-schemas-1.0.1.json"
PREVIOUS = "common/mc.catalog.artifact-schemas-1.0.0.json"


def _generator():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "mc_generate_catalog_seeds", SEEDS / "generate_catalog_seeds.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _schemas(bundle: dict) -> dict[str, dict]:
    return {
        record["fields"]["manifest"]["definition"]["logical_id"]: record["fields"]["manifest"][
            "definition"
        ]["json_schema"]
        for record in bundle["records"]
        if record["kind"] == "asset_version"
    }


def test_the_successor_is_committed_generated_and_additive() -> None:
    generator = _generator()
    generated = generator.build_bundles()
    committed = (SEEDS / SUCCESSOR).read_bytes()
    assert generator.encode(generated[SUCCESSOR]) == committed
    successor = json.loads(committed)
    previous = json.loads((SEEDS / PREVIOUS).read_bytes())
    assert successor["depends_on"] == [
        {"seed_key": "mc.catalog.artifact-schemas", "seed_version": "1.0.0"}
    ]
    old_keys = {record["logical_key"] for record in previous["records"]}
    assert old_keys.isdisjoint(record["logical_key"] for record in successor["records"])
    assert generator.encode(generated[PREVIOUS]) == (SEEDS / PREVIOUS).read_bytes()


def test_every_schema_is_supported_and_accepts_its_fixture_shape() -> None:
    schemas = _schemas(json.loads((SEEDS / SUCCESSOR).read_bytes()))
    assert set(schemas) == {
        "schema.w2-triage-verdict",
        "schema.w2-scan-flag",
        "schema.w2-critique-verdict",
    }
    samples = {
        "schema.w2-triage-verdict": {"severity": "high", "source_count": 3},
        "schema.w2-scan-flag": {"flagged": False},
        "schema.w2-critique-verdict": {"approved": True, "score": 80, "findings": []},
    }
    for logical_id, schema in schemas.items():
        assert supported_schema(schema), logical_id
        Draft202012Validator(schema).validate(samples[logical_id])
    fixtures = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "tests/fixtures/manifests/sprint-oc-w2").glob("graph.*.yml")
    )
    for logical_id in schemas:
        assert f"{logical_id}@1" in fixtures
