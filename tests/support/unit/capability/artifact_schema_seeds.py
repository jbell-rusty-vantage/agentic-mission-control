"""Builders, constants and fakes that other test files import.

Moved from tests/unit/capability/test_artifact_schema_seeds.py.
"""

import json
from pathlib import Path

from mission_control.domain.authoring.contracts import PublishedDefinition

ROOT = Path(__file__).resolve().parents[4]
SEEDS = ROOT / "packages/mission-control-db-contract/seeds"


def production_record():
    bundle = json.loads((SEEDS / "common/mc.catalog.artifact-schemas-1.0.0.json").read_text())
    asset = next(row for row in bundle["records"] if row["kind"] == "asset_version")
    return PublishedDefinition.model_validate(asset["fields"]["manifest"])
