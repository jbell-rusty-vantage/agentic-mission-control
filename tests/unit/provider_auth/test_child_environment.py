"""MO-04: the allowlisted environment of a local provider child process (SPEC-01 §4).

`provider_child_environment` starts from an empty environment and copies only the inherited
platform names, the admitted route's credential variable and the declared names, then sets
the lane's explicit values; a name the admission unsets can neither be copied nor
re-introduced. Every admission here is built in the test (FIXTURE); no process starts.
"""

from __future__ import annotations

import pytest

from mission_control.application.execution.auth_admission import AuthAdmission
from mission_control.application.execution.child_environment import (
    INHERITED_NAMES,
    admitted_credential_name,
    provider_child_environment,
)

WORKER = {
    "PATH": "/usr/bin",
    "HOME": "/home/worker",
    "LANG": "C.UTF-8",
    "https_proxy": "http://proxy.local:3128",
    "MISSION_CONTROL_DATABASE_URL": "postgresql://worker@db/mission_control",
    "OPENAI_API_KEY": "sk-openai-not-a-real-key",
    "ANTHROPIC_API_KEY": "sk-ant-not-a-real-key",
    "CURSOR_API_KEY": "key_cursor_not_a_real_key",
    "TAVILY_API_KEY": "tvly-not-a-real-key",
    "UNRELATED": "value",
}


def _admission(
    route: str = "owner_cli_login",
    credential_ref: str | None = None,
    env_unset: tuple[str, ...] = (),
) -> AuthAdmission:
    return AuthAdmission.model_construct(
        route=route, credential_ref=credential_ref, env_unset=env_unset
    )


def test_inherited_names_carry_no_credential() -> None:
    assert not {name for name in INHERITED_NAMES if "KEY" in name or "TOKEN" in name}
    assert {"PATH", "HOME", "HTTPS_PROXY", "SSL_CERT_FILE"} <= INHERITED_NAMES


def test_a_login_route_child_gets_the_inherited_names_only() -> None:
    child = provider_child_environment(WORKER, _admission())
    assert child == {
        "PATH": "/usr/bin",
        "HOME": "/home/worker",
        "LANG": "C.UTF-8",
        "https_proxy": "http://proxy.local:3128",
    }


@pytest.mark.parametrize(
    ("credential_ref", "expected"),
    [
        ("env:ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        ("env:anthropic_api_key", "ANTHROPIC_API_KEY"),
        ("settings:anthropic_api_key", None),
        ("keyring:anthropic", None),
    ],
)
def test_only_an_env_credential_ref_names_a_variable(
    credential_ref: str, expected: str | None
) -> None:
    admission = _admission("api_key", credential_ref)
    assert admitted_credential_name(admission) == expected
    child = provider_child_environment(WORKER, admission)
    assert set(child) - {"PATH", "HOME", "LANG", "https_proxy"} == (
        {expected} if expected else set()
    )


def test_declared_names_are_copied_when_present_and_never_invented() -> None:
    child = provider_child_environment(
        WORKER, _admission(), declared=("tavily_api_key", "FIRECRAWL_API_KEY")
    )
    assert child["TAVILY_API_KEY"] == "tvly-not-a-real-key"
    assert "FIRECRAWL_API_KEY" not in child
    assert "OPENAI_API_KEY" not in child and "MISSION_CONTROL_DATABASE_URL" not in child


def test_extra_values_are_set_last_and_need_no_worker_value() -> None:
    child = provider_child_environment(
        WORKER, None, extra={"CODEX_HOME": "/lease/.codex-home", "HOME": "/lease"}
    )
    assert child["CODEX_HOME"] == "/lease/.codex-home" and child["HOME"] == "/lease"


def test_an_unset_name_is_never_copied_nor_reintroduced() -> None:
    admission = _admission(env_unset=("ANTHROPIC_API_KEY",))
    environ = {**WORKER, "anthropic_api_key": "lower-case twin"}
    child = provider_child_environment(environ, admission, declared=("TAVILY_API_KEY",))
    assert not {name for name in child if name.upper() == "ANTHROPIC_API_KEY"}
    with pytest.raises(ValueError, match="re-introduce"):
        provider_child_environment(environ, admission, declared=("Anthropic_Api_Key",))
    with pytest.raises(ValueError, match="re-introduce"):
        provider_child_environment(environ, admission, extra={"ANTHROPIC_API_KEY": "again"})
