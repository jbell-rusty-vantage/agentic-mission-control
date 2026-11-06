"""FIXTURE stand-in for the Claude Code CLI in `--input-format stream-json` mode (MO-73).

FIXTURE ONLY: no model is called and nothing here is a live recording. The process speaks the
wire the pinned claude_agent_sdk==0.2.165 drives over the lane's transport: it answers the
`initialize` control request, emits `system/init`, and answers each streamed user message with
one assistant message and a `result`. Like the CLI it keeps the session transcript at
`<CLAUDE_CONFIG_DIR or ~/.claude>/projects/<project key of the cwd>/<session_id>.jsonl`,
emits a `transcript_mirror` frame per write when started with `--session-mirror`, and on
`--resume=<id>` continues that session from the transcript file alone, exiting non-zero when
the file is absent. Each reply lists every user prompt of the session so far, so a test can
tell a restored history from a lost one.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from bootstrap_usage_fixture import zero_bootstrap_usage
from claude_agent_sdk import project_key_for_directory

MODEL = "claude-fixture"


def _emit(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _option(argv: list[str], name: str) -> str | None:
    prefix = f"{name}="
    for arg in argv:
        if arg.startswith(prefix):
            return arg[len(prefix) :]
    return None


def _transcript_dir() -> Path:
    configured = os.environ.get("CLAUDE_CONFIG_DIR")
    config = Path(configured) if configured else Path.home() / ".claude"
    return config / "projects" / project_key_for_directory(Path.cwd())


def _read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class FakeCli:
    def __init__(self, argv: list[str]) -> None:
        self.mirror = "--session-mirror" in argv
        resume = _option(argv, "--resume")
        self.session_id = resume or str(uuid.uuid4())
        self.path = _transcript_dir() / f"{self.session_id}.jsonl"
        if resume is not None and not self.path.is_file():
            sys.stderr.write(f"No conversation found with session ID: {resume}\n")
            raise SystemExit(1)
        self.entries = _read(self.path) if resume is not None else []

    def _record(self, entries: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.writelines(json.dumps(entry) + "\n" for entry in entries)
        self.entries.extend(entries)
        if self.mirror:
            _emit({"type": "transcript_mirror", "filePath": str(self.path), "entries": entries})

    def _entry(self, kind: str, message: dict[str, Any], entry_uuid: str) -> dict[str, Any]:
        parent = self.entries[-1]["uuid"] if self.entries else None
        return {
            "type": kind,
            "uuid": entry_uuid,
            "parentUuid": parent,
            "sessionId": self.session_id,
            "cwd": str(Path.cwd()),
            "message": message,
        }

    def control(self, request_id: str, request: dict[str, Any]) -> None:
        _emit(
            {
                "type": "control_response",
                "response": {"subtype": "success", "request_id": request_id, "response": {}},
            }
        )
        if request.get("subtype") == "initialize":
            _emit(
                {
                    "type": "system",
                    "subtype": "init",
                    "session_id": self.session_id,
                    "uuid": str(uuid.uuid4()),
                    "model": MODEL,
                    "cwd": str(Path.cwd()),
                    "tools": [],
                    "mcp_servers": [],
                    "permissionMode": "default",
                    "apiKeySource": "none",
                }
            )

    def turn(self, message: dict[str, Any]) -> None:
        if message.get("shouldQuery") is False:
            assert message.get("isSynthetic") is True
            assert message.get("client_composed") is True
            _emit(
                {
                    "type": "result",
                    "subtype": "success",
                    "session_id": self.session_id,
                    "is_error": False,
                    "num_turns": 0,
                    "duration_ms": 1,
                    "duration_api_ms": 0,
                    "total_cost_usd": 0,
                    "usage": zero_bootstrap_usage(),
                    "origin": {"kind": "unclassified"},
                    "result": "",
                }
            )
            return
        user = self._entry("user", message["message"], message.get("uuid") or str(uuid.uuid4()))
        history = [*self.entries, user]
        prompts = [entry["message"]["content"] for entry in history if entry["type"] == "user"]
        text = f"turn {len(prompts)} of {self.session_id}; prompts: {json.dumps(prompts)}"
        reply = {"role": "assistant", "model": MODEL, "content": [{"type": "text", "text": text}]}
        assistant = self._entry("assistant", reply, str(uuid.uuid4()))
        assistant["parentUuid"] = user["uuid"]
        self._record([user, assistant])
        _emit(
            {
                "type": "assistant",
                "uuid": assistant["uuid"],
                "session_id": self.session_id,
                "parent_tool_use_id": None,
                "message": {**reply, "id": f"msg_{assistant['uuid']}", "stop_reason": "end_turn"},
            }
        )
        _emit(
            {
                "type": "result",
                "subtype": "success",
                "uuid": str(uuid.uuid4()),
                "session_id": self.session_id,
                "is_error": False,
                "num_turns": len(prompts),
                "duration_ms": 1,
                "duration_api_ms": 0,
                "result": text,
                "stop_reason": "end_turn",
                "total_cost_usd": 0.0,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }
        )

    def run(self) -> None:
        for line in sys.stdin:
            if not line.strip():
                continue
            message = json.loads(line)
            if message.get("type") == "control_request":
                self.control(message["request_id"], message["request"])
            elif message.get("type") == "user":
                self.turn(message)


if __name__ == "__main__":
    FakeCli(sys.argv[1:]).run()
