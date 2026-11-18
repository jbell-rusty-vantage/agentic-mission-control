"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_experiment_loop_fixtures.py.
"""

from __future__ import annotations

from pathlib import Path

from mission_control.application.authoring.manifest_service import ManifestCompilation
from tests.support.manifests.compile import scope, service

ROOT = Path(__file__).resolve().parents[3]
LOOP = ROOT / "tests/fixtures/manifests/experiment-loop"


FIXTURES = (
    "e1-goal-loop-report.mission.yml",
    "e2-stagegraph-fanout-join.mission.yml",
    "e3-stagegraph-route-revisit.mission.yml",
    "e4-linked-chain.mission.yml",
    "e5-nested-goal-in-graph.mission.yml",
)


# What the driver substitutes; the pack shape matters only to the model, never to compile.
PLACEHOLDERS = {"__PACK__": '{"reportId":"fixture","task":{},"fragments":[]}'}


def rendered(name: str, producer: str = "producer.fallback") -> str:
    text = (LOOP / name).read_text(encoding="utf-8")
    for key, value in PLACEHOLDERS.items():
        text = text.replace(key, value)
    return text.replace("__PRODUCER__", producer)


async def compiled(name: str, producer: str = "producer.fallback") -> ManifestCompilation:
    compile_service, _, _ = await service()
    return await compile_service.compile(rendered(name, producer), scope("ai-engineer"))
