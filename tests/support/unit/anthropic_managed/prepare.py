"""Builders, constants and fakes that other test files import.

Moved from tests/unit/anthropic_managed/test_prepare.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from mission_control.adapters.anthropic_managed.prepare import ClaudeManagedPrepare
from mission_control.adapters.secrets.sources import WorkerEnvironmentSource
from mission_control.application.secrets.broker import SecretBroker
from tests.fixtures.managed_agents import FakeManagedAgentsApi

REPO_ROOT: Final = Path(__file__).resolve().parents[4]
AI_ENGINEER_PACK: Final = REPO_ROOT / "deployments/hosted-packs/ai-engineer/claude_managed"
FIRECRAWL_VALUE: Final = "fc-test-value-0123456789"


def prepare(
    api: FakeManagedAgentsApi,
    *,
    secrets: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
    installation_id: str = "local",
    broker: SecretBroker | None = None,
) -> ClaudeManagedPrepare:
    environment = {"FIRECRAWL_API_KEY": FIRECRAWL_VALUE} if secrets is None else secrets
    return ClaudeManagedPrepare(
        api.client(),
        broker or SecretBroker(environment=WorkerEnvironmentSource(environment)),
        installation_id=installation_id,
        labels=labels,
    )
