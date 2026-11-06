"""Application Profiles from `deployments/<app>/application.toml` (ADR-0063, OC-R4 / OVE-198).

An installation serves one application; its application id selects its profile file under the
deployments root (``MISSION_CONTROL_DEPLOYMENTS_ROOT``, default
``<MISSION_CONTROL_HOME>/deployments``).
Nothing is discovered: a caller names the application ids it composes, and a missing or invalid
file fails closed. The file carries the profile (`mc.application_profile.v1`, validated by
:class:`ApplicationProfile` and by `ApplicationRegistry.register`) plus one `[installation]` table
of operator defaults the settings fall back to when the environment sets none (the task queue, the
LangSmith projects and the capability resource owner, which left `bootstrap/settings.py`).

Stdlib and domain types only: `bootstrap/settings.py` reads the `[installation]` table at import,
so this module must not import the settings.
"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mission_control.domain.execution.data_class import DATA_CLASSES, DataClassPolicy
from mission_control.domain.resolution.profiles import ApplicationProfile

if TYPE_CHECKING:
    from mission_control.application.resolution.registries import ApplicationRegistry

PROFILE_FILE: Final = "application.toml"
DEPLOYMENTS_ROOT_ENV: Final = "MISSION_CONTROL_DEPLOYMENTS_ROOT"
_LOG = logging.getLogger(__name__)
# The installation's application id: it selects the profile whose `[installation]` defaults the
# settings use (`Settings.mission_control_application`).
APPLICATION_ENV: Final = "MISSION_CONTROL_APPLICATION"
INSTALLATION_TABLE: Final = "installation"


class ApplicationProfileError(ValueError):
    """An application has no readable, valid profile file (fail closed; names no secret)."""


class ApplicationSelectionMismatch(ValueError):
    """`MISSION_CONTROL_APPLICATION` names another application than the composing binding."""


def require_selected_application(selected: str | None, binding_application_id: str) -> None:
    """Startup assertion (OC-R4 review B2): a selected application is the binding's own, so
    the settings defaults and the binding never come from two different applications."""

    if selected is not None and selected != binding_application_id:
        raise ApplicationSelectionMismatch(
            f"MISSION_CONTROL_APPLICATION is {selected}, but this process composes the "
            f"Application Binding of {binding_application_id}"
        )


class InstallationDefaults(BaseModel):
    """The `[installation]` table: operator defaults, each overridden by its environment
    variable."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    temporal_task_queue: str | None = Field(default=None, min_length=1)
    langsmith_project: str | None = Field(default=None, min_length=1)
    agent_server_langsmith_project: str | None = Field(default=None, min_length=1)
    # Relative to MISSION_CONTROL_HOME, or absolute.
    capability_workspace_root: str | None = Field(default=None, min_length=1)


class ApplicationFile(BaseModel):
    """One parsed `application.toml`: the profile and its installation defaults."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: Path
    profile: ApplicationProfile
    installation: InstallationDefaults


def deployments_root(project_root: Path, configured: Path | str | None = None) -> Path:
    """The configured deployments root, else ``<project_root>/deployments``."""

    value = configured if configured is not None else os.environ.get(DEPLOYMENTS_ROOT_ENV)
    return Path(value).resolve() if value else (project_root / "deployments").resolve()


def trusted_assessment_validators(root: Path, application_id: str | None) -> frozenset[str] | None:
    """The application's trusted-judgment validator pin (``[outputs] assessment_pin``, WI-07
    review N1). ``None`` when no application or profile is resolvable: callers then treat every
    validator as trusted (fail closed), never a guessed default pin."""

    if application_id is None:
        return None
    try:
        pin = load_application_profile(root, application_id).profile.outputs.assessment_pin
    except (OSError, ValueError):
        _LOG.warning(
            "the %s Application Profile did not load; trusted validators fail closed",
            application_id,
            exc_info=True,
        )
        return None
    return frozenset({pin})


def profile_path(root: Path, application_id: str) -> Path:
    return root / application_id / PROFILE_FILE


def load_application_file(path: Path) -> ApplicationFile:
    """Parse and validate one profile file; its `application_id` must name its directory."""

    try:
        document: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ApplicationProfileError(f"no Application Profile at {path.as_posix()}") from None
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ApplicationProfileError(
            f"unreadable Application Profile {path.as_posix()}: {error}"
        ) from None
    installation = document.pop(INSTALLATION_TABLE, {})
    try:
        profile = ApplicationProfile.model_validate(document)
        defaults = InstallationDefaults.model_validate(installation)
    except ValidationError as error:
        raise ApplicationProfileError(
            f"invalid Application Profile {path.as_posix()}: {error}"
        ) from None
    if profile.application_id != path.parent.name:
        raise ApplicationProfileError(
            f"{path.as_posix()} declares application {profile.application_id}, not "
            f"{path.parent.name}"
        )
    # OC-R4 review S2: the payload layout must be one this host builds, checked at load
    # (composition), not first at the first `knowledge.apply`. Lazy: settings import this.
    from mission_control.application.knowledge.apply_payload import APPLY_PAYLOAD_LAYOUTS

    if profile.knowledge.intent_schema_ref not in APPLY_PAYLOAD_LAYOUTS:
        raise ApplicationProfileError(
            f"{path.as_posix()} names apply payload layout "
            f"{profile.knowledge.intent_schema_ref}, which this host does not build (known: "
            f"{', '.join(sorted(APPLY_PAYLOAD_LAYOUTS))})"
        )
    charter = profile.knowledge.charter_skill
    if charter is not None and charter != charter_skill_id(profile.application_id):
        raise ApplicationProfileError(
            f"{path.as_posix()} names charter skill {charter}; application "
            f"{profile.application_id} admits only {charter_skill_id(profile.application_id)}"
        )
    return ApplicationFile(path=path, profile=profile, installation=defaults)


def charter_skill_id(application_id: str) -> str:
    """The one knowledge charter skill an application admits. The agent-skill seed admits
    ``skill.<app>-knowledge-charter`` to that application only (``agent_skills.py``
    ``APPLICATION_SKILLS``, held to this rule by its tests); the runtime image ships without the
    seed sources, so the load check is this naming rule, not a seed import."""

    return f"skill.{application_id}-knowledge-charter"


def load_application_profile(root: Path, application_id: str) -> ApplicationFile:
    return load_application_file(profile_path(root, application_id))


def installation_defaults(root: Path, application_id: str | None) -> InstallationDefaults:
    """The selected application's `[installation]` defaults; none when no application is set."""

    if not application_id:
        return InstallationDefaults()
    return load_application_profile(root, application_id).installation


def compose_application_registry(root: Path, application_ids: Iterable[str]) -> ApplicationRegistry:
    """The registry of exactly the named applications, each from its own profile file."""

    # Lazy: the settings import this module, and the registries import the harness protocol.
    from mission_control.application.resolution.registries import ApplicationRegistry

    registry = ApplicationRegistry()
    for application_id in sorted(set(application_ids)):
        loaded = load_application_profile(root, application_id)
        try:
            registry.register(loaded.profile)
        except ValueError as error:
            raise ApplicationProfileError(f"{loaded.path.as_posix()}: {error}") from None
    return registry


def require_hosted_widening_within_ceiling(
    profile: ApplicationProfile, policy: DataClassPolicy
) -> None:
    """OC-R4 review S1: the Application Binding's hosted agent API widening (HL-18,
    `installations/registry.py`) may not admit a class above the profile's Data Class ceiling.
    One ceiling governs; a binding that widens past it is refused at composition."""

    ceiling = DATA_CLASSES.index(profile.data_class_ceiling)
    beyond = sorted(
        f"{lane} admits {data_class}"
        for lane, classes in policy.admitted.items()
        for data_class in classes
        if DATA_CLASSES.index(data_class) > ceiling
    )
    if beyond:
        raise ApplicationProfileError(
            f"application {profile.application_id}'s binding widens hosted lanes past its "
            f"profile ceiling {profile.data_class_ceiling}: {', '.join(beyond)}"
        )


__all__ = [
    "APPLICATION_ENV",
    "DEPLOYMENTS_ROOT_ENV",
    "PROFILE_FILE",
    "ApplicationFile",
    "ApplicationProfileError",
    "ApplicationSelectionMismatch",
    "InstallationDefaults",
    "charter_skill_id",
    "compose_application_registry",
    "deployments_root",
    "installation_defaults",
    "load_application_file",
    "load_application_profile",
    "profile_path",
    "require_hosted_widening_within_ceiling",
    "require_selected_application",
]
