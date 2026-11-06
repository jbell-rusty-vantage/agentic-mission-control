"""Codex hook trust for the projected `.codex/hooks.json` (SPEC-02 §5 "Codex trust"; Q-X2).

Codex runs a non-managed hook only when its state entry in a config layer names the hook's
current hash: `[hooks.state."<source path>:<event>:<group>:<handler>"]` with
`trusted_hash = "sha256:<hex>"` (`hooks/list` reports `trustStatus` `trusted`, `untrusted` or
`modified`). The hash is Codex's `version_for_toml` of the normalized hook identity: SHA-256
over the key-sorted compact JSON of `{event_name, matcher, hooks: [handler]}`, the handler
normalized as `codex-rs/hooks/src/engine/discovery.rs` does at the pinned CLI (timeout default
600 s, 1-3 s for `SessionEnd` and `Interrupt`; `async` always present; no matcher on
`UserPromptSubmit`, `Stop` and `Interrupt`; an `additionalContextLimit` only on the events
that spill context and only when it differs from the 2,500-token default). The formula is
pinned by hashes the 0.162.1 app-server reported (`tests/fixtures/provider_frames/codex/
hooks_list/`).

Q-X2, observed through `hooks/list` on codex-cli 0.162.1 (no login, no model turn): trust
records in the isolated `CODEX_HOME/config.toml` are honoured; neither `-c` overrides of
`hooks.state` (nor of the project trust, which then loads no project hooks at all), session
flag hooks nor a `requirements.toml` in `CODEX_HOME` are. So the lane writes the records for
the exact bytes it projected into the isolated home, refuses hooks in the owner's home, and
after `initialize` checks `hooks/list` before any thread starts (`verify_listed_trust`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

HOOKS_FILE: Final = ".codex/hooks.json"
HOOK_TRUST_UNVERIFIED: Final = "HOOK_TRUST_UNVERIFIED"
DEFAULT_TIMEOUT_S: Final = 600
DEFAULT_CONTEXT_LIMIT: Final = 2_500
_SHORT_TIMEOUT_EVENTS: Final = frozenset({"SessionEnd", "Interrupt"})
_NO_MATCHER_EVENTS: Final = frozenset({"UserPromptSubmit", "Stop", "Interrupt"})
_CONTEXT_LIMIT_EVENTS: Final = frozenset(
    {"PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "SubagentStart"}
)
TRUSTED_STATUSES: Final = frozenset({"trusted", "managed"})


class HookTrustUnverified(RuntimeError):
    """Codex would not run a projected hook as trusted: the session does not start."""

    code = HOOK_TRUST_UNVERIFIED


@dataclass(frozen=True)
class HookTrustRecord:
    """One `[hooks.state]` entry: the hook's state key and the hash Codex must find."""

    key: str
    trusted_hash: str
    event: str
    command: str


def _event_label(event: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", event).lower()


def _timeout(event: str, value: Any) -> int:
    seconds = value if isinstance(value, int) and not isinstance(value, bool) else None
    if event in _SHORT_TIMEOUT_EVENTS:
        return min(max(seconds if seconds is not None else 1, 1), 3)
    return max(seconds if seconds is not None else DEFAULT_TIMEOUT_S, 1)


def _normalized_handler(event: str, handler: Mapping[str, Any]) -> dict[str, Any]:
    if handler.get("type") != "command" or not handler.get("command"):
        raise ValueError(f"{event}: Mission Control projects command hooks only")
    normalized: dict[str, Any] = {
        "type": "command",
        "command": str(handler["command"]),
        "timeout": _timeout(event, handler.get("timeout", handler.get("timeoutSec"))),
        "async": bool(handler.get("async", False)),
    }
    if handler.get("statusMessage") is not None:
        normalized["statusMessage"] = str(handler["statusMessage"])
    limit = handler.get("additionalContextLimit")
    if event in _CONTEXT_LIMIT_EVENTS and isinstance(limit, int) and limit != DEFAULT_CONTEXT_LIMIT:
        normalized["additionalContextLimit"] = limit
    return normalized


def hook_hash(event: str, matcher: str | None, handler: Mapping[str, Any]) -> str:
    """Codex's `current_hash` of one handler of one matcher group of `event`."""

    identity: dict[str, Any] = {
        "event_name": _event_label(event),
        "hooks": [_normalized_handler(event, handler)],
    }
    if matcher is not None and event not in _NO_MATCHER_EVENTS:
        identity["matcher"] = matcher
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def hook_trust_records(hooks_json: bytes, source_path: Path) -> tuple[HookTrustRecord, ...]:
    """Every handler of a `hooks.json` (the bytes Mission Control projected) as the trust
    record Codex keys on `source_path`, the file's absolute path as Codex reports it."""

    document = json.loads(hooks_json.decode("utf-8"))
    events = document.get("hooks", {}) if isinstance(document, dict) else {}
    records: list[HookTrustRecord] = []
    for event, groups in events.items():
        for group_index, group in enumerate(groups or ()):
            matcher = group.get("matcher")
            for handler_index, handler in enumerate(group.get("hooks") or ()):
                records.append(
                    HookTrustRecord(
                        key=f"{source_path}:{_event_label(event)}:{group_index}:{handler_index}",
                        trusted_hash=hook_hash(
                            event, None if matcher is None else str(matcher), handler
                        ),
                        event=event,
                        command=str(handler.get("command", "")),
                    )
                )
    return tuple(records)


def _toml_string(value: str) -> str:
    return json.dumps(value)


def hook_trust_toml(records: Iterable[HookTrustRecord]) -> str:
    """The `[hooks.state]` tables of the isolated `CODEX_HOME/config.toml`."""

    return "".join(
        f"\n[hooks.state.{_toml_string(record.key)}]\n"
        f"enabled = true\ntrusted_hash = {_toml_string(record.trusted_hash)}\n"
        for record in records
    )


def verify_listed_trust(
    listed: Mapping[str, Any], records: Sequence[HookTrustRecord], source_path: Path
) -> None:
    """Refuse (`HookTrustUnverified`) unless `hooks/list` reports every projected handler of
    `source_path` at its recorded key and hash, trusted, enabled and without load errors."""

    entries = [
        entry
        for item in listed.get("data") or ()
        for entry in (item.get("hooks") or ())
        if str(entry.get("sourcePath")) == str(source_path)
    ]
    errors = [
        str(error.get("message"))
        for item in listed.get("data") or ()
        for error in (item.get("errors") or ())
        if str(error.get("path")) == str(source_path)
    ]
    if errors:
        raise HookTrustUnverified(f"Codex could not load {HOOKS_FILE}: {'; '.join(errors)}")
    by_key = {str(entry.get("key")): entry for entry in entries}
    missing = [record.key for record in records if record.key not in by_key]
    if missing or len(by_key) != len(records):
        raise HookTrustUnverified(
            f"Codex lists {len(by_key)} of the {len(records)} projected hooks of {HOOKS_FILE}"
        )
    for record in records:
        entry = by_key[record.key]
        status = str(entry.get("trustStatus"))
        if (
            status not in TRUSTED_STATUSES
            or entry.get("enabled") is False
            or entry.get("currentHash") != record.trusted_hash
        ):
            raise HookTrustUnverified(
                f"Codex reports hook {record.event} `{record.command}` as {status} "
                f"(hash {entry.get('currentHash')}, recorded {record.trusted_hash})"
            )


__all__ = [
    "HOOKS_FILE",
    "HOOK_TRUST_UNVERIFIED",
    "HookTrustRecord",
    "HookTrustUnverified",
    "hook_hash",
    "hook_trust_records",
    "hook_trust_toml",
    "verify_listed_trust",
]
