"""OVE-169 E4: a Stage Graph program root owes no promise of its own.

Each root output is an export of exactly one stage's promise (explicit ``exports`` with
``from: <stage>.<output>``, or the one stage declaring the same name), so every promise of the
mission is submittable by some stage invocation. An unbound root output, an unknown producer, an
early export at the root and a producer with another contract refuse at compile, pointed.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from mission_control.domain.authoring.manifest import (
    ManifestRejected,
    load_manifest_yaml,
    parse_manifest,
    resolve_environments,
)
from mission_control.domain.authoring.manifest_lowering import output_promises
from mission_control.domain.authoring.mission_definition import manifest_to_definitions
from mission_control.domain.composition.chain import compile_chain
from tests.unit.authoring.test_experiment_loop_fixtures import FIXTURES, rendered

PROGRAM = "/missions/0/program"


def e4() -> dict[str, Any]:
    return load_manifest_yaml(rendered(FIXTURES[3]))


def supplier(doc: dict[str, Any]) -> dict[str, Any]:
    program: dict[str, Any] = doc["missions"][0]["program"]
    return program


def map_stage(doc: dict[str, Any]) -> dict[str, Any]:
    return next(item for item in supplier(doc)["nodes"] if item["key"] == "map")


def issues(doc: dict[str, Any]) -> list[tuple[str, str]]:
    with pytest.raises(ManifestRejected) as caught:
        manifest = parse_manifest(doc)
        blockers = getattr(resolve_environments(manifest, doc), "blockers", ())
        if blockers:
            raise ManifestRejected(blockers)
    return [(item.pointer, item.reason or "") for item in caught.value.issues]


def owners(doc: dict[str, Any]) -> dict[str, str]:
    manifest = parse_manifest(doc)
    definitions = manifest_to_definitions(manifest, doc)
    promises = output_promises(definitions[0])
    assert promises is not None
    return {item.key: item.owner_position for item in promises.obligations}


def test_an_explicit_root_export_binds_the_chain_to_the_producing_stage() -> None:
    doc = e4()
    assert owners(doc) == {"collect.notes": "collect", "map.evidence_map": "map"}
    resolution = compile_chain(parse_manifest(doc)).resolution
    assert resolution is not None
    (binding,) = resolution.links[0].bindings
    assert (binding.output_name, binding.source_position, binding.output_key) == (
        "evidence_map",
        "map",
        "map.evidence_map",
    )


def test_a_single_same_named_stage_output_binds_without_an_export() -> None:
    doc = e4()
    del supplier(doc)["exports"]
    assert owners(doc)["map.evidence_map"] == "map"
    resolution = compile_chain(parse_manifest(doc)).resolution
    assert resolution is not None
    assert resolution.links[0].bindings[0].output_key == "map.evidence_map"


def test_a_root_output_no_stage_produces_refuses_instead_of_owing_an_unsubmittable_promise() -> (
    None
):
    doc = e4()
    del supplier(doc)["exports"]
    del map_stage(doc)["outputs"]
    assert (f"{PROGRAM}/outputs/0", "root_output_unbound") in issues(doc)


def test_an_ambiguous_same_named_producer_needs_an_explicit_export() -> None:
    doc = e4()
    del supplier(doc)["exports"]
    collect = next(item for item in supplier(doc)["nodes"] if item["key"] == "collect")
    collect["outputs"].append(copy.deepcopy(map_stage(doc)["outputs"][0]))
    assert (f"{PROGRAM}/outputs/0", "root_output_unbound") in issues(doc)


def test_an_export_from_an_unknown_stage_output_refuses() -> None:
    doc = e4()
    supplier(doc)["exports"] = [{"output": "evidence_map", "from": "map.other"}]
    found = issues(doc)
    assert (f"{PROGRAM}/exports/0/from", "nested_export_unknown_source") in found
    assert (f"{PROGRAM}/outputs/0", "root_output_unbound") in found


def test_an_early_export_at_the_root_refuses() -> None:
    doc = e4()
    supplier(doc)["exports"][0]["timing"] = "early"
    assert (f"{PROGRAM}/exports/0/timing", "unsupported_graph_position") in issues(doc)


def test_a_producer_with_another_contract_refuses() -> None:
    doc = e4()
    map_stage(doc)["outputs"][0] = {
        "name": "evidence_map",
        "form": "structured",
        "schema": "claim_table@1",
    }
    assert (f"{PROGRAM}/outputs/0", "root_export_contract_mismatch") in issues(doc)
