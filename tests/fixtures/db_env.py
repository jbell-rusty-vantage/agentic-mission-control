"""The plane-qualified database variable names a fixture sets for a given application."""

from __future__ import annotations

_PLANES = {"ai-engineer": "AIENG", "biotech": "BIOTECH"}


def db_env_name(application_id: str, role: str) -> str:
    """``MC_<PLANE>_DB_<ROLE>`` for ``application_id`` (``RUNTIME_DSN``, ``ADMIN_DSN``, ...)."""

    return f"MC_{_PLANES[application_id]}_DB_{role}"
