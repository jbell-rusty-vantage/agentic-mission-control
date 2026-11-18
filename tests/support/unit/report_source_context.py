"""Builders, constants and fakes that other test files import.

Moved from tests/unit/test_report_source_context.py.
"""

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "report_source_context",
    Path(__file__).resolve().parents[3] / "scripts/report_source_context.py",
)


context = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(context)
