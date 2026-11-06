"""OVE-169: compile reports every refusal the fresh-launch acceptance check applies at start.

Start refuses authored acceptance no runtime evaluator supports (``completion_support_issues``,
``manifest_launch_inputs.py``), for the root and for each nested body's own launch. Compile now
runs the same check (``launch_acceptance_issues``) and reports the same reason at the same
pointer as ``start_blockers`` with ``startable`` false (``ok`` stays compile validity: compile
still describes such contracts), so an author never gets a clean compile that start refuses.
Every W2 and W5 fixture is compiled through the full service; the one known start refusal
(W5 graph-in-goal) is pinned.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mission_control.application.authoring.completion_support import (
    completion_support_issues,
    launch_acceptance_issues,
)
from mission_control.application.authoring.manifest_service import ManifestCompilation
from mission_control.domain.authoring.manifest import (
    canonical_manifest_bytes,
    load_manifest_yaml,
    parse_manifest,
)
from mission_control.domain.authoring.manifest_lowering import lower_mission
from mission_control.domain.authoring.mission_definition import manifest_to_definitions
from tests.unit.authoring.test_manifest_compile import scope, service

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests/fixtures/manifests"
W2 = sorted((FIXTURES / "sprint-oc-w2").glob("*.yml"))
W5 = sorted((FIXTURES / "sprint-oc-w5").glob("*.yml"))
# Known start refusal, pinned so it flips when nested criterion inheritance is decided: the
# nested Stage Graph body inherits the parent goal's human criterion and nothing inside it can
# evaluate human acceptance (fixture header).
KNOWN = {
    "ai-engineer.graph-in-goal.mission.yml",
    "biotech.graph-in-goal.mission.yml",
}


def rendered(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for key in ("__PRODUCER__", "__CONSUMER__", "__MODEL__"):
        text = text.replace(key, "producer.fallback")
    return text.replace("__PACK__", '{"task":"frozen"}')


def application(path: Path) -> str:
    return "biotech" if path.name.startswith("biotech") else "ai-engineer"


async def compiled(text: str, app: str = "ai-engineer") -> ManifestCompilation:
    compile_service, _, _ = await service()
    return await compile_service.compile(text, scope(app))


def without_review_gate(path: Path) -> str:
    document = load_manifest_yaml(rendered(path))
    program = document["mission"]["program"]
    program["nodes"] = [item for item in program["nodes"] if item["key"] != "review"]
    return canonical_manifest_bytes(document).decode("utf-8")


@pytest.mark.asyncio
async def test_compile_refuses_what_start_refuses_with_the_same_reason_and_pointer() -> None:
    """The W2 shape before this fix: human criteria owned by agent stages."""

    path = FIXTURES / "sprint-oc-w2/ai-engineer.producer-consumer.mission.yml"
    text = without_review_gate(path)
    document = load_manifest_yaml(text)
    (definition,) = manifest_to_definitions(parse_manifest(document), document)
    start = completion_support_issues(definition, lower_mission(definition).blueprint)
    assert {item.reason for item in start} == {"completion_evaluator_unavailable"}
    compilation = await compiled(text)
    assert compilation.ok and compilation.report.startable is False
    assert compilation.report.blockers == ()
    assert {
        (item.pointer, item.reason, item.message) for item in compilation.report.start_blockers
    } == {(item.pointer, item.reason, item.message) for item in start}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", W2 + W5, ids=lambda path: f"{path.parent.name}/{path.name}")
async def test_every_w2_and_w5_fixture_compiles_to_what_start_accepts(path: Path) -> None:
    compilation = await compiled(rendered(path), application(path))
    assert compilation.report.blockers == (), compilation.report.blockers
    if path.name in KNOWN:
        assert compilation.report.startable is False
        assert {(item.pointer, item.reason) for item in compilation.report.start_blockers} == {
            (
                "/mission/program/nodes/0/goals/0/criteria/0/acceptance",
                "completion_evaluator_unavailable",
            ),
        }
        return
    assert compilation.report.start_blockers == (), compilation.report.start_blockers
    assert compilation.report.startable is True
    for program in compilation.programs:
        assert launch_acceptance_issues(program.definition, program.lowered.blueprint) == ()
