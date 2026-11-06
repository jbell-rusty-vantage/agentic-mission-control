"""Head SHA artifacts: the resolved head of every mission branch (SPEC-01 section 6; MO-14).

Mission Control records which commit a mission branch pointed at, and how it learned it, as
an immutable `mc.mission_branch_head.v1` artifact in content-addressed custody:

- `local_push`: a local lane's lease branch pushed by Mission Control and read back from the
  remote;
- `branch_lookup`: a provider-hosted branch (Cursor cloud) read back from the remote;
- `pull_request`: the head the `repo_pr` effect's pull request points at;
- `claude_session_trailer`: the newest commit of a Claude cloud session, found by the
  `Claude-Session: <url>` trailer the provider writes on its commits.

Codex Cloud (`codex cloud diff`/apply) is a deferred lane (DECISIONS R5, R27) and has no
producer here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from mission_control.application.effects.ports import OBJECT_ID, BranchCommit
from mission_control.domain.execution.lanes import LaneProfileName

BRANCH_HEAD_SCHEMA: Final = "mc.mission_branch_head.v1"
CLAUDE_SESSION_TRAILER: Final = "Claude-Session"

BranchHeadSource = Literal["local_push", "branch_lookup", "pull_request", "claude_session_trailer"]


class HeadArtifactSink(Protocol):
    """Content-addressed custody (`SnapshotArtifacts`, a lane's artifact sink)."""

    async def stage(
        self, *, request_scope: str, name: str, content: bytes, media_type: str
    ) -> str: ...


class MissionBranchHead(BaseModel):
    """`mc.mission_branch_head.v1`: one observed head of one mission branch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.mission_branch_head.v1"] = BRANCH_HEAD_SCHEMA
    run_id: str = Field(min_length=1)
    lane_profile: LaneProfileName
    repository: str = Field(min_length=1)
    branch: str = Field(min_length=1, max_length=256)
    head_sha: str = Field(pattern=OBJECT_ID)
    source: BranchHeadSource
    session_ref: str | None = Field(default=None, min_length=1, max_length=2_048)
    pull_request_url: str | None = Field(default=None, min_length=1, max_length=2_048)
    observed_at: AwareDatetime

    def encoded(self) -> bytes:
        return self.model_dump_json().encode("utf-8")


async def record_branch_head(
    artifacts: HeadArtifactSink, head: MissionBranchHead, *, request_scope: str
) -> str:
    """Stage the head artifact; the returned durable ref is what receipts and manifests cite."""

    return await artifacts.stage(
        request_scope=request_scope,
        name=f"mission-branch-heads/{head.run_id}/{head.branch}@{head.head_sha}.json",
        content=head.encoded(),
        media_type="application/json",
    )


def commit_trailers(message: str) -> dict[str, tuple[str, ...]]:
    """The `Key: value` trailers of a commit message's last paragraph (keys lower-cased)."""

    paragraphs = [part for part in message.replace("\r\n", "\n").strip().split("\n\n") if part]
    if len(paragraphs) < 2:
        return {}
    trailers: dict[str, list[str]] = {}
    for line in paragraphs[-1].splitlines():
        key, separator, value = line.partition(":")
        key = key.strip()
        if not separator or not key or " " in key:
            continue
        trailers.setdefault(key.lower(), []).append(value.strip())
    return {key: tuple(values) for key, values in trailers.items()}


def claude_session_head(commits: Sequence[BranchCommit], session_url: str) -> str | None:
    """The newest commit (commits newest first) carrying `Claude-Session: <session_url>`."""

    wanted = session_url.strip()
    for commit in commits:
        if wanted in commit_trailers(commit.message).get(CLAUDE_SESSION_TRAILER.lower(), ()):
            return commit.sha
    return None


__all__ = [
    "BRANCH_HEAD_SCHEMA",
    "CLAUDE_SESSION_TRAILER",
    "BranchHeadSource",
    "HeadArtifactSink",
    "MissionBranchHead",
    "claude_session_head",
    "commit_trailers",
    "record_branch_head",
]
