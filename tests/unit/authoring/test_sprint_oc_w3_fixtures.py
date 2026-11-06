"""The Sprint OC W3 slice A fixtures compile offline (WI-07 / OVE-170).

Each app's report-collection manifest (frozen pack and producer profile substituted as the driver
does) passes the structural compile and lowers to a goal-scoped required ``reports`` promise of
exactly three distinct report references, each judged per exact revision, plus an
iteration-scoped progress note, under a Goal Loop with at least three iterations.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mission_control.application.chains.service import ManifestStructureService
from mission_control.domain.authoring.manifest_lowering import output_promises
from mission_control.domain.authoring.manifest_v2 import parse_manifest_yaml_versioned
from mission_control.domain.authoring.mission_definition import manifest_to_definition
from mission_control.domain.outputs.contracts import Enforcement, EvaluationScope, OutputForm

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/manifests/sprint-oc-w3"
PACK = {
    "reports": [
        {"reportId": f"w3-{name}", "task": {}, "fragments": [{"id": f"frag-{name}"}]}
        for name in ("a", "b", "c")
    ]
}


def _text(name: str) -> str:
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    return raw.replace("__PACK__", json.dumps(PACK)).replace("__PRODUCER__", "producer.default")


@pytest.mark.parametrize(
    "name", ["ai-engineer.report-collection.mission.yml", "biotech.report-collection.mission.yml"]
)
def test_w3_collection_fixture_compiles_offline_with_a_goal_scoped_collection(name: str) -> None:
    text = _text(name)
    report = ManifestStructureService().compile(text)
    assert report.ok, report.blockers
    manifest, document = parse_manifest_yaml_versioned(text)
    del document
    ((pointer, block),) = tuple(manifest.mission_blocks())
    definition = manifest_to_definition(block, pointer=pointer, digest=report.manifest_digest)
    promises = output_promises(definition)
    assert promises is not None
    reports = promises.obligation("root.reports")
    note = promises.obligation("root.progress_note")
    assert reports is not None and note is not None
    assert reports.contract.form is OutputForm.REFERENCE
    assert reports.enforcement is Enforcement.REQUIRED
    assert reports.evaluation_scope is EvaluationScope.GOAL
    assert (reports.cardinality.min, reports.cardinality.max) == (3, 3)
    assert [item.validator for item in reports.contract.requirements] == [
        "knowledge.report.assess@1"
    ]
    assert note.evaluation_scope is EvaluationScope.ITERATION
    assert block.environment.governors.iterations >= 3  # type: ignore[union-attr]
