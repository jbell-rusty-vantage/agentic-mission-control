"""MP-05 composition: deployment auth profiles, the local auth preflight and capacity bounds.

The worker composes one :class:`AuthAdmissionService` from settings. Profiles come from the
operator-reviewed ``mc.auth_profile.v1`` document; the preflight observes names, paths and
read-only status commands only (never credential values, never a login). Provider child
processes receive the allowlisted environment of
``application.execution.child_environment.provider_child_environment`` (MO-04), so a
subscription route never inherits an API key the worker holds for another lane.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path, PurePath

from pydantic import TypeAdapter, ValidationError

from mission_control.adapters.provider_auth.detection import PATH_ENV_ALLOWLIST, WorkerAuthContext
from mission_control.adapters.provider_auth.preflight import (
    LocalAuthPreflight,
    StatusRunner,
    SubprocessStatusRunner,
)
from mission_control.application.execution.auth_admission import (
    AuthAdmissionService,
    AuthProfile,
    InMemoryAuthProfileRegistry,
)
from mission_control.application.execution.usage_admission import LimitWaitPolicy
from mission_control.bootstrap.settings import Settings

_PROFILES = TypeAdapter(list[AuthProfile])

# Settings fields whose bound value a lane may read as a credential (``settings:<field>``).
_BOUND_CREDENTIAL_SETTINGS: tuple[str, ...] = (
    "openai_api_key",
    "anthropic_api_key",
    "cursor_api_key",
)


class AuthProfilesUnavailable(RuntimeError):
    """The configured profiles document is missing, unreadable or not ``mc.auth_profile.v1``."""


def load_auth_profiles(path: Path) -> dict[str, AuthProfile]:
    """The profiles of a ``{"profiles": [...]}`` document keyed by ``profile_id`` (unique)."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise AuthProfilesUnavailable(f"auth profiles document unreadable: {path}") from error
    if not isinstance(document, dict) or not isinstance(document.get("profiles"), list):
        raise AuthProfilesUnavailable(f"auth profiles document needs a 'profiles' list: {path}")
    try:
        profiles = _PROFILES.validate_python(document["profiles"])
    except ValidationError as error:
        raise AuthProfilesUnavailable(f"auth profiles document invalid: {path}: {error}") from error
    by_id: dict[str, AuthProfile] = {}
    for profile in profiles:
        if profile.profile_id in by_id:
            raise AuthProfilesUnavailable(f"duplicate auth profile id {profile.profile_id!r}")
        by_id[profile.profile_id] = profile
    return by_id


def worker_platform() -> str:
    """The platform vocabulary the detection surface uses (``linux``/``darwin``/``win32``)."""

    return (
        "darwin" if sys.platform == "darwin" else ("win32" if sys.platform == "win32" else "linux")
    )


def worker_auth_context(
    settings: Settings,
    environ: Mapping[str, str],
    *,
    home: PurePath | None = None,
    platform: str | None = None,
    project_root: PurePath | None = None,
) -> WorkerAuthContext:
    """What the preflight may see on this worker: variable names, bound-setting names and the
    locations of the vendor settings files whose key names are inspected (values never)."""

    environ = selected_auth_environment(settings, environ)
    home_path = home if home is not None else PurePath(Path.home())
    root = project_root if project_root is not None else PurePath(Path.cwd())
    # Same path flavour as `home` (tests pass POSIX paths on any host).
    claude_dir = (
        type(home_path)(environ["CLAUDE_CONFIG_DIR"])
        if environ.get("CLAUDE_CONFIG_DIR")
        else home_path / ".claude"
    )
    bound = tuple(
        name for name in _BOUND_CREDENTIAL_SETTINGS if getattr(settings, name) is not None
    )
    return WorkerAuthContext.from_environment(
        environ,
        home=home_path,
        platform=platform if platform is not None else worker_platform(),
        bound_settings=bound,
        settings_files=(
            claude_dir / "settings.json",
            root / ".claude" / "settings.json",
            root / ".claude" / "settings.local.json",
        ),
    )


def capacity_policy(settings: Settings) -> LimitWaitPolicy:
    """The finite capacity-wait bounds the operation workflow applies (1:1 with settings)."""

    return LimitWaitPolicy(
        max_waits=settings.mission_control_capacity_max_waits,
        max_total_wait_s=settings.mission_control_capacity_max_total_wait_s,
        reset_margin_s=settings.mission_control_capacity_reset_margin_s,
        fallback_backoff_s=settings.mission_control_capacity_fallback_backoff_s,
        max_backoff_s=settings.mission_control_capacity_max_backoff_s,
    )


def status_probe_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment a read-only vendor status command runs with: ``PATH``/``HOME``-class
    variables and the allow-listed location variables only; no credential variables."""

    keep = {"PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TEMP", "TMP", "LANG", "LC_ALL", "TERM"}
    keep |= PATH_ENV_ALLOWLIST
    return {name: value for name, value in environ.items() if name.upper() in keep}


def selected_auth_environment(settings: Settings, environ: Mapping[str, str]) -> dict[str, str]:
    """Make auth detection and read-only probes observe the launcher's selected home."""
    selected = dict(environ)
    if settings.mission_control_codex_home_mode == "owner":
        owner_home = settings.mission_control_codex_owner_home
        if owner_home is not None:
            selected["CODEX_HOME"] = str(owner_home)
    return selected


def compose_auth_admission(
    settings: Settings,
    *,
    environ: Mapping[str, str] | None = None,
    status_runner: StatusRunner | None = None,
    home: PurePath | None = None,
    platform: str | None = None,
    project_root: PurePath | None = None,
) -> AuthAdmissionService | None:
    """The worker's auth admission, or ``None`` when no profiles document is configured.

    The status probe is composed only when ``MISSION_CONTROL_AUTH_STATUS_PROBE`` is on (or a
    runner is injected); it runs the surface's read-only status command with a bounded timeout.
    """

    path = settings.mission_control_auth_profiles_path
    if path is None:
        return None
    env = selected_auth_environment(settings, environ if environ is not None else os.environ)
    profiles = load_auth_profiles(path)
    context = worker_auth_context(
        settings, env, home=home, platform=platform, project_root=project_root
    )
    runner = status_runner
    if runner is None and settings.mission_control_auth_status_probe:
        runner = SubprocessStatusRunner(
            status_probe_environment(env),
            timeout_s=settings.mission_control_auth_status_timeout_s,
            binaries={"codex": settings.mission_control_codex_binary},
        )
    preflight = LocalAuthPreflight(lambda _profile: context, status_runner=runner)
    return AuthAdmissionService(
        InMemoryAuthProfileRegistry(profiles),
        preflight,
        allow_unqualified_routes=settings.mission_control_allow_unqualified_auth_routes,
    )


__all__ = [
    "AuthProfilesUnavailable",
    "capacity_policy",
    "compose_auth_admission",
    "load_auth_profiles",
    "status_probe_environment",
    "worker_auth_context",
    "worker_platform",
]
