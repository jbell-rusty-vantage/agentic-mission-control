"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_manifest_schema.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mission_control.domain.authoring.manifest import load_manifest_yaml

ROOT = Path(__file__).resolve().parents[4]


FIXTURES = ROOT / "tests/fixtures/manifests"


def minimal() -> dict[str, Any]:
    return load_manifest_yaml((FIXTURES / "minimal-stage-graph.yml").read_text(encoding="utf-8"))
