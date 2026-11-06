"""Knowledge workspaces survive compile/persistence and reach the research lease (MO-51)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindingError
from mission_control.domain.authoring.manifest_v2 import WorkspaceOutputs, WorkspaceSelectionV2
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.execution.lanes import CursorExecutionBinding
from tests.unit.authoring.test_manifest_cursor_launch import CLOUD, LOCAL
from tests.unit.authoring.test_manifest_v2_launch import bindings, compiled_ok, edited, templates_of


def knowledge(text_path: Path, *, named: bool = False) -> str:
    def change(document):  # type: ignore[no-untyped-def]
        workspace = document["mission"]["environment"]["workspace"]
        workspace.pop("repo", None)
        workspace["kind"] = "knowledge"
        workspace["outputs"] = {
            "collect": ["artifact_upload"],
            "evidence_channel": "artifact_upload",
        }
        if named:
            workspace["repo"] = {"use": "application_knowledge_repo"}

    return edited(text_path, change)


@pytest.mark.parametrize("named", [False, True])
def test_cloud_knowledge_resolves_the_application_repo_after_definition_roundtrip(
    named: bool,
) -> None:
    compiled = compiled_ok(knowledge(CLOUD, named=named))
    bound = bindings()
    repository = next(iter(bound.providers.cursor_cloud.repositories.values()))
    bound = bound.model_copy(update={"knowledge_workspace_repository": repository})
    definition = MissionDefinition.model_validate_json(compiled.definitions[0].model_dump_json())
    templates = templates_of(compiled.programs[0], definition, bound)
    cursor = [
        item for item in templates.values() if CursorExecutionBinding.carried_by(item) is not None
    ]
    assert cursor
    assert all(
        CursorExecutionBinding.carried_by(item).workspace.repo_url == repository.repo_url
        for item in cursor
    )
    assert all(item.workspace.kind == "knowledge" for item in cursor)
    assert all(item.workspace.output_evidence_channel == "artifact_upload" for item in cursor)


def test_unconfigured_application_knowledge_repository_is_a_pointed_refusal() -> None:
    compiled = compiled_ok(knowledge(CLOUD))
    with pytest.raises(
        ManifestLaunchBindingError, match="Application knowledge workspace repository"
    ):
        templates_of(compiled.programs[0], compiled.definitions[0], bindings())


def test_local_knowledge_selects_a_research_lease_without_a_code_repository() -> None:
    compiled = compiled_ok(knowledge(LOCAL))
    definition = MissionDefinition.model_validate_json(compiled.definitions[0].model_dump_json())
    templates = templates_of(compiled.programs[0], definition, bindings())
    cursor = [
        item for item in templates.values() if CursorExecutionBinding.carried_by(item) is not None
    ]
    assert cursor
    assert all(
        CursorExecutionBinding.carried_by(item).workspace.repo_url is None for item in cursor
    )
    assert all(item.workspace.kind == "knowledge" for item in cursor)


def test_artifact_inputs_use_the_existing_context_materialization_path() -> None:
    workspace = WorkspaceSelectionV2.model_validate(
        {
            "kind": "knowledge",
            "inputs": [
                {
                    "artifact": "artifact://ai-engineer/report",
                    "as": "report",
                    "expand": "materialize",
                }
            ],
        }
    )
    assert workspace.context[0].artifact == "artifact://ai-engineer/report"
    roundtrip = WorkspaceSelectionV2.model_validate(
        workspace.model_dump(mode="json", by_alias=True)
    )
    assert len(roundtrip.context) == 1
    direct = WorkspaceSelectionV2(kind="knowledge", inputs=workspace.inputs)
    assert direct.context == workspace.context


def test_output_channels_are_closed_and_evidence_channel_must_be_collected() -> None:
    with pytest.raises(ValidationError):
        WorkspaceOutputs.model_validate({"collect": ["arbitrary_write"]})
    with pytest.raises(ValidationError, match="evidence channel must be collected"):
        WorkspaceOutputs(collect=("artifact_upload",), evidence_channel="branch_commit")
