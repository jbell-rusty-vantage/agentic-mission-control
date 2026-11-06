"""Cloud channel selection binds completion evidence to committed rather than provider bytes."""

from hashlib import sha256
from pathlib import Path

from mission_control.domain.context.refs import parse_workspace_candidate_ref
from tests.fixtures.cursor_cloud import cloud_stack
from tests.fixtures.lane_turns import RecordingSignals
from tests.unit.harness.test_cursor_cloud import _identity, _lanes, _turn
from tests.unit.operations.test_lane_outputs import compiled, custody


async def test_branch_channel_collects_exact_head_bytes_as_evidence(tmp_path: Path) -> None:
    workspace = compiled("/workspace/output").workspace.model_copy(
        update={
            "kind": "knowledge",
            "output_channels": ("provider_artifacts", "branch_commit"),
            "output_evidence_channel": "branch_commit",
        }
    )
    port, contents = custody()
    stack = cloud_stack(
        tmp_path, operation_changes={"workspace": workspace}, harness_changes={"outputs": port}
    )
    stack.api.record["agent_branch_commit"] = {
        "path": "outputs/report.md",
        "content": "committed evidence",
    }
    stack.api.record["artifacts"] = {"outputs/report.md": "provider evidence"}
    lanes = _lanes(stack)
    result = await lanes.service.turn(
        _turn(stack), RecordingSignals(lanes.frames, _identity(stack).harness_execution_id)
    )
    candidates = [parse_workspace_candidate_ref(ref) for ref in result.closing_facts.output_refs]
    candidates = [candidate for candidate in candidates if candidate is not None]
    assert len(candidates) == 1
    descriptor = await contents.describe(candidates[0])
    assert descriptor.content_digest == "sha256:" + sha256(b"committed evidence").hexdigest()
    assert stack.api.downloads
    await stack.client.aclose()
