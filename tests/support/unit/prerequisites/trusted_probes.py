"""Builders, constants and fakes that other test files import.

Moved from tests/unit/prerequisites/test_trusted_probes.py.
"""

from mission_control.application.prerequisites.catalog import account_prerequisites
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.prerequisites import OwnerPrerequisiteRecord


def record_for(profile: str, code: str) -> OwnerPrerequisiteRecord:
    prerequisite = next(
        item for item in account_prerequisites(LaneProfile(profile)) if item.id.endswith("." + code)
    )
    return OwnerPrerequisiteRecord.of(prerequisite)
