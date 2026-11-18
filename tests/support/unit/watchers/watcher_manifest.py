"""Builders, constants and fakes that other test files import.

Moved from tests/unit/watchers/test_watcher_manifest.py.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from mission_control.domain.authoring.manifest import load_manifest_yaml
from mission_control.domain.authoring.manifest_v2 import parse_manifest_any
from mission_control.domain.authoring.mission_definition import (
    MissionDefinition,
    manifest_to_definitions,
)

ROOT = Path(__file__).resolve().parents[4]
MINIMAL = ROOT / "tests/fixtures/manifests/minimal-stage-graph.yml"


def v1() -> dict[str, Any]:
    return load_manifest_yaml(MINIMAL.read_text(encoding="utf-8"))


def v2(**controls: Any) -> dict[str, Any]:
    document = copy.deepcopy(v1())
    document["manifest"] = "mission/v2"
    document["mission"]["controls"].update(controls)
    return document


def definition(document: dict[str, Any]) -> MissionDefinition:
    (item,) = manifest_to_definitions(parse_manifest_any(document), document)
    return item


def event_wait_document(**node: Any) -> dict[str, Any]:
    document = v2()
    nodes = document["mission"]["program"]["nodes"]
    nodes.insert(
        1,
        {
            "key": "await-merge",
            "behavior": "event_wait",
            "event_type": "github.pull_request.merged",
            "match": {"base": "main", "merged": True},
            **node,
        },
    )
    nodes[2]["depends_on"] = ["collect", "await-merge"]
    return document
