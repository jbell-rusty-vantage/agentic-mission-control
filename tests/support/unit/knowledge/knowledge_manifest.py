"""Builders, constants and fakes that other test files import.

Moved from tests/unit/knowledge/test_knowledge_manifest.py.
"""

from __future__ import annotations

from pathlib import Path

from tests.fixtures.mission_control_common_db import canonical_scope

ROOT = Path(__file__).resolve().parents[4]
MANIFEST = ROOT / "tests/fixtures/manifests/knowledge-tools-stage-graph.yml"


SCOPE = canonical_scope("tenant-1", "ai-engineer")
