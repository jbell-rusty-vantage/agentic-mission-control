"""Builders, constants and fakes that other test files import.

Moved from tests/unit/watchers/test_standard_library.py.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "standard_watchers", ROOT / "packages/mission-control-db-contract/seeds/watcher_library.py"
)


LIBRARY = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(LIBRARY)


DATA = {
    "result-marker-stop": {"matched": True},
    "ci-watch": {"conclusion": "failure"},
    "pr-merged-release-wait": {"merged": True},
    "artifact-pipeline": {"media_type": "application/pdf", "artifact_ref": "artifact://fixture"},
    "budget-guard": {"exhausted": True},
    "heartbeat-progress": {},
}
