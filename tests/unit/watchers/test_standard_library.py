"""MO46: each published template has a compilable manifest and bounded firing proof."""

import runpy

import pytest

from mission_control.domain.authoring.manifest import load_manifest_yaml
from mission_control.domain.programs.watchers import compile_watcher, wait_condition_id
from tests.support.unit.watchers.standard_library import DATA, LIBRARY, ROOT
from tests.support.unit.watchers.watcher_manifest import definition
from tests.support.unit.watchers.watcher_planner import plan, signal
from tests.unit.watchers.fakes import T0, at


@pytest.mark.parametrize("entry", LIBRARY.definitions(), ids=lambda entry: entry.logical_id)
def test_template_example_compiles_and_source_fires_once(entry):
    name = entry.logical_id.removeprefix("watcher.")
    document = load_manifest_yaml(
        (ROOT / f"tests/fixtures/manifests/watchers/{name}.yml").read_text("utf-8")
    )
    compiled = definition(document).policies.watchers
    assert any(item.watcher_id == name for item in compiled)
    descriptor = compile_watcher(entry.spec, watcher_id=name, origin="catalog", pointer="/fixture")
    observations = (
        ()
        if name == "stall-detector"
        else (
            signal(
                entry.spec.on.signal,
                DATA[name],
                when=at(1200),
                ref="fixture",
                trust="provider_signed",
            ),
        )
    )
    result = plan(
        [descriptor],
        observations,
        now=at(1200),
        last_seen={"frame": T0, "signal": T0},
        waits=frozenset({wait_condition_id("await-merge")}),
    )
    assert len(result.firings) == 1
    assert descriptor.boundaries.max_fires is not None
    if name == "result-marker-stop":
        assert result.firings[0].actions[-1].spec.command.kind == "cancel"


def test_additive_seed_bytes_match_all_seven_definitions():
    generator = runpy.run_path(
        str(ROOT / "packages/mission-control-db-contract/seeds/generate_catalog_seeds.py")
    )
    expected = LIBRARY.bundles(
        lambda definition, prefix, evidence: generator["_published_definition_records"](
            definition, prefix, evidence, published_at=LIBRARY.SEED_TIME
        ),
        generator["SEED_FORMAT"],
        generator["COMPATIBILITY"],
        generator["SEED_ACTOR"],
    )
    assert len(expected) == 2
    for relative, bundle in expected.items():
        assert (
            ROOT / "packages/mission-control-db-contract/seeds" / relative
        ).read_bytes() == generator["encode"](bundle)
