"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_wi13_nested_authoring.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mission_control.domain.authoring.manifest import (
    load_manifest_yaml,
    parse_manifest,
    resolve_environments,
)
from mission_control.domain.authoring.mission_definition import (
    MissionDefinition,
    manifest_to_definitions,
)

ROOT = Path(__file__).resolve().parents[4]
W5 = ROOT / "tests/fixtures/manifests/sprint-oc-w5"
PLACEHOLDERS = {"__PACK__": '{"task":"frozen"}', "__MODEL__": "frontier.default"}


def document(name: str) -> dict[str, Any]:
    text = (W5 / name).read_text(encoding="utf-8")
    for key, value in PLACEHOLDERS.items():
        text = text.replace(key, value)
    return load_manifest_yaml(text)


def definition(doc: dict[str, Any]) -> MissionDefinition:
    manifest = parse_manifest(doc)
    structure = resolve_environments(manifest, doc)
    assert not getattr(structure, "blockers", ())
    (only,) = manifest_to_definitions(manifest, doc)
    return only
