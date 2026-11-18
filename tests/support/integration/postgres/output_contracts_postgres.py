"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_output_contracts_postgres.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.application.knowledge.access import InvocationAccess
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.knowledge.gateway import origin

AT = datetime(2026, 10, 27, 12, tzinfo=UTC)


def access_for(db: CommonDatabase, tenant: str = "tenant-1", attempt: int = 1) -> InvocationAccess:
    _mc, installation, application, tenant_id = db.scope(tenant).split("/")
    return InvocationAccess(
        origin=origin(
            attempt,
            installation_id=installation,
            application_id=application,
            tenant_id=tenant_id,
        ),
        subject="mission-control-runtime",
        invocation_id=f"inv-{attempt:04d}",
        authenticated_at=AT,
    )
