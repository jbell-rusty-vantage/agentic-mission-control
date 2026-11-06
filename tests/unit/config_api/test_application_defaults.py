"""OC-R4: settings name no application; the selected application's profile supplies defaults.

`MISSION_CONTROL_APPLICATION` selects `deployments/<app>/application.toml`, whose
`[installation]` table fills the task queue and LangSmith projects the process does not set,
and names the capability resource owner `Settings.workspace_root` falls back to. The
environment wins.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import mission_control.bootstrap.settings as settings_module
from mission_control.bootstrap.settings import Settings
from tests.fixtures.isolated_settings import isolated_settings

DEPLOYMENTS = Path(__file__).resolve().parents[3] / "deployments"


def test_without_an_application_the_defaults_are_neutral() -> None:
    settings = isolated_settings()

    assert settings.mission_control_application is None
    assert settings.temporal_task_queue is None  # no neutral queue (review B2)
    assert settings.langsmith_project == "MissionControl"
    assert settings.agent_server_langsmith_project == "MissionControl-AgentServer-Local"
    assert "knowledge_binding_ids" not in Settings.model_fields


@pytest.mark.parametrize("application", ["ai-engineer", "biotech"])
def test_the_selected_profile_supplies_its_installation_defaults(application: str) -> None:
    settings = isolated_settings(mission_control_application=application)

    # The pre-R4 defaults, preserved in both profiles.
    assert settings.temporal_task_queue == "biotech-research-ingestion"
    assert settings.langsmith_project == "BellLabsBiotech"
    assert settings.agent_server_langsmith_project == "BellLabsBiotech-AgentServer-Local"


def test_an_explicit_setting_wins_over_the_profile() -> None:
    settings = isolated_settings(
        mission_control_application="biotech", temporal_task_queue="explicit-queue"
    )

    assert settings.temporal_task_queue == "explicit-queue"
    assert settings.langsmith_project == "BellLabsBiotech"


def test_an_application_without_a_profile_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="no Application Profile at"):
        isolated_settings(mission_control_application="unknown-app")
    with pytest.raises(ValidationError, match="no Application Profile at"):
        isolated_settings(
            mission_control_application="biotech", mission_control_deployments_root=tmp_path
        )


def test_the_deployments_root_is_configurable(tmp_path: Path) -> None:
    copied = tmp_path / "biotech" / "application.toml"
    copied.parent.mkdir()
    source = (DEPLOYMENTS / "biotech" / "application.toml").read_text(encoding="utf-8")
    copied.write_text(
        source.replace(
            'temporal_task_queue = "biotech-research-ingestion"',
            'temporal_task_queue = "copied-queue"',
        ),
        encoding="utf-8",
    )
    settings = isolated_settings(
        mission_control_application="biotech", mission_control_deployments_root=tmp_path
    )

    assert settings.deployments_root == tmp_path.resolve()
    assert settings.temporal_task_queue == "copied-queue"


def test_the_capability_workspace_root_follows_setting_then_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "platform" / "mission-control"
    target = home / "deployments" / "biotech"
    target.mkdir(parents=True)
    target.joinpath("application.toml").write_text(
        (DEPLOYMENTS / "biotech" / "application.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_module, "PROJECT_ROOT", home)
    monkeypatch.delenv("MISSION_CONTROL_DEPLOYMENTS_ROOT", raising=False)

    selected = isolated_settings(mission_control_application="biotech")
    assert selected.workspace_root == (tmp_path / "biotech").resolve()
    explicit = isolated_settings(
        mission_control_application="biotech", mission_control_workspace_root=tmp_path / "assets"
    )
    assert explicit.workspace_root == (tmp_path / "assets").resolve()
