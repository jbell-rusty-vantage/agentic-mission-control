"""The one set of test ids: installations, tenants and canonical scopes.

A canonical scope is ``mc/{installation}/{application}/{tenant}``. The disposable common
database (``tests.fixtures.mission_control_common_db``) seeds exactly these installations
and tenants, so fixtures built from these ids join the database rows they meet.

``SCOPE``/``INSTALLATION``/``TENANT`` are the default ids for tests that need one scope
and do not care which. A test that pins different values on purpose (a recorded frame, a
golden digest) keeps its own literal next to that recording.
"""

from __future__ import annotations

from uuid import UUID, uuid5

_NAMESPACE = UUID("6d9c2f6e-6a43-4c7e-9a52-6f3b1b7f2a10")

BIOTECH_INSTALLATION_ID = UUID("0192a4f0-0000-7000-8000-00000000b10e")
AI_ENGINEER_INSTALLATION_ID = UUID("0192a4f0-0000-7000-8000-0000000a1e00")
# application id -> (installation id, the installation's disposable project reference)
INSTALLATIONS = {
    "biotech": (BIOTECH_INSTALLATION_ID, "mcdisposablebiotech"),
    "ai-engineer": (AI_ENGINEER_INSTALLATION_ID, "mcdisposableaieng"),
}


def tenant_id(name: str, application_id: str = "biotech") -> UUID:
    """Deterministic test tenant UUID; equal names in two apps intentionally collide."""
    del application_id
    return uuid5(_NAMESPACE, f"tenant:{name}")


def canonical_scope(name: str = "tenant-1", application_id: str = "biotech") -> str:
    installation_id, _ref = INSTALLATIONS[application_id]
    return f"mc/{installation_id}/{application_id}/{tenant_id(name, application_id)}"


def catalog_scope(application_id: str = "biotech") -> str:
    installation_id, _ref = INSTALLATIONS[application_id]
    return f"mc/{installation_id}/{application_id}/catalog"


INSTALLATION = BIOTECH_INSTALLATION_ID
TENANT = tenant_id("tenant-1")
SCOPE = canonical_scope("tenant-1")
OTHER_TENANT = tenant_id("tenant-2")
OTHER_SCOPE = canonical_scope("tenant-2")
