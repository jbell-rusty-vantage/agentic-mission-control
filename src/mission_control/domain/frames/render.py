"""Pure Transcript renderers: JSONL for agents and Markdown for humans (SPEC-03, C3).

Both apply secret redaction again at render time (defence in depth) and never inline the
contents of a referenced body artifact; they render its `mc://` / `artifact://` reference.
Markdown: a heading per activation, a sub-heading per turn, one bullet per entry as
`<mark> HH:MM:SS · role · title` where `✓` marks canonical mission events and `·` marks
provider frames, tool calls as collapsed blocks with digest and excerpt, artifacts as
links, and expired frames as `(frame expired, digest …)`.

Tracing Stage 3 (owner, transcript usability): the kernel hook pairs (`hook_invoked` /
`hook_result` of the kernel ports) were more than half of every Markdown transcript. A run
of consecutive kernel hook entries renders one line per tool call (or invocation) for the
ports that allowed, `kernel hooks [call]: 4 port(s) allowed (mc.stop_fence, …)`; a port that
denied, deferred, failed or has no result keeps its entries expanded. JSONL is unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from mission_control.domain.frames.body import redact_text
from mission_control.domain.frames.transcript import TranscriptEntry
from mission_control.domain.frames.usage import render_dimension

CANONICAL_MARK = "✓"
FRAME_MARK = "·"
MARKDOWN_EXCERPT_CHARS = 1_200
# Tracing Stage 2 (F-S2-3): the readable text of a message or a prompt part, so the owner
# reads what the model saw and answered; bounded per part, never the encrypted reasoning.
MARKDOWN_TEXT_CHARS = 20_000
TURN_START_KINDS = frozenset({"session.turn_started", "turn_started"})
TOOL_KINDS = frozenset(
    {"tool_call.completed", "tool_call_started", "tool_call_completed", "tool_call_failed"}
)
HOOK_KINDS = frozenset({"hook_invoked", "hook_result"})


def _clean(value: str | None, secret_values: Sequence[str]) -> str | None:
    if value is None:
        return None
    return redact_text(value, secret_values)[0]


def redacted_entry(entry: TranscriptEntry, secret_values: Sequence[str] = ()) -> TranscriptEntry:
    """The entry with its title and excerpt redacted again."""

    return entry.model_copy(
        update={
            "title": _clean(entry.title, secret_values) or entry.title,
            "body_excerpt": _clean(entry.body_excerpt, secret_values),
        }
    )


def to_jsonl(entries: Iterable[TranscriptEntry], *, secret_values: Sequence[str] = ()) -> str:
    """One canonical JSON object per line (sorted keys, no whitespace, UTF-8)."""

    lines = [
        json.dumps(
            redacted_entry(entry, secret_values).model_dump(mode="json", exclude_none=True),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        for entry in entries
    ]
    return "".join(f"{line}\n" for line in lines)


def _artifact_link(ref: str) -> str:
    label = ref.rsplit("/", 1)[-1] or ref
    return f"[{label}]({ref})"


def _usage_line(entry: TranscriptEntry) -> str | None:
    if entry.usage is None:
        return None
    dims = entry.usage.dimensions
    return (
        f"usage: input {render_dimension(dims.get('input_tokens'))}, "
        f"output {render_dimension(dims.get('output_tokens'))}, "
        f"cost_micros {render_dimension(dims.get('cost_micros'))}"
    )


def _fence(text: str) -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return fence


def to_markdown(
    entries: Sequence[TranscriptEntry],
    *,
    run_id: str,
    secret_values: Sequence[str] = (),
) -> str:
    lines = [
        f"# Transcript · run {run_id}",
        "",
        f"_Legend: {CANONICAL_MARK} canonical mission event; {FRAME_MARK} provider frame "
        "(evidence, not state)_",
    ]
    # A turn sub-heading comes from the canonical `session.turn_started`; a provider
    # `turn_started` frame opens one only where no canonical turn event exists.
    canonical_turns = {
        entry.activation_id for entry in entries if entry.kind == "session.turn_started"
    }
    activation: str | None = "__none__"
    # The prompt parts already shown per activation: a model request repeats the whole
    # batch, the Markdown shows each part once, where the model first saw it.
    seen_parts: dict[str | None, set[str]] = {}
    summaries, collapsed = _collapsed_kernel_hooks(entries)
    for raw in entries:
        entry = redacted_entry(raw, secret_values)
        if entry.activation_id != activation:
            activation = entry.activation_id
            heading = f"Activation {activation}" if activation else "Run"
            if entry.node_key:
                heading += f" · {entry.node_key}"
            lines.extend(["", f"## {heading}", ""])
        if entry.kind == "session.turn_started" or (
            entry.kind in TURN_START_KINDS and entry.activation_id not in canonical_turns
        ):
            lines.extend(["", f"### Turn {_turn_label(entry)}", ""])
        mark = CANONICAL_MARK if entry.canonical else FRAME_MARK
        clock = entry.at.strftime("%H:%M:%S")
        if entry.cursor in collapsed:
            if entry.cursor in summaries:
                lines.append(f"- {mark} {clock} · system · {summaries[entry.cursor]}")
            continue
        title = entry.title
        if entry.refs.artifact_ref and entry.source == "artifact":
            title = f"{title} {_artifact_link(entry.refs.artifact_ref)}"
        line = f"- {mark} {clock} · {entry.role or 'system'} · {title}"
        if entry.subordinate_ref:
            line += f" _(subagent {entry.subordinate_ref})_"
        lines.append(line)
        usage = _usage_line(entry)
        if usage:
            lines.append(f"  - {usage}")
        if entry.refs.artifact_ref and entry.source != "artifact":
            lines.append(f"  - body: {_artifact_link(entry.refs.artifact_ref)}")
        if entry.kind == "message":
            lines.extend(_message_lines(entry.body_excerpt))
        elif entry.kind == "model_request":
            seen = seen_parts.setdefault(entry.activation_id, set())
            lines.extend(_request_lines(entry.body_excerpt, seen))
        if entry.kind in TOOL_KINDS and entry.body_excerpt:
            excerpt = entry.body_excerpt[:MARKDOWN_EXCERPT_CHARS]
            digest = entry.refs.body_digest or ""
            fence = _fence(excerpt)
            lines.extend(
                [
                    "  <details>",
                    f"  <summary>{entry.refs.tool_call_ref or 'tool call'} · {digest}</summary>",
                    "",
                    f"  {fence}json",
                    *(f"  {item}" for item in excerpt.splitlines() or [""]),
                    f"  {fence}",
                    "  </details>",
                ]
            )
    lines.append("")
    return "\n".join(lines)


def _kernel_hook(entry: TranscriptEntry) -> dict[str, Any] | None:
    """The body of a kernel port's hook frame (`kernel: true`), else None."""

    if entry.kind not in HOOK_KINDS or entry.source != "provider_frame":
        return None
    body = _json_object(entry.body_excerpt)
    return body if body is not None and body.get("kernel") is True else None


def _collapsed_kernel_hooks(
    entries: Sequence[TranscriptEntry],
) -> tuple[dict[str, str], set[str]]:
    """(summary line by the cursor it replaces, every collapsed cursor) for the runs of
    consecutive kernel hook entries of one activation."""

    summaries: dict[str, str] = {}
    collapsed: set[str] = set()
    index = 0
    while index < len(entries):
        if _kernel_hook(entries[index]) is None:
            index += 1
            continue
        end = index
        activation = entries[index].activation_id
        while (
            end < len(entries)
            and entries[end].activation_id == activation
            and _kernel_hook(entries[end]) is not None
        ):
            end += 1
        _summarize_hooks(entries[index:end], summaries, collapsed)
        index = end
    return summaries, collapsed


def _summarize_hooks(
    run: Sequence[TranscriptEntry], summaries: dict[str, str], collapsed: set[str]
) -> None:
    calls: dict[str, dict[str, list[tuple[TranscriptEntry, dict[str, Any]]]]] = {}
    for entry in run:
        body = _kernel_hook(entry)
        assert body is not None
        call = str(body.get("tool_call_id") or body.get("invocation_ref") or "")
        hook = str(body.get("hook_id") or "?")
        calls.setdefault(call, {}).setdefault(hook, []).append((entry, body))
    for hooks in calls.values():
        allowed = [hook for hook, items in hooks.items() if _all_allowed(items)]
        if not allowed:
            continue
        cursors = [entry.cursor for hook in allowed for entry, _ in hooks[hook]]
        first = next(entry for entry in run if entry.cursor in cursors)
        tool_call = next(
            (body.get("tool_call_id") for hook in allowed for _, body in hooks[hook]), None
        )
        label = f" [{tool_call}]" if tool_call else ""
        collapsed.update(cursors)
        summaries[first.cursor] = (
            f"kernel hooks{label}: {len(allowed)} port(s) allowed ({', '.join(allowed)})"
        )


def _all_allowed(items: Sequence[tuple[TranscriptEntry, dict[str, Any]]]) -> bool:
    """A port collapses only when it has a result and every result allowed, unfailed."""

    results = [body for entry, body in items if entry.kind == "hook_result"]
    return bool(results) and all(
        body.get("decision") == "allow" and not body.get("failed") for body in results
    )


def _json_object(text: str | None) -> dict[str, Any] | None:
    try:
        value = json.loads(text or "")
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _block_lines(content: Any) -> list[str]:
    """Readable lines of a message's content: text, tool calls, reasoning summaries."""

    if isinstance(content, str):
        return [content] if content.strip() else []
    lines: list[str] = []
    for block in content if isinstance(content, list) else ():
        if isinstance(block, str):
            lines.append(block)
        elif isinstance(block, dict):
            kind = block.get("type")
            if kind == "text" and block.get("text"):
                lines.append(str(block["text"]))
            elif kind == "reasoning":
                summary = " ".join(
                    str(item.get("text", ""))
                    for item in block.get("summary") or []
                    if isinstance(item, dict)
                )
                lines.append(f"_(reasoning{': ' + summary if summary.strip() else ', not shown'})_")
    return lines


def _quoted(text: str) -> list[str]:
    text = text[:MARKDOWN_TEXT_CHARS]
    return [f"  > {line}" if line else "  >" for line in text.splitlines() or [""]]


def _message_lines(excerpt: str | None) -> list[str]:
    body = _json_object(excerpt)
    if body is None:
        return []
    lines: list[str] = []
    for text in _block_lines(body.get("content")):
        lines.extend(_quoted(text))
    for call in body.get("tool_calls") or []:
        if isinstance(call, dict):
            args = json.dumps(call.get("args"), ensure_ascii=False, sort_keys=True)
            lines.append(f"  - calls `{call.get('name')}` {args[:MARKDOWN_EXCERPT_CHARS]}")
    return lines


def _request_lines(excerpt: str | None, seen: set[str]) -> list[str]:
    body = _json_object(excerpt)
    if body is None:
        return []
    model: dict[str, Any] = body["model"] if isinstance(body.get("model"), dict) else {}
    graph: dict[str, Any] = body["langgraph"] if isinstance(body.get("langgraph"), dict) else {}
    messages = [item for item in body.get("messages") or [] if isinstance(item, dict)]
    tools = [str(item.get("name")) for item in body.get("tools") or [] if isinstance(item, dict)]
    lines = [
        f"  - model `{model.get('name')}` · step {graph.get('step')} · "
        f"{len(messages)} message(s) · tool choice {body.get('tool_choice') or 'auto'} · "
        f"tools: {', '.join(tools) or 'none'}"
    ]
    system = body.get("system") if isinstance(body.get("system"), dict) else None
    for label, part in [("system", system), *((str(m.get("type")), m) for m in messages)]:
        if part is None:
            continue
        # Tracing Stage 3 (R4-F14): a part with neither digest nor id has no identity to
        # deduplicate by (an empty key used to hide every later such part); its reference
        # names it when it has one, else it is always shown.
        key = str(part.get("digest") or part.get("id") or part.get("ref") or "")
        if (key and key in seen) or "body" not in part:
            continue
        if key:
            seen.add(key)
        resolved = part["body"]
        content = (
            resolved.get("content", resolved.get("text", resolved))
            if isinstance(resolved, dict)
            else resolved
        )
        texts = _block_lines(content) or ([] if content in (None, "") else [str(content)])
        lines.extend(
            [
                "  <details>",
                f"  <summary>new to the model: {label} · {part.get('bytes', '?')} bytes</summary>",
                "",
                *(line for text in texts for line in _quoted(text)),
                "  </details>",
            ]
        )
    return lines


def _turn_label(entry: TranscriptEntry) -> str:
    if entry.body_excerpt:
        try:
            body = json.loads(entry.body_excerpt)
        except ValueError:
            body = None
        if isinstance(body, dict) and isinstance(body.get("turn_ordinal"), int):
            return str(body["turn_ordinal"])
    return entry.refs.native_event_ref or entry.cursor[-8:]
