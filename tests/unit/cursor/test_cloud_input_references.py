"""Large/sensitive input bytes never enter a cloud branch and runtime downloads verify."""

import json
from pathlib import Path
from types import ModuleType

import pytest

from mission_control.adapters.cursor.workspace import git
from mission_control.application.agentic_components.placement import LaneProjectionError
from mission_control.application.workspaces.cloud_branches import (
    FETCH_SCRIPT,
    MAX_COMMITTED_INPUT_BYTES,
    REMOTE_INPUT_MANIFEST,
    cloud_packet,
    mission_branch,
    runtime_input_urls,
)
from mission_control.domain.context.render import bytes_digest
from mission_control.domain.execution.contracts import WorkspaceOwner, WorkspaceSlotBinding
from tests.fixtures.cursor_cloud import cloud_stack
from tests.fixtures.cursor_controls import StaticInputs, started_session
from tests.fixtures.lane_turns import cursor_operation


class SignedInputs(StaticInputs):
    async def runtime_url(self, durable_ref: str) -> str:
        return "https://objects.invalid/read?signature=runtime-only"


def input_workspace(operation, content: bytes, *, sensitive: bool = False):  # type: ignore[no-untyped-def]
    owner = WorkspaceOwner(kind="run", owner_id=operation.identity.run_id)
    existing = operation.workspace.slot_bindings or tuple(
        WorkspaceSlotBinding(
            slot_name=f"output-{index}", logical_path=path, access="exclusive_write", owner=owner
        )
        for index, path in enumerate(operation.workspace.exclusive_write_paths)
    )
    return operation.workspace.model_copy(
        update={
            "workflow_contract_digest": "sha256:" + "1" * 64,
            "slot_bindings": (
                *existing,
                WorkspaceSlotBinding(
                    slot_name="ctx-source",
                    logical_path="/inputs/source.bin",
                    access="read_only",
                    owner=WorkspaceOwner(kind="run", owner_id=operation.identity.run_id),
                    durable_ref="artifact://source",
                    content_digest=bytes_digest(content),
                    sensitive=sensitive,
                ),
            ),
        }
    )


@pytest.mark.parametrize(
    ("size", "sensitive", "external"),
    [
        (MAX_COMMITTED_INPUT_BYTES, False, False),
        (MAX_COMMITTED_INPUT_BYTES + 1, False, True),
        (10, True, True),
    ],
)
async def test_threshold_and_classification_control_branch_input_delivery(
    size: int, sensitive: bool, external: bool
) -> None:
    content = b"x" * size
    operation = cursor_operation("cursor_cloud")
    operation = operation.model_copy(
        update={"workspace": input_workspace(operation, content, sensitive=sensitive)}
    )
    packet = await cloud_packet(operation, SignedInputs({"artifact://source": content}))
    assert ("inputs/source.bin" in dict(packet.files)) is not external
    assert bool(packet.remote) is external
    assert (REMOTE_INPUT_MANIFEST in dict(packet.files)) is external
    if external:
        assert "runtime-only" not in repr(packet.files)
        assert json.loads(await runtime_input_urls(packet, SignedInputs({})))
        with pytest.raises(LaneProjectionError, match="runtime signed-URL delivery"):
            await runtime_input_urls(packet, StaticInputs({}))


async def test_real_branch_excludes_bytes_and_launch_delivers_urls_only_in_env(
    tmp_path: Path,
) -> None:
    content = b"private input bytes" * 20000
    original = cursor_operation("cursor_cloud")
    workspace = input_workspace(original, content, sensitive=True)
    stack = cloud_stack(
        tmp_path,
        cloud_changes={"client_agent_id": False},
        inputs=SignedInputs({"artifact://source": content}),
        operation_changes={"workspace": workspace},
    )
    _, handle = await started_session(stack)
    branch = mission_branch(stack.operation.identity.run_id, stack.operation.identity.operation_id)
    assert "inputs/source.bin" not in git("ls-tree", "-r", "--name-only", branch, cwd=stack.remote)
    manifest = json.loads(git("show", f"{branch}:{REMOTE_INPUT_MANIFEST}", cwd=stack.remote))
    assert manifest["inputs"][0]["content_digest"] == bytes_digest(content)
    assert "runtime-only" not in git("show", f"{branch}:{REMOTE_INPUT_MANIFEST}", cwd=stack.remote)
    assert "MC_INPUT_URLS" in stack.api.creates[0]["envVars"]
    assert "fetch-inputs.py" in stack.api.creates[0]["prompt"]["text"]
    assert handle.native_session_ref
    await stack.client.aclose()


def test_download_verifies_before_installing_and_refuses_traversal(tmp_path: Path) -> None:
    module = ModuleType("fetch_inputs")
    exec(compile(FETCH_SCRIPT, "fetch-inputs.py", "exec"), module.__dict__)  # noqa: S102
    digest = bytes_digest(b"valid")
    manifest = {"inputs": [{"path": "inputs/file", "content_digest": digest, "bytes": 5}]}
    path = tmp_path / REMOTE_INPUT_MANIFEST
    path.parent.mkdir()
    path.write_text(json.dumps(manifest))
    urls = {digest: "https://objects.invalid/read"}
    with pytest.raises(ValueError, match="sealed digest"):
        module.fetch(tmp_path, urls, lambda url, limit: b"other")
    assert not (tmp_path / "inputs/file").exists()
    module.fetch(tmp_path, urls, lambda url, limit: b"valid")
    assert (tmp_path / "inputs/file").read_bytes() == b"valid"
    manifest["inputs"][0]["path"] = "../escape"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unsafe input path"):
        module.fetch(tmp_path, urls, lambda url, limit: b"valid")


def test_unit_branches_do_not_collide_when_normalized_or_truncated() -> None:
    assert mission_branch("run", "member:1") != mission_branch("run", "member/1")
    assert mission_branch("run", "x" * 100 + "a") != mission_branch("run", "x" * 100 + "b")


def test_cloud_branch_remains_inside_the_runs_write_grant_and_bounds_ref_length() -> None:
    from mission_control.application.effects.mission_branches import is_mission_branch

    run = "9afb58e3-d240-5074-bb53-05e38e66af7d"
    branch = mission_branch(run, "execution-epoch-1-stage-implement-" * 20)
    assert is_mission_branch(branch, run)
    assert not is_mission_branch(branch, "another-run")
    assert len(branch) <= 80
