"""Allowlisted environments for local provider child processes (MO-04; SPEC-01 §4, gap G12).

Every local provider child (the Claude Code CLI, `codex app-server`, the Cursor SDK bridge)
starts from an empty environment. `provider_child_environment` copies from the worker only:

* `INHERITED_NAMES`: the platform, locale, proxy and TLS-root names a process needs; never a
  credential;
* the admitted auth route's credential variable (`credential_ref = env:NAME`); a login route,
  or a credential the lane delivers outside the environment, contributes none;
* `declared` names: what the provider process is declared to read. Today that is the
  variables the projected MCP configuration references (`HostProjection.environment_names`)
  plus the lane's own location variables; Environment Kit variables and secrets join here.

It then sets the lane's explicit `extra` values (`CODEX_HOME`, a relocated
`CLAUDE_CONFIG_DIR`; values the Secret Broker resolves for the process-environment channel).
Nothing else reaches the child. A name the admission asked to unset (`AuthAdmission.env_unset`)
is never copied, and declaring or setting one is refused, so nothing shadows the admitted
route. Names compare case-insensitively, as Windows environments do.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final, Protocol

from mission_control.application.execution.auth_admission import LOGIN_ROUTES, AuthAdmission

# Names every provider child may inherit from the worker (never a credential).
INHERITED_NAMES: Final[frozenset[str]] = frozenset(
    {
        "PATH",
        "HOME",
        "USERPROFILE",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "SHELL",
        "USER",
        "LOGNAME",
        "TZ",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
    }
)


class ChildEnvironmentBuilder(Protocol):
    """`provider_child_environment` or a stand-in a composition injects into a lane."""

    def __call__(
        self,
        environ: Mapping[str, str],
        admission: AuthAdmission | None,
        *,
        declared: Iterable[str] = (),
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]: ...


def admitted_credential_name(admission: AuthAdmission) -> str | None:
    """The one environment variable the admitted route reads (None on a login route or a
    credential that is not an `env:` reference)."""

    if admission.route in LOGIN_ROUTES or admission.credential_ref is None:
        return None
    scheme, _, name = admission.credential_ref.partition(":")
    return name.upper() if scheme == "env" and name else None


def provider_child_environment(
    environ: Mapping[str, str],
    admission: AuthAdmission | None,
    *,
    declared: Iterable[str] = (),
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The explicit environment of a provider child process: the allowlisted names copied from
    `environ`, then `extra`. `admission` is None when the lane's credential travels outside the
    environment (Cursor passes its key in agent options)."""

    unset = frozenset(name.upper() for name in admission.env_unset) if admission else frozenset()
    allowed = set(INHERITED_NAMES)
    credential = admitted_credential_name(admission) if admission else None
    if credential is not None:
        allowed.add(credential)
    for name in (*declared, *(extra or {})):
        if name.upper() in unset:
            raise ValueError(f"child environment may not re-introduce {name}")
    allowed.update(name.upper() for name in declared)
    child = {
        name: value
        for name, value in environ.items()
        if name.upper() in allowed and name.upper() not in unset
    }
    child.update(extra or {})
    return child


__all__ = [
    "INHERITED_NAMES",
    "ChildEnvironmentBuilder",
    "admitted_credential_name",
    "provider_child_environment",
]
