"""Provider-neutral mission branches and non-committed cloud input delivery (MO-50)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from mission_control.application.agentic_components.placement import (
    DurableInputReader,
    LaneProjectionError,
    packet_files,
    safe_relative,
)
from mission_control.application.effects.mission_branches import mission_branch_prefix
from mission_control.domain.execution.contracts import OperationExecutionRequest

MAX_COMMITTED_INPUT_BYTES = 256 * 1024
REMOTE_INPUT_MANIFEST = ".mission/inputs.remote.json"
FETCH_INPUTS_SCRIPT = ".mission/setup/fetch-inputs.py"
RUNTIME_INPUT_URLS = "MC_INPUT_URLS"


@dataclass(frozen=True)
class PublishedBranch:
    branch: str
    head: str
    base_commit: str


class BranchPublisher(Protocol):
    async def publish(
        self,
        *,
        repository: str,
        base_ref: str,
        branch: str,
        files: Sequence[tuple[str, bytes]],
        secret_values: Iterable[str] = (),
    ) -> PublishedBranch: ...


def mission_branch(run_id: str, unit_id: str, *, prefix: str = "mc/") -> str:
    # Preserve the run segment used by the scoped pre-push guard and repo_pr policy.
    run_path = mission_branch_prefix(run_id).removeprefix("mc/")
    # Semantic operation ids can be hundreds of characters. Keep refs short enough
    # for Git on Windows while retaining a readable hint and a 96-bit identity hash.
    clean = re.sub(r"[^A-Za-z0-9_-]", "-", unit_id).strip("-")[:8] or "unit"
    unit = f"{clean}-{sha256(unit_id.encode()).hexdigest()[:24]}"
    return f"{prefix}{run_path}{unit}"


@dataclass(frozen=True)
class CloudPacket:
    files: tuple[tuple[str, bytes], ...]
    remote: tuple[dict[str, object], ...]


async def cloud_packet(
    operation: OperationExecutionRequest,
    reader: DurableInputReader | None,
) -> CloudPacket:
    """Keep cognition, setup and packet metadata; replace unsafe input bytes with references."""
    files = await packet_files(operation, reader)
    slots = {
        safe_relative(slot.logical_path).as_posix(): slot
        for slot in operation.workspace.slot_bindings
    }
    kept: list[tuple[str, bytes]] = []
    remote: list[dict[str, object]] = []
    for path, content in files:
        slot = slots.get(path) or next(
            (slot for logical, slot in slots.items() if logical.endswith("/" + path)), None
        )
        # Packet metadata and operating instructions remain committed; actual input files do not.
        if path.startswith("inputs/") and (
            len(content) > MAX_COMMITTED_INPUT_BYTES or (slot is not None and slot.sensitive)
        ):
            if slot is None or slot.durable_ref is None:
                raise LaneProjectionError(
                    "PREREQUISITES_UNMET", "cloud input has no durable reference"
                )
            remote.append(
                {
                    "path": path,
                    "durable_ref": slot.durable_ref,
                    "content_digest": slot.content_digest,
                    "bytes": len(content),
                }
            )
        else:
            kept.append((path, content))
    if remote:
        kept += [
            (
                REMOTE_INPUT_MANIFEST,
                (
                    json.dumps(
                        {"schema_version": "mc.remote_inputs.v1", "inputs": remote},
                        sort_keys=True,
                        indent=2,
                    )
                    + "\n"
                ).encode(),
            ),
            (FETCH_INPUTS_SCRIPT, FETCH_SCRIPT.encode()),
        ]
    return CloudPacket(tuple(kept), tuple(remote))


async def runtime_input_urls(packet: CloudPacket, reader: DurableInputReader | None) -> str | None:
    if not packet.remote:
        return None
    runtime_url = getattr(reader, "runtime_url", None)
    if not callable(runtime_url):
        raise LaneProjectionError(
            "PREREQUISITES_UNMET", "cloud inputs require runtime signed-URL delivery"
        )
    try:
        urls = {
            str(item["content_digest"]): await runtime_url(str(item["durable_ref"]))
            for item in packet.remote
        }
    except Exception as error:
        raise LaneProjectionError(
            "PREREQUISITES_UNMET", "cloud input signing is unavailable"
        ) from error
    if any(not isinstance(url, str) or not url.startswith("https://") for url in urls.values()):
        raise LaneProjectionError("PREREQUISITES_UNMET", "cloud input delivery requires HTTPS URLs")
    return json.dumps(urls, sort_keys=True)


FETCH_SCRIPT = '''#!/usr/bin/env python3
"""Fetch digest-bound input references; URLs arrive only through the launch environment."""
import hashlib
import json
import os
from pathlib import Path
import urllib.request

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("input download redirects are refused")

def fetch(root, urls, download):
    manifest = json.loads((root / ".mission/inputs.remote.json").read_bytes())
    for item in manifest["inputs"]:
        if "\\\\" in item["path"] or ":" in item["path"]:
            raise ValueError("unsafe input path")
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "inputs":
            raise ValueError("unsafe input path")
        target = root
        for part in relative.parts:
            target = target / part
            if target.is_symlink():
                raise ValueError("input path crosses a symlink")
        url = urls[item["content_digest"]]
        if not url.startswith("https://"):
            raise ValueError("input URL must use HTTPS")
        content = download(url, item["bytes"] + 1)
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        if len(content) != item["bytes"] or digest != item["content_digest"]:
            raise ValueError("input content does not match its sealed digest")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".mc-download")
        if temporary.is_symlink():
            raise ValueError("input staging path crosses a symlink")
        temporary.write_bytes(content)
        temporary.chmod(0o444)
        os.replace(temporary, target)

def main():
    opener = urllib.request.build_opener(NoRedirect())
    def download(url, limit):
        with opener.open(url, timeout=60) as response:
            return response.read(limit)
    fetch(Path.cwd(), json.loads(os.environ["MC_INPUT_URLS"]), download)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("runtime input retrieval failed; no unverified input was installed")
'''
