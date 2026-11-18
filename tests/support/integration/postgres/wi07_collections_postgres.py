"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_collection_member_assessments.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mission_control.application.knowledge.access import InvocationAccess
from tests.fixtures.mission_control_common_db import CommonDatabase
from tests.support.knowledge.gateway import origin

AT = datetime(2026, 10, 28, 12, tzinfo=UTC)


def access_for(db: CommonDatabase, operation: str = "op-research-1") -> InvocationAccess:
    _mc, installation, application, tenant_id = db.scope("tenant-1").split("/")
    return InvocationAccess(
        origin=origin(
            1,
            installation_id=installation,
            application_id=application,
            tenant_id=tenant_id,
            operation_id=operation,
        ),
        subject="mission-control-runtime",
        invocation_id="inv-" + operation.replace("/", "-"),
        authenticated_at=AT,
    )
