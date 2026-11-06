"""Workspace Closure capture, contract and reads (OVE-204 slice 5).

Seams: `capture_closure` over the text-only `StateBackend` and a sandbox double (listing,
classification, raw-byte digests, caps, withholding, candidate links); the domain contract's
derived identity and references; the Application Profile's `[workspace]` policy; the run-bound
`closure-body://` read; the point read service's closure listing; the Docker per-slot mount.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse
from deepagents.backends.state import StateBackend
from pydantic import ValidationError

from mission_control.adapters.deep_agents.docker_sandbox import slot_host_path
from mission_control.adapters.deep_agents.workspace_closure import (
    capture_closure,
    listing_command,
    parse_listing,
    retain_until,
)
from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.frames.artifact_bodies import (
    ARTIFACT_READ_PERMISSION,
    ArtifactBodyMissing,
    ArtifactBodyTooLarge,
    GrantedArtifactBodyReader,
)
from mission_control.domain.execution.contracts import WorkspaceOwner, WorkspaceSlotBinding
from mission_control.domain.execution.workspace_closure import (
    WorkspaceClosure,
    closure_body_ref,
    closure_ref,
    parse_closure_body_ref,
    parse_closure_ref,
)
from mission_control.domain.graph_runtime.identities import QualifiedCheckpointKey
from mission_control.domain.resolution.profiles import WorkspaceClosureProfile
from tests.fixtures.workspace_closures import InMemoryWorkspaceClosures

RUN = "run-closure-1"
UNIT = "bl-unit-v1:" + "a" * 64
SCOPE = "scope-closure"
SECRET = "super-secret-token-value"
KEY = QualifiedCheckpointKey(
    checkpointer_ref_digest="sha256:" + "b" * 64,
    thread_id="thread-1",
    checkpoint_id="1f0-result",
)
OWNER = WorkspaceOwner(kind="stage", owner_id="stage-a")


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _workspace(*, sensitive: bool = False) -> Any:
    slots = (
        WorkspaceSlotBinding(
            slot_name="out", logical_path="/out", access="exclusive_write", owner=OWNER
        ),
        WorkspaceSlotBinding(
            slot_name="private",
            logical_path="/private",
            access="exclusive_write",
            owner=OWNER,
            sensitive=sensitive,
        ),
        WorkspaceSlotBinding(
            slot_name="ctx-input",
            logical_path="/inputs/brief.md",
            access="read_only",
            owner=OWNER,
            durable_ref="memory://brief",
            content_digest=_digest(b"brief"),
        ),
    )
    return SimpleNamespace(slot_bindings=slots, exclusive_write_paths=("/out", "/private"))


async def _capture(backend: Any, state: dict[str, Any], **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "run_id": RUN,
        "unit_key": UNIT,
        "execution_generation": 1,
        "harness_execution_id": None,
        "result_key": KEY,
        "boundary": "attempt_settled",
        "policy": WorkspaceClosureProfile(),
        "secret_values": (SECRET,),
        "now": datetime(2026, 10, 31, tzinfo=UTC),
    }
    workspace = overrides.pop("workspace", _workspace(sensitive=True))
    arguments.update(overrides)
    return await capture_closure(backend, workspace, state, **arguments)


def _state(files: dict[str, bytes | str]) -> dict[str, Any]:
    channel: dict[str, Any] = {}
    for path, value in files.items():
        if isinstance(value, bytes):
            channel[path] = {
                "content": base64.standard_b64encode(value).decode(),
                "encoding": "base64",
            }
        else:
            channel[path] = {"content": value, "encoding": "utf-8"}
    return {"files": channel}


@pytest.mark.asyncio
async def test_state_backend_closure_covers_the_files_channel_by_raw_bytes() -> None:
    binary = bytes(range(256))
    state = _state(
        {
            "/out/report.md": "# report\n",
            "/out/data.bin": binary,
            "/private/notes.txt": "private notes",
            "/inputs/brief.md": "brief",
            "/skills/s/SKILL.md": f"token {SECRET}",
        }
    )
    state["files"]["/deleted.txt"] = None
    captured = await _capture(
        StateBackend(),
        state,
        candidates=(
            {
                "logical_path": "/out/report.md",
                "content_digest": _digest(b"# report\n"),
                "candidate_id": "cand-1",
            },
        ),
    )
    closure: WorkspaceClosure = captured.closure
    files = {item.path: item for item in closure.files}
    assert list(files) == sorted(files) and "/deleted.txt" not in files
    assert files["/out/data.bin"].digest == _digest(binary)
    assert files["/out/data.bin"].encoding == "base64"
    assert files["/out/report.md"].candidate_id == "cand-1"
    assert files["/out/report.md"].slot == "out"
    assert files["/out/report.md"].slot_access == "exclusive_write"
    assert files["/private/notes.txt"].body_state == "withheld_sensitive"
    assert files["/inputs/brief.md"].body_state == "withheld_input"
    assert files["/skills/s/SKILL.md"].body_state == "withheld_secret"
    assert files["/skills/s/SKILL.md"].slot is None
    assert all(item.destination == "state_channel" for item in closure.files)
    promoted = [item for item in closure.files if item.body_state == "promoted"]
    assert {item.path for item in promoted} == {"/out/report.md", "/out/data.bin"}
    assert set(captured.bodies) == {item.digest for item in promoted}
    assert all(SECRET.encode() not in body for body in captured.bodies.values())
    assert closure.complete and closure.backend == "state"
    assert closure.ref == closure_ref(closure.closure_id, closure.closure_digest)
    # The result point the settlement writes is the closure's point (no FK, same id).
    assert (
        closure.point_id
        == WorkspaceClosure.model_validate(closure.model_dump(mode="json")).point_id
    )


@pytest.mark.asyncio
async def test_caps_degrade_instead_of_failing() -> None:
    state = _state({f"/out/f{index}.txt": "x" * 10 for index in range(5)})
    policy = WorkspaceClosureProfile(closure_max_files=3, closure_max_bytes=25)
    captured = await _capture(StateBackend(), state, policy=policy)
    closure = captured.closure
    assert [item.path for item in closure.files] == ["/out/f0.txt", "/out/f1.txt", "/out/f2.txt"]
    assert [item.body_state for item in closure.files] == ["promoted", "promoted", "withheld_cap"]
    assert closure.limits.applied == ("max_files", "max_bytes")
    assert closure.limits.omitted_files == 2 and not closure.complete


class FakeDockerSandbox:
    """A sandbox double: `find ... sha256sum` output and downloads from a dict."""

    def __init__(self, files: dict[str, bytes], *, corrupt: frozenset[str] = frozenset()) -> None:
        self.files = files
        self.corrupt = corrupt
        self.commands: list[str] = []
        self.downloaded: list[str] = []

    async def aexecute(self, command: str) -> ExecuteResponse:
        self.commands.append(command)
        lines = [
            f"{len(content)}\t{hashlib.sha256(content).hexdigest()}  {path}"
            for path, content in self.files.items()
        ]
        return ExecuteResponse(output="\n".join([*lines, "garbage line"]), exit_code=0)

    async def adownload_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        self.downloaded.extend(paths)
        return [
            FileDownloadResponse(
                path=path,
                content=b"tampered" if path in self.corrupt else self.files[path],
            )
            for path in paths
        ]


@pytest.mark.asyncio
async def test_sandbox_closure_lists_in_container_and_downloads_only_promoted_bodies() -> None:
    sandbox = FakeDockerSandbox(
        {
            "/out/a.txt": b"alpha",
            "/workspace/scratch.py": b"print(1)",
            "/workspace/big.bin": b"z" * 100,
            "/private/key.txt": b"k",
            "/workspace/odd.txt": b"odd",
        },
        corrupt=frozenset({"/workspace/odd.txt"}),
    )
    policy = WorkspaceClosureProfile(closure_max_bytes=50)
    captured = await _capture(sandbox, {}, policy=policy, boundary="attempt_failed")
    closure = captured.closure
    files = {item.path: item for item in closure.files}
    assert closure.backend == "docker" and closure.boundary == "attempt_failed"
    assert closure.roots == ("/out", "/private", "/workspace")
    assert files["/out/a.txt"].destination == "sandbox_writable"
    assert files["/workspace/scratch.py"].destination == "sandbox_workdir"
    assert files["/workspace/big.bin"].body_state == "withheld_cap"
    assert files["/private/key.txt"].body_state == "withheld_sensitive"
    assert files["/workspace/odd.txt"].body_state == "unreadable"
    assert files["/workspace/odd.txt"].digest == _digest(b"odd")
    assert files["/out/a.txt"].body_state == "promoted"
    assert sorted(sandbox.downloaded) == [
        "/out/a.txt",
        "/workspace/odd.txt",
        "/workspace/scratch.py",
    ]
    assert len(sandbox.commands) == 1 and "sha256sum" in sandbox.commands[0]


@pytest.mark.asyncio
async def test_an_unknown_backend_records_no_closure() -> None:
    assert await _capture(object(), {}) is None


def test_listing_command_quotes_roots_and_parses_its_output() -> None:
    command = listing_command(("/out", "/a b"))
    assert "'/a b'" in command and "find /out" in command
    hex_digest = "c" * 64
    assert parse_listing(f"12\t{hex_digest}  /out/x y.txt\nbad\n") == [
        ("/out/x y.txt", 12, "sha256:" + hex_digest)
    ]


def test_references_round_trip_and_identity_is_derived() -> None:
    digest = _digest(b"body")
    ref = closure_body_ref(digest=digest, size_bytes=4, media_type="text/plain")
    parsed = parse_closure_body_ref(ref)
    assert (parsed.digest, parsed.bytes, parsed.media_type) == (digest, 4, "text/plain")
    closure_id = "00000000-0000-0000-0000-000000000001"
    assert parse_closure_ref(closure_ref(closure_id, digest)) == (closure_id, digest)


@pytest.mark.asyncio
async def test_a_tampered_closure_is_refused() -> None:
    captured = await _capture(StateBackend(), _state({"/out/a.txt": "a"}))
    document = captured.closure.model_dump(mode="json")
    document["files"][0]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError):
        WorkspaceClosure.model_validate(document)
    document = captured.closure.model_dump(mode="json")
    document["boundary"] = "attempt_cancelled"
    with pytest.raises(ValidationError):
        WorkspaceClosure.model_validate(document)


def test_profile_retention_is_mission_or_at_least_thirty_days() -> None:
    assert WorkspaceClosureProfile().retention_days is None
    recorded = datetime(2026, 10, 31, tzinfo=UTC)
    assert retain_until(WorkspaceClosureProfile(), recorded) is None
    thirty = WorkspaceClosureProfile(closure_retention=30)
    assert retain_until(thirty, recorded) == datetime(2026, 11, 30, tzinfo=UTC)
    with pytest.raises(ValidationError):
        WorkspaceClosureProfile(closure_retention=29)
    with pytest.raises(ValidationError):
        WorkspaceClosureProfile(closure_retention="forever")  # type: ignore[arg-type]


def _actor() -> Any:
    return SimpleNamespace(permissions=frozenset({ARTIFACT_READ_PERMISSION}))


@pytest.mark.asyncio
async def test_closure_bodies_are_read_only_for_their_run() -> None:
    captured = await _capture(StateBackend(), _state({"/out/a.txt": "alpha", "/out/b.txt": "b"}))
    closures = InMemoryWorkspaceClosures()
    await closures.put(captured.closure, captured.bodies, request_scope=SCOPE, retain_until=None)
    payloads = InMemoryArtifactPayloadStore()
    for digest, content in captured.bodies.items():
        await payloads.stage(
            artifact_id="x", content=content, content_digest=digest, media_type="text/plain"
        )
    reader = GrantedArtifactBodyReader(
        SimpleNamespace(), payloads, request_scope=SCOPE, closures=closures
    )
    ref = next(item.body_ref for item in captured.closure.files if item.path == "/out/a.txt")
    assert ref is not None
    content, media_type = await reader.read_bytes(SCOPE, _actor(), ref, run_id=RUN)
    assert content == b"alpha" and media_type == "text/plain"
    with pytest.raises(ArtifactBodyMissing):
        await reader.read_bytes(SCOPE, _actor(), ref, run_id="another-run")
    with pytest.raises(ArtifactBodyMissing):
        await reader.read_bytes(SCOPE, _actor(), ref)
    small = GrantedArtifactBodyReader(
        SimpleNamespace(), payloads, request_scope=SCOPE, closures=closures, max_bytes=2
    )
    with pytest.raises(ArtifactBodyTooLarge):
        await small.read_bytes(SCOPE, _actor(), ref, run_id=RUN)


def test_docker_writable_targets_get_distinct_host_directories(tmp_path: Path) -> None:
    first, second = slot_host_path(tmp_path, "/a"), slot_host_path(tmp_path, "/b")
    assert first != second and first.parent == second.parent == tmp_path
    assert slot_host_path(tmp_path, "/a") == first
