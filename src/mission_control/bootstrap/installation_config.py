"""The installation configuration source (P1): each Application's non-secret values.

A ``mission/v2`` variable's ``value_ref: config:<key>`` names a value of this source. The
operator reviews one small JSON file for the deployment, referenced by
``Settings.mission_control_installation_config_path``, with one mapping per Application::

    {
        "schema": "mc.installation_config.v1",
        "applications": {
            "ai-engineer": {"knowledge_services.public_url": "https://knowledge.example.org"},
            "biotech": {},
        },
    }

Each Application's composition selects its own mapping; an Application the file does not list
has no values, so its keys stay compile blockers (not a fallback: nothing resolves for it).
Keys follow the ``config:`` key grammar (``CONFIG_KEY_PATTERN``); a key that looks like a
credential (``SECRET_LIKE_CONFIG_KEY_PATTERN``) is refused here, as compile admission refuses
it too: credentials belong to ``secrets[]`` and the Secret Broker, never to configuration.
Values are strings of bounded length without control characters.

Values never leave this module through an error, its context or a ``repr``: errors name the
file, a field, an Application or a key only; :meth:`InstallationConfig.value_digests` gives
the SHA-256 of each value for a caller that needs a record. No fallback exists: a configured
file that is missing or invalid raises :class:`InstallationConfigError`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from mission_control.domain.authoring.mission_environment import (
    CONFIG_KEY_PATTERN,
    is_secret_like_config_key,
)

INSTALLATION_CONFIG_SCHEMA: Final = "mc.installation_config.v1"
# The bound of an inline manifest variable value (`EnvironmentVariable.value`).
MAX_VALUE_LENGTH: Final = 4_096
MAX_ENTRIES: Final = 512
MAX_APPLICATIONS: Final = 64
APPLICATION_ID_PATTERN: Final = r"^[a-z][a-z0-9-]{0,62}$"
_FIELDS: Final = frozenset({"$comment", "schema", "applications"})
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")
_EMPTY: Final[Mapping[str, str]] = MappingProxyType({})


class InstallationConfigError(RuntimeError):
    """The configured installation configuration file is unreadable or invalid, or no
    Application can be selected from it. The message never carries a value."""


class InstallationConfigSecretLikeKey(InstallationConfigError):
    """A configuration key names a credential; only the key is reported."""

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(
            f"installation configuration key {key!r} is secret-like; configuration is "
            "non-secret, declare the credential as a manifest secret"
        )


@dataclass(frozen=True)
class InstallationConfig:
    """Every listed Application's validated non-secret values (ids and keys sorted)."""

    applications: Mapping[str, Mapping[str, str]] = field(repr=False)

    def __repr__(self) -> str:
        keys = {application: tuple(values) for application, values in self.applications.items()}
        return f"InstallationConfig(keys={keys!r})"

    def values_for(self, application_id: str) -> Mapping[str, str]:
        """The Application's values; none when the file does not list it."""

        return self.applications.get(application_id, _EMPTY)

    def value_digests(self, application_id: str) -> dict[str, str]:
        """Each of the Application's keys with the SHA-256 digest of its value."""

        values = self.values_for(application_id)
        return {key: value_digest(value) for key, value in values.items()}


def value_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _label(text: str) -> str:
    return repr(text if len(text) <= 64 else text[:64] + "...")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise InstallationConfigError(f"duplicate installation configuration key {key!r}")
        document[key] = value
    return document


def _values(source: str, application_id: str, values: object) -> Mapping[str, str]:
    where = f"{source} application {application_id!r}"
    if not isinstance(values, dict):
        raise InstallationConfigError(f"{where} must map keys to strings")
    if len(values) > MAX_ENTRIES:
        raise InstallationConfigError(f"{where} holds more than {MAX_ENTRIES} values")
    checked: dict[str, str] = {}
    for key in sorted(values):
        if not isinstance(key, str) or not re.fullmatch(CONFIG_KEY_PATTERN, key):
            raise InstallationConfigError(
                f"{where} key {_label(str(key))} does not match {CONFIG_KEY_PATTERN}"
            )
        if is_secret_like_config_key(key):
            raise InstallationConfigSecretLikeKey(key)
        value = values[key]
        if not isinstance(value, str):
            raise InstallationConfigError(f"{where} value of {key!r} must be a string")
        if len(value) > MAX_VALUE_LENGTH:
            raise InstallationConfigError(
                f"{where} value of {key!r} exceeds {MAX_VALUE_LENGTH} characters"
            )
        if _CONTROL.search(value):
            raise InstallationConfigError(f"{where} value of {key!r} has control characters")
        checked[key] = value
    return MappingProxyType(checked)


def parse_installation_config(
    document: object, *, source: str = "installation configuration"
) -> InstallationConfig:
    """Validate one ``mc.installation_config.v1`` document (already decoded JSON)."""

    if not isinstance(document, dict):
        raise InstallationConfigError(f"{source} must be a JSON object")
    unknown = sorted(str(name) for name in document if name not in _FIELDS)
    if unknown:
        raise InstallationConfigError(f"{source} has unknown fields: {', '.join(unknown)}")
    if document.get("schema") != INSTALLATION_CONFIG_SCHEMA:
        raise InstallationConfigError(f"{source} schema must be {INSTALLATION_CONFIG_SCHEMA}")
    comment = document.get("$comment")
    if comment is not None and not isinstance(comment, str):
        raise InstallationConfigError(f"{source} $comment must be a string")
    applications = document.get("applications")
    if not isinstance(applications, dict):
        raise InstallationConfigError(f"{source} applications must be an object")
    if len(applications) > MAX_APPLICATIONS:
        raise InstallationConfigError(f"{source} lists more than {MAX_APPLICATIONS} applications")
    checked: dict[str, Mapping[str, str]] = {}
    for application_id in sorted(applications):
        if not re.fullmatch(APPLICATION_ID_PATTERN, application_id):
            raise InstallationConfigError(
                f"{source} application id {_label(application_id)} does not match "
                f"{APPLICATION_ID_PATTERN}"
            )
        checked[application_id] = _values(source, application_id, applications[application_id])
    return InstallationConfig(applications=MappingProxyType(checked))


def load_installation_config(path: Path) -> InstallationConfig:
    """Load and validate the file.

    Read and decode failures are raised outside their handlers, so no exception context
    (a ``JSONDecodeError.doc`` or a ``UnicodeDecodeError.object``) carries the file content.
    """

    text: str | None = None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        text = None
    if text is None:
        raise InstallationConfigError(f"installation configuration unreadable: {path}")
    document: object = None
    failure: str | None = None
    try:
        document = json.loads(text, object_pairs_hook=_pairs)
    except json.JSONDecodeError as error:
        failure = f"line {error.lineno}, column {error.colno}"
    except (ValueError, RecursionError):
        # An integer literal beyond the conversion limit, or nesting beyond the stack.
        failure = "an unparseable literal or nesting"
    if failure is not None:
        raise InstallationConfigError(f"installation configuration is not JSON: {path} ({failure})")
    return parse_installation_config(document, source=f"installation configuration {path}")


__all__ = [
    "INSTALLATION_CONFIG_SCHEMA",
    "MAX_APPLICATIONS",
    "MAX_ENTRIES",
    "MAX_VALUE_LENGTH",
    "InstallationConfig",
    "InstallationConfigError",
    "InstallationConfigSecretLikeKey",
    "load_installation_config",
    "parse_installation_config",
    "value_digest",
]
