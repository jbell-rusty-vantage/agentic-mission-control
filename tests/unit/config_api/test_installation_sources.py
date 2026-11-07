"""OC-R4 review B2/S1/S2/S3: one source per installation setting, typed failures, no silent default.

The API derives its Temporal queues from the installation (`TemporalDeployment.queue_base`), as
the worker does; a selected `MISSION_CONTROL_APPLICATION` must be the composed binding's; a
missing queue or capability resource owner fails with `InstallationDefaultUnavailable`; the
workspace root resolves through `Settings` (`.env` applies) and a bogus application id does not
break importing the settings module; a binding's hosted widening may not exceed the profile
ceiling; an unknown payload layout is refused when the profile loads.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import SecretStr, ValidationError

from mission_control.adapters.auth.jwt import ApplicationAuthentication
from mission_control.application.installations.registry import ApplicationBinding
from mission_control.bootstrap.api import (
    ApplicationDeployment,
    MissionDeployment,
    TaskQueueConventionError,
    TemporalDeployment,
    require_queue_agreement,
    verify_deployment_selection,
)
from mission_control.bootstrap.application_profiles import (
    ApplicationProfileError,
    ApplicationSelectionMismatch,
    load_application_file,
    load_application_profile,
    require_hosted_widening_within_ceiling,
    require_selected_application,
)
from mission_control.bootstrap.settings import (
    PROJECT_ROOT,
    InstallationDefaultUnavailable,
    Settings,
)
from mission_control.domain.execution.data_class import (
    DEFAULT_DATA_CLASS_POLICY,
    application_policy,
)
from tests.fixtures.isolated_settings import isolated_settings

ROOT = Path(__file__).resolve().parents[3]
DEPLOYMENTS = ROOT / "deployments"


def _temporal(stagegraph: str, goal_directed: str) -> TemporalDeployment:
    return TemporalDeployment(
        address="127.0.0.1:7233",
        namespace="default",
        root_task_queue="root",
        stagegraph_task_queue=stagegraph,
        goal_directed_task_queue=goal_directed,
    )


def _deployment(application_id: str, temporal: TemporalDeployment | None) -> MissionDeployment:
    binding = ApplicationBinding.seal(
        application_id=application_id,
        installation_id=UUID("00000000-0000-7000-8000-000000000001"),
        binding_version="v1",
        supabase_project_ref="project",
        database_secret_ref="MC_BIOTECH_DB_RUNTIME_DSN",
        accepted_issuers={"https://issuer.invalid"},
        accepted_audiences={"aud"},
        required_component_version="1.7.0",
    )
    authentication = ApplicationAuthentication(
        binding=binding,
        issuer="https://issuer.invalid",
        audience="aud",
        public_jwks_file=Path("unused-jwks.json"),
        grants=(),
    )
    return MissionDeployment(
        storage_mode="production_common",
        applications=(ApplicationDeployment(authentication=authentication, temporal=temporal),),
        max_request_bytes=1_000,
    )


# --- B2: the API's queue source is the installation's ------------------------------------------


def test_the_queue_base_is_the_installations_family_convention() -> None:
    good = _temporal("base-coordinator-family-stagegraph", "base-coordinator-family-goal-directed")
    assert good.queue_base == "base"
    with pytest.raises(TaskQueueConventionError, match="qualified family queue convention"):
        _ = _temporal("stage", "base-coordinator-family-goal-directed").queue_base
    with pytest.raises(TaskQueueConventionError, match="do not share"):
        _ = _temporal("base-coordinator-family-stagegraph", "other").queue_base


def test_api_startup_refuses_a_foreign_selection_or_an_unconventional_queue() -> None:
    temporal = _temporal(
        "base-coordinator-family-stagegraph", "base-coordinator-family-goal-directed"
    )
    deployment = _deployment("biotech", temporal)
    verify_deployment_selection(deployment, None)
    verify_deployment_selection(deployment, "biotech")
    with pytest.raises(ApplicationSelectionMismatch, match="composes the Application Binding"):
        verify_deployment_selection(deployment, "ai-engineer")
    with pytest.raises(TaskQueueConventionError):
        verify_deployment_selection(_deployment("biotech", _temporal("stage", "goal")), "biotech")


def test_the_selected_application_must_be_the_bindings() -> None:
    require_selected_application(None, "biotech")
    require_selected_application("biotech", "biotech")
    with pytest.raises(ApplicationSelectionMismatch):
        require_selected_application("ai-engineer", "biotech")


def test_a_settings_queue_must_agree_with_the_installation() -> None:
    """Re-review 3: both sources in one process agree, or startup refuses typed."""

    deployment = _deployment(
        "biotech",
        _temporal("base-coordinator-family-stagegraph", "base-coordinator-family-goal-directed"),
    )
    verify_deployment_selection(deployment, None, "base")
    verify_deployment_selection(deployment, None, None)
    with pytest.raises(TaskQueueConventionError, match="installation's queue base is base"):
        verify_deployment_selection(deployment, None, "biotech-research-ingestion")
    require_queue_agreement("base", None)
    with pytest.raises(TaskQueueConventionError):
        require_queue_agreement("base", "other")


def test_worker_readiness_refuses_typed_without_a_capability_owner() -> None:
    """Re-review 1: the startup path raises `InstallationUnavailable` with preflight's remedy."""

    from mission_control.application.installations.registry import InstallationUnavailable
    from mission_control.bootstrap.worker import verify_startup_readiness

    settings = isolated_settings()
    assert settings.capability_pins_path.is_file()
    with pytest.raises(InstallationUnavailable) as refused:
        verify_startup_readiness(settings)
    assert str(refused.value).startswith("worker startup refused by readiness: ")
    assert "set MISSION_CONTROL_WORKSPACE_ROOT, or MISSION_CONTROL_APPLICATION" in str(
        refused.value
    )


def test_no_queue_and_no_workspace_root_fail_typed_instead_of_defaulting() -> None:
    settings = isolated_settings()

    assert settings.temporal_task_queue is None
    assert settings.mission_control_workspace_root is None
    with pytest.raises(InstallationDefaultUnavailable, match="TEMPORAL_TASK_QUEUE"):
        _ = settings.task_queue_base
    with pytest.raises(InstallationDefaultUnavailable, match="MISSION_CONTROL_WORKSPACE_ROOT"):
        _ = settings.workspace_root
    selected = isolated_settings(mission_control_application="biotech")
    assert selected.task_queue_base == "biotech-research-ingestion"
    assert selected.workspace_root == (PROJECT_ROOT / "../../biotech").resolve()


# --- S3: the workspace root resolves through Settings ------------------------------------------


def test_the_workspace_root_reads_the_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("MISSION_CONTROL_WORKSPACE_ROOT", "MISSION_CONTROL_APPLICATION"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(f"MISSION_CONTROL_WORKSPACE_ROOT={tmp_path / 'assets'}\n", "utf-8")

    settings = Settings(_env_file=env_file, mc_local_db_runtime_dsn=SecretStr("x"))  # type: ignore[call-arg]

    assert settings.workspace_root == (tmp_path / "assets").resolve()
    tools = settings.workspace_root / ".tools"
    assert settings.web_research_tavily_mcp_module == (
        tools / "node_modules" / "tavily-mcp" / "build" / "index.js"
    )


def test_a_bogus_application_does_not_break_importing_the_settings() -> None:
    environment = {**os.environ, "MISSION_CONTROL_APPLICATION": "no-such-application"}
    environment.pop("MISSION_CONTROL_WORKSPACE_ROOT", None)
    imported = subprocess.run(
        [sys.executable, "-c", "import mission_control.bootstrap.settings"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr
    with pytest.raises(ValidationError, match="no Application Profile at"):
        isolated_settings(mission_control_application="no-such-application")


# --- S1: one ceiling --------------------------------------------------------------------------


def test_hosted_widening_may_not_exceed_the_profile_ceiling() -> None:
    profile = load_application_profile(DEPLOYMENTS, "biotech").profile
    assert profile.data_class_ceiling == "internal"

    require_hosted_widening_within_ceiling(profile, DEFAULT_DATA_CLASS_POLICY)
    widened = application_policy({"claude_managed": {"confidential"}})
    with pytest.raises(ApplicationProfileError, match="claude_managed admits confidential"):
        require_hosted_widening_within_ceiling(profile, widened)
    raised = profile.model_copy(update={"data_class_ceiling": "confidential"})
    require_hosted_widening_within_ceiling(raised, widened)


# --- S2: the payload layout is validated at load -----------------------------------------------


def test_an_unknown_payload_layout_is_refused_when_the_profile_loads(tmp_path: Path) -> None:
    source = (DEPLOYMENTS / "biotech" / "application.toml").read_text(encoding="utf-8")
    copied = tmp_path / "biotech" / "application.toml"
    copied.parent.mkdir()
    copied.write_text(
        source.replace(
            "mc.knowledge_apply_payload.intent_envelope.v1", "mc.knowledge_apply_payload.nope.v1"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ApplicationProfileError, match="which this host does not build"):
        load_application_file(copied)
