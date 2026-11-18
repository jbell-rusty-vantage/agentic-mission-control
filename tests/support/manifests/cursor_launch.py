"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_manifest_cursor_launch.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from tests.support.manifests.v2_launch import EXAMPLES

ROOT = Path(__file__).resolve().parents[3]


LOCAL = EXAMPLES / "cursor-local.stage-graph.mission.yml"
CLOUD = EXAMPLES / "cursor-cloud.goal-loop.mission.yml"


def seeds_publish_module() -> Any:
    """``scripts/seeds_publish_bundles.py`` (FT-A7 custody upload of the agent-skill seeds)."""

    spec = importlib.util.spec_from_file_location(
        "mo31_publish", ROOT / "scripts" / "seeds_publish_bundles.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
