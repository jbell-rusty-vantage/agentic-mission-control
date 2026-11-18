"""Builders, constants and fakes that other test files import.

Moved from tests/unit/prerequisites/test_preflight.py.
"""

from __future__ import annotations

from mission_control.domain.authoring.manifest import Lane, load_manifest_yaml
from mission_control.domain.authoring.manifest_v2 import parse_manifest_any
from mission_control.domain.authoring.mission_definition import manifest_to_definitions
from tests.support.manifests.compile import MINIMAL


def definition(lane="claude_managed"):
    document = load_manifest_yaml(MINIMAL.read_text(encoding="utf-8"))
    manifest = parse_manifest_any(document)
    original = manifest_to_definitions(manifest, document)[0]

    def change(node):
        return node.model_copy(
            update={
                "lane": Lane(lane),
                "environment": node.environment.model_copy(update={"lane": Lane(lane)}),
                "nodes": tuple(change(child) for child in node.nodes),
            }
        )

    return original.model_copy(update={"program": change(original.program)})
