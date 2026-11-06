"""PostgreSQL Owner Prerequisite store (migration 0038; MO-20)."""

from mission_control.adapters.postgres.prerequisites.repository import (
    PostgresOwnerPrerequisiteRepository,
)

__all__ = ["PostgresOwnerPrerequisiteRepository"]
