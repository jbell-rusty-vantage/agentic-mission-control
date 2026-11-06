"""Offline admission preflight for the actual held linked repair fixture."""

from mission_control.application.authoring.completion_support import completion_support_issues
from mission_control.domain.authoring.manifest import (
    load_manifest_yaml,
    parse_manifest,
    resolve_environments,
)
from mission_control.domain.authoring.mission_definition import manifest_to_definitions
from tests.acceptance.mission_control.test_overnight_linked import linked_manifest


def test_held_repair_is_explicit_subject_with_independent_required_receiver_outputs() -> None:
    document = load_manifest_yaml(
        linked_manifest({"reportId": "fixture", "fragments": []}, scenario="held-repair")
    )
    manifest = parse_manifest(document)
    assert resolve_environments(manifest, document).blockers == ()
    definitions = manifest_to_definitions(manifest, document)
    assert all(completion_support_issues(definition) == () for definition in definitions)
    source, consumer = document["missions"]
    assert source["environment"]["governors"]["iterations"] == 1
    (link,) = document["links"]
    assert link["on"] == "execution_complete"
    assert link["selector"] == "finalized_snapshot"
    assert link["receiving_purpose"] == "repair"
    consume, review = consumer["program"]["nodes"]
    promised = {item["name"]: item for item in consume["outputs"]}
    assert {"report", "progress_note", "comparison"} <= promised.keys()
    assert promised["report"]["form"] == "reference"
    assert all(
        promised[key]["enforcement"] == "required"
        for key in ("report", "progress_note", "comparison")
    )
    assert set(review["task"]["packet"]) == {
        "consume.report",
        "consume.progress_note",
        "consume.comparison",
    }
    assert consume["inputs"] == [{"name": "report", "from": "source.report", "expand": "reference"}]
