"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_completion_support.py.
"""

from mission_control.domain.authoring.manifest import parse_manifest
from mission_control.domain.authoring.mission_definition import manifest_to_definitions
from tests.support.unit.authoring.manifest_schema import minimal


def definition():
    document = minimal()
    return manifest_to_definitions(parse_manifest(document), document)[0]
