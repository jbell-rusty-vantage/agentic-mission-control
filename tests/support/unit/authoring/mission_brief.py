"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_mission_brief.py.
"""

from __future__ import annotations

import json
from typing import Any

from mission_control.application.guide.mission_templates import load_template
from mission_control.domain.authoring.manifest import load_manifest_yaml
from tests.unit.guide.support import SANDBOXES

APPLICATION = "ai-engineer"
BRIEF: dict[str, Any] = {
    "purpose": "system",
    "request": "Show me that a first mission runs end to end here.",
    "answers": [
        {"question": "What should the text be about?", "answer": "What a Mission Manifest is."},
        {"question": "Who reviews it?", "answer": "I do, the same day."},
    ],
    "done_means": "I read three clear sentences and approve them.",
    "out_of_scope": ["No web research."],
}


def document(brief: dict[str, Any] | None = BRIEF) -> dict[str, Any]:
    """The `smallest` template with its examples, and this brief (or none)."""

    template = load_template("smallest")
    values = template.examples() | {
        "application_id": APPLICATION,
        "sandbox_profile": next(iter(SANDBOXES)),
    }
    loaded = load_manifest_yaml(template.fill(values))
    if brief is None:
        del loaded["mission"]["brief"]
    else:
        loaded["mission"]["brief"] = json.loads(json.dumps(brief))
    return loaded
