"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_trusted_judgment_postgres.py.
"""

from __future__ import annotations

from mission_control.application.knowledge.access import InvocationAccess
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.clock import Clock
from tests.support.knowledge.credentials import KNOWLEDGE_NOW
from tests.support.knowledge.gateway import origin


def access_for(db: CommonDatabase) -> InvocationAccess:
    """The database's own application (``MISSION_CONTROL_APPLICATION``: run once per app)."""

    _mc, installation, app, tenant_id = db.scope("tenant-1").split("/")
    return InvocationAccess(
        origin=origin(installation_id=installation, application_id=app, tenant_id=tenant_id),
        subject="mission-control-runtime",
        invocation_id="inv-producer",
        authenticated_at=Clock(KNOWLEDGE_NOW).now,
    )
