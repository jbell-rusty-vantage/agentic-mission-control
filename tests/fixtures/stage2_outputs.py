"""Tracing Stage 2 (SESSION-STAGE-2 §4a): the files the owner reads for every fixture run.

`write_outputs` writes, under `.scratch/tracing-stage-2/<fixture>/<run id>/` (git-ignored like
every runtime receipt), through the public surfaces only (`missionctl` over loopback HTTP and
the configured API):

- `transcript.jsonl` / `transcript.md`: `run transcript RUN --format jsonl|md --limit 5000 --full`
- `transcript-by-step.jsonl` and `transcript-by-stage.jsonl` (`--by iteration` for a Goal Loop)
- `mission.json`: what the run was compiled and admitted from (the caller's `mission` block),
  `run inspect` at completion, the points index (every page) and, for a fork, its receipt
- `outputs/`: the bytes behind every output reference the result points name, downloaded with
  `run artifact`; a reference the route refuses is listed with the refusal instead
- `commands.json`: each command run, its exit code and stderr tail (so a failed read is visible)

Returns the manifest of what was written; the ledger entry names each file.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

from tests.fixtures.live_models import OUTPUT_ROOT
from tests.fixtures.scoped_api_stack import ScopedStack

BASE = "/v1/applications/biotech/runs"
REF_PATTERN = re.compile(r"(?:artifact|workspace-candidates?|frame-body)://[^\s\"'<>)\]]+")


def run_directory(fixture: str, run_id: str) -> Path:
    return OUTPUT_ROOT / fixture / run_id


CLI_TIMEOUT_SECONDS = 300


def _spawn(url: str, token: str, *args: str) -> subprocess.Popen[bytes]:
    """One `missionctl` process (the Windows selector loop cannot spawn asyncio ones)."""

    return subprocess.Popen(
        [sys.executable, "-m", "mission_control.interfaces.cli", *args],
        env={
            **os.environ,
            "MISSION_CONTROL_URL": url,
            "MISSION_CONTROL_APPLICATION_ID": "biotech",
            "MISSION_CONTROL_TOKEN": token,
            "PYTHONIOENCODING": "utf-8",
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


async def missionctl(url: str, token: str, *args: str) -> tuple[int, bytes, str]:
    """Run one `missionctl` command over loopback HTTP: (exit code, stdout bytes, stderr)."""

    process = _spawn(url, token, *args)
    stdout, stderr = await asyncio.to_thread(process.communicate, timeout=CLI_TIMEOUT_SECONDS)
    return process.returncode, stdout, stderr.decode("utf-8", errors="replace")


async def all_points(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """Every point of the run (the route pages at 500)."""

    points: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"limit": 500}
        if cursor:
            params["cursor"] = cursor
        response = await stack.http.get(f"{BASE}/{run_id}/points", params=params)
        response.raise_for_status()
        page = response.json()
        points.extend(page["entries"])
        cursor = page.get("next_cursor")
        if not cursor:
            return points


def output_refs(points: list[dict[str, Any]], inspection: dict[str, Any]) -> list[str]:
    """Every output reference a result point or the run inspection names, in first-seen order."""

    found: list[str] = []
    for source in (
        [point for point in points if "result" in (point.get("roles") or [])],
        inspection,
    ):
        for match in REF_PATTERN.findall(json.dumps(source, default=str)):
            if match not in found and not match.startswith("frame-body://"):
                found.append(match)
    return found


async def custody_outputs(stack: ScopedStack, run_id: str, target: Path) -> list[dict[str, Any]]:
    """Every workspace candidate the run's units wrote, read from custody by the fixture.

    No public route serves `workspace-candidate://` bytes yet (`run artifact` answers
    `artifact_unavailable`; AUDIT-OUTPUT-TRANSFER §A3, specification §3.5), so the fixture
    reads the descriptors and the payload store the packer itself reads
    (`PostgresArtifactBytes`), and labels the files as such.
    """

    from mission_control.adapters.postgres.context.artifact_bytes import PostgresArtifactBytes
    from mission_control.adapters.postgres.scope import apply_scope
    from mission_control.adapters.temporal.deployment_composition import artifact_payload_store
    from mission_control.bootstrap.settings import get_settings
    from mission_control.contracts.identities import parse_request_scope

    scope = parse_request_scope(stack.scope)
    async with stack.pool.acquire() as connection, connection.transaction():
        await apply_scope(connection, scope)
        rows = await connection.fetch(
            """SELECT candidate_key, namespace_key, workspace_key, logical_path, content_digest,
                      size_bytes, recorded_at
               FROM mission_control.workspace_candidate_descriptor
               WHERE installation_id=$1 AND application_id=$2 AND tenant_id=$3
                 AND namespace_key LIKE $4
               ORDER BY recorded_at""",
            scope.installation_id,
            scope.application_id,
            scope.tenant_id,
            f"%{run_id}%",
        )
    reader = PostgresArtifactBytes(stack.pool, artifact_payload_store(get_settings()))
    found: list[dict[str, Any]] = []
    await asyncio.to_thread(target.mkdir, parents=True, exist_ok=True)
    for index, row in enumerate(rows):
        ref = f"workspace-candidate://{row['candidate_key']}"
        content = await reader.capture(ref, request_scope=stack.scope, max_text_bytes=10_000_000)
        name = f"{index:02d}_{_safe_name(row['workspace_key'])}{_safe_name(row['logical_path'])}"
        entry = {
            "ref": ref,
            "workspace": row["workspace_key"],
            "logical_path": row["logical_path"],
            "content_digest": row["content_digest"],
            "size_bytes": row["size_bytes"],
            "recorded_at": row["recorded_at"],
            "source": "custody (fixture read; no public route serves candidates)",
            "file": None,
        }
        if content is not None and content.text is not None:
            (target / name).write_text(content.text, encoding="utf-8")
            entry["file"] = str(target / name)
        found.append(entry)
    return found


def _safe_name(ref: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", ref)[:150]


async def write_outputs(
    stack: ScopedStack,
    url: str,
    *,
    fixture: str,
    run_id: str,
    group: Literal["stage", "iteration"],
    mission: dict[str, Any],
    fork_receipt: dict[str, Any] | None = None,
    extra_files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    directory = run_directory(fixture, run_id)
    directory.mkdir(parents=True, exist_ok=True)
    commands: list[dict[str, Any]] = []
    files: dict[str, str] = {}

    async def read(name: str, *args: str) -> bytes:
        code, out, err = await missionctl(url, stack.token, *args)
        commands.append(
            {"file": name, "args": list(args), "exit": code, "stderr_tail": err[-2000:]}
        )
        (directory / name).write_bytes(out)
        files[name] = str(directory / name)
        return out

    full = ("--limit", "5000", "--full")
    await read("transcript.jsonl", "run", "transcript", run_id, "--format", "jsonl", *full)
    await read("transcript.md", "run", "transcript", run_id, "--format", "md", *full)
    await read(
        "transcript-by-step.jsonl",
        "run",
        "transcript",
        run_id,
        "--format",
        "jsonl",
        "--by",
        "step",
        *full,
    )
    await read(
        f"transcript-by-{group}.jsonl",
        "run",
        "transcript",
        run_id,
        "--format",
        "jsonl",
        "--by",
        group,
        *full,
    )
    inspection_raw = await read("inspect.json", "run", "inspect", run_id, "--json")
    try:
        inspection = json.loads(inspection_raw.decode("utf-8"))
    except ValueError:
        inspection = {"unparsed": inspection_raw.decode("utf-8", errors="replace")}
    points = await all_points(stack, run_id)

    outputs = directory / "outputs"
    outputs.mkdir(exist_ok=True)
    downloads: list[dict[str, Any]] = []
    for ref in output_refs(points, inspection):
        target = outputs / _safe_name(ref)
        code, out, err = await missionctl(
            url, stack.token, "run", "artifact", run_id, ref, "--out", str(target)
        )
        downloads.append(
            {
                "ref": ref,
                "exit": code,
                "file": str(target) if code == 0 and target.exists() else None,
                "refusal": None
                if code == 0
                else (err.strip() or out.decode(errors="replace"))[-600:],
            }
        )

    candidates = await custody_outputs(stack, run_id, outputs / "custody")

    document = {
        "run_id": run_id,
        "mission": mission,
        "inspect": inspection,
        "points": points,
        "fork_receipt": fork_receipt,
        "outputs": downloads,
        "workspace_candidates": candidates,
    }
    (directory / "mission.json").write_text(
        json.dumps(document, indent=2, default=str), encoding="utf-8"
    )
    files["mission.json"] = str(directory / "mission.json")
    for name, payload in (extra_files or {}).items():
        path = directory / name
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
        files[name] = str(path)
    (directory / "commands.json").write_text(json.dumps(commands, indent=2), encoding="utf-8")
    files["commands.json"] = str(directory / "commands.json")
    return {
        "directory": str(directory),
        "files": files,
        "outputs": downloads,
        "workspace_candidates": len(candidates),
        "failed_commands": [item for item in commands if item["exit"] != 0],
        "points": len(points),
    }
