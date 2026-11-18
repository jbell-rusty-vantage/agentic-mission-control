"""The checked-in Application Profiles as a test registry (OC-R4 / OVE-198).

Production composes exactly the installation's application (`bootstrap/application_profiles`);
tests that launch manifests of either application compose both from the same files.
"""

from __future__ import annotations

from pathlib import Path

from mission_control.application.resolution.registries import ApplicationRegistry
from mission_control.bootstrap.application_profiles import compose_application_registry

DEPLOYMENTS = Path(__file__).resolve().parents[2] / "deployments"
CHECKED_IN = tuple(sorted(path.parent.name for path in DEPLOYMENTS.glob("*/application.toml")))


def installed_applications(*application_ids: str) -> ApplicationRegistry:
    """The registry of the named checked-in profiles (all of them when none is named)."""

    return compose_application_registry(DEPLOYMENTS, application_ids or CHECKED_IN)
