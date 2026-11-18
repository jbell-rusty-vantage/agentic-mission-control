"""Builders, constants and fakes that other test files import.

Moved from tests/unit/openai_agents/test_prepare.py.
"""

from __future__ import annotations

from mission_control.adapters.openai_agents.prepare import CodexAgentsPreparer
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from tests.unit.openai_agents.support import FakeAgentsApi

TOKEN = "github-readonly-test-value-7f3a"
WORKER = {"MC_GITHUB_READONLY_TOKEN": TOKEN}
LABELS = {"mc_run": "run1-HL-11"}


def _preparer(api: FakeAgentsApi, worker: dict[str, str] | None = None) -> CodexAgentsPreparer:
    environment = WorkerEnvironmentSource(WORKER if worker is None else worker)
    return CodexAgentsPreparer(api.client(), environment, labels=LABELS)
