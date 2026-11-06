"""Tracing Stage 2 (F-S2-3): the Markdown transcript shows what the model saw and answered.

A `message` entry renders its text and tool calls (never the encrypted reasoning); a
`model_request` renders the model, step, tools and, when a full read resolved them, each
prompt part once, where the model first saw it.

Tracing Stage 3: kernel hook pairs collapse to one line per tool call while every port
allowed (a deny, a failure or a missing result stays expanded; JSONL is unchanged), and a
prompt part without a digest or id is never hidden by another such part (R4-F14).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from mission_control.domain.frames.render import to_jsonl, to_markdown
from mission_control.domain.frames.transcript import TranscriptBody, TranscriptEntry

CURSOR = "tc1:000000000001:00000000000000000:000000000000:00000000"


def entry(kind: str, body: dict[str, object], seq: int) -> TranscriptEntry:
    return TranscriptEntry(
        cursor=CURSOR.replace("000000000001", f"{seq:012d}", 1),
        run_id="run-1",
        activation_id="activation-1",
        at=datetime(2026, 10, 22, 20, 0, seq, tzinfo=UTC),
        source="provider_frame",
        kind=kind,
        role="agent" if kind == "message" else "system",
        title=kind,
        body_excerpt=json.dumps(body),
        body=TranscriptBody(state="inline"),
        canonical=False,
    )


def request(messages: list[dict[str, object]], step: int, seq: int) -> TranscriptEntry:
    return entry(
        "model_request",
        {
            "model": {"name": "gpt-6-sol"},
            "langgraph": {"step": step},
            "tool_choice": "auto",
            "tools": [{"name": "write_file"}],
            "system": {"digest": "sha256:s", "bytes": 20, "body": {"content": "Be careful."}},
            "messages": messages,
        },
        seq,
    )


def test_messages_and_prompt_parts_are_readable_once() -> None:
    human = {
        "digest": "sha256:h",
        "bytes": 30,
        "type": "human",
        "body": {"type": "human", "content": "Write the note about the WAL."},
    }
    answer = {
        "content": [
            {"type": "reasoning", "encrypted_content": "gAAAA-secret", "summary": []},
            {"type": "text", "text": "I wrote the note at /work/note.md."},
        ],
        "tool_calls": [{"name": "write_file", "args": {"file_path": "/work/note.md"}}],
    }
    markdown = to_markdown(
        [
            request([human], 3, 1),
            entry("message", answer, 2),
            request([human, {"digest": "sha256:a", "type": "ai", "bytes": 9}], 5, 3),
        ],
        run_id="run-1",
    )

    assert "model `gpt-6-sol` · step 3 · 1 message(s)" in markdown
    assert markdown.count("Write the note about the WAL.") == 1
    assert markdown.count("Be careful.") == 1
    assert "  > I wrote the note at /work/note.md." in markdown
    assert 'calls `write_file` {"file_path": "/work/note.md"}' in markdown
    assert "gAAAA-secret" not in markdown
    assert "_(reasoning, not shown)_" in markdown


def hook(
    kind: str, hook_id: str, seq: int, *, call: str = "call-1", **result: object
) -> TranscriptEntry:
    body: dict[str, object] = {
        "hook_id": hook_id,
        "kernel": True,
        "event": "before_tool",
        "tool_call_id": call,
        "invocation_ref": f"call.{call}",
    }
    if kind == "hook_result":
        body.update({"decision": "allow", "failed": False, **result})
    return entry(kind, body, seq).model_copy(update={"title": f"{kind} [{call}]"})


def test_kernel_hook_pairs_collapse_per_tool_call_and_denials_stay_expanded() -> None:
    ports = ("mc.stop_fence", "mc.budget", "mc.approval", "mc.usage")
    first = [
        item
        for index, port in enumerate(ports)
        for item in (
            hook("hook_invoked", port, 2 * index + 1),
            hook("hook_result", port, 2 * index + 2),
        )
    ]
    denied = [
        hook("hook_invoked", "mc.stop_fence", 20, call="call-2"),
        hook("hook_result", "mc.stop_fence", 21, call="call-2", decision="deny"),
        hook("hook_invoked", "mc.usage", 22, call="call-2"),
        hook("hook_result", "mc.usage", 23, call="call-2"),
        hook("hook_invoked", "mc.budget", 24, call="call-2"),  # no result yet
    ]
    answer = entry("message", {"content": "done"}, 10)
    entries = [*first, answer, *denied]
    markdown = to_markdown(entries, run_id="run-1")

    assert (
        markdown.count("kernel hooks [call-1]: 4 port(s) allowed (" + ", ".join(ports) + ")") == 1
    )
    assert "hook_invoked [call-1]" not in markdown and "hook_result [call-1]" not in markdown
    assert "kernel hooks [call-2]: 1 port(s) allowed (mc.usage)" in markdown
    assert markdown.count("hook_invoked [call-2]") == 2  # mc.stop_fence and mc.budget
    assert markdown.count("hook_result [call-2]") == 1  # the denial
    assert len(to_jsonl(entries).splitlines()) == len(entries), "JSONL keeps every entry"


def test_a_hook_that_is_not_a_kernel_port_is_not_collapsed() -> None:
    script = hook("hook_result", "catalog.lint", 1).model_copy(
        update={
            "body_excerpt": json.dumps(
                {"hook_id": "catalog.lint", "kernel": False, "decision": "allow"}
            )
        }
    )
    assert "hook_result [call-1]" in to_markdown([script], run_id="run-1")


def test_prompt_parts_without_identity_are_all_shown() -> None:
    parts = [
        {"type": "human", "body": {"content": "first anonymous part"}},
        {"type": "human", "body": {"content": "second anonymous part"}},
    ]
    markdown = to_markdown([request(parts, 1, 1)], run_id="run-1")
    assert "first anonymous part" in markdown and "second anonymous part" in markdown
