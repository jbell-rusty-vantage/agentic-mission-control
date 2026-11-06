"""Shared pieces of the HL-23 provider smokes: labels, verdicts, the evidence record and cleanup.

Nothing here imports a provider SDK, so the offline tests run against the project venv while the
smokes themselves run under the pinned SDKs (`uv run --no-project --with ...`).
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

RUN_LABEL = "run1-HL-23"
METADATA = {"mc_run": RUN_LABEL}
# Neither Skills API accepts metadata, so the skill carries the run label in its name.
SKILL_NAME = "mc-run1-hl-23-smoke"
MIDTURN_ACK = "MIDTURN-ACK"
AGENTS_MD_CANARY = "AGENTS-CANARY-7Q4"
SIGNAL_TOOL = "mc_signal"
# The vault credential proves the shape only; its value is a fixed non-secret placeholder.
VAULT_VARIABLE = "MC_SMOKE_PLACEHOLDER"
VAULT_VARIABLE_HOST = "example.com"
# Provider 401 messages can echo a masked key fragment; scrub anything key-shaped.
_KEY_LIKE = re.compile(r"\b(?:sk|whsec)[-_][A-Za-z0-9_\-*]+")

SIGNAL_TOOL_DESCRIPTION = "Report a Mission Control lifecycle signal. Returns 'ok'."
SIGNAL_TOOL_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"name": {"type": "string", "description": "Signal name, e.g. smoke.start"}},
    "required": ["name"],
    "additionalProperties": False,
}

MIDTURN_MESSAGE = (
    f"Additional instruction sent while you are working: include the word {MIDTURN_ACK} "
    "in your final answer for this task."
)
LONG_TURN_PROMPT = (
    "Write the numbers from one to three hundred as English words, one per line, "
    "with no other text."
)


def skill_files() -> list[tuple[str, bytes, str]]:
    """The smoke skill bundle as SDK upload tuples: one `SKILL.md` in its own directory."""
    body = (
        f"---\nname: {SKILL_NAME}\n"
        "description: Mission Control provider smoke skill. Use when asked about the smoke.\n"
        "---\n\n# Mission Control smoke skill\n\n"
        "This skill exists only to prove that a custom skill attaches to a hosted agent.\n"
    )
    return [(f"{SKILL_NAME}/SKILL.md", body.encode(), "text/markdown")]


def record_path(value: str) -> Path:
    """`--record` argument type: a `.json` path whose directory exists or can be created.

    Checked before anything is provisioned, so a paid run never ends without its evidence.
    """
    path = Path(value)
    if path.suffix != ".json":
        raise argparse.ArgumentTypeError(f"--record must name a .json file, got {value!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def placeholder_credential_auth() -> dict[str, object]:
    """The one vault credential: an egress-substituted environment variable, same on both APIs."""
    return {
        "type": "environment_variable",
        "secret_name": VAULT_VARIABLE,
        "secret_value": "mc-smoke-placeholder-not-a-secret",
        "networking": {"type": "limited", "allowed_hosts": [VAULT_VARIABLE_HOST]},
    }


def mid_turn_delivery(timeline: Sequence[str]) -> str:
    """Classify Q-M1 from the ordered markers `sent`, `processed` and `turn_end`.

    `injected_mid_turn` means the message was consumed before the turn it was sent into ended;
    `queued_until_turn_end` means that turn ended first and the message started the next one.
    """
    if "sent" not in timeline:
        return "not_sent"
    after_send = list(timeline[timeline.index("sent") + 1 :])
    if "processed" not in after_send:
        return "not_observed"
    processed_at = after_send.index("processed")
    turn_end_at = after_send.index("turn_end") if "turn_end" in after_send else len(after_send)
    return "injected_mid_turn" if processed_at < turn_end_at else "queued_until_turn_end"


def agents_md_verdict(*, canary_in_answer: bool, commands_run: int) -> str:
    """Classify Q-O2: was a workspace AGENTS.md in the harness context without any tool use?"""
    if not canary_in_answer:
        return "not_honoured"
    return "honoured_in_context" if commands_run == 0 else "read_with_tools"


def gpt_6_luna_cost_usd(
    *, input_tokens: int, cached_tokens: int, output_tokens: int, container_minutes: float
) -> float:
    """Estimate from research/openai-hosted-agents.md §6: token rates plus a small container.

    The Agents API reports tokens only, so this stays an estimate, never a settled cost.
    """
    uncached = max(input_tokens - cached_tokens, 0)
    tokens = (uncached * 0.10 + cached_tokens * 0.01 + output_tokens * 0.50) / 1_000_000
    container = max(container_minutes, 5.0) * 0.03 / 20
    return round(tokens + container, 6)


def retry_on_conflict(
    action: Callable[[], object], *, attempts: int = 10, delay_s: float = 1.0
) -> object:
    """Retry an HTTP 409 (busy or changed resource); any other error, or the last 409, raises."""
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except Exception as exc:
            if getattr(exc, "status_code", None) != 409 or attempt == attempts:
                raise
            time.sleep(delay_s)
    raise AssertionError("unreachable")


@dataclass
class SmokeRecord:
    """Evidence written to JSON: ids, statuses, event names, usage and verdicts; never text."""

    provider: str
    sdk: str
    model: str
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    resources: dict[str, str] = field(default_factory=dict)
    statuses: list[str] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)
    sequence: list[str] = field(default_factory=list)
    findings: dict[str, object] = field(default_factory=dict)
    usage: dict[str, object] = field(default_factory=dict)
    cleanup: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def created(self, kind: str, resource_id: str) -> None:
        self.resources[kind] = resource_id
        self.status(kind, resource_id, "created")

    def status(self, step: str, resource_id: str, status: str) -> None:
        line = f"{step} {resource_id} {status}"
        self.statuses.append(line)
        print(line, flush=True)

    def saw(self, event_type: str) -> None:
        """Count the event and extend the ordered sequence, collapsing runs (text deltas)."""
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1
        if not self.sequence or self.sequence[-1] != event_type:
            self.sequence.append(event_type)

    def error(self, step: str, exc: BaseException) -> None:
        """Keep the error class, HTTP status and message, with key-shaped fragments scrubbed."""
        status = getattr(exc, "status_code", None)
        message = _KEY_LIKE.sub("[redacted]", str(exc))
        detail = f"{step}: {type(exc).__name__}" + (f" {status}" if status else "") + f": {message}"
        self.errors.append(detail)
        print(f"{step} - error {type(exc).__name__}" + (f" {status}" if status else ""))

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, default=str) + "\n", encoding="utf-8")


class CleanupLedger:
    """Delete or archive every created resource in reverse order, recording each outcome."""

    def __init__(self, record: SmokeRecord) -> None:
        self._record = record
        self._actions: list[tuple[str, str, str, Callable[[], object]]] = []

    def add(self, kind: str, resource_id: str, verb: str, action: Callable[[], object]) -> None:
        self._actions.append((kind, resource_id, verb, action))

    def run(self) -> None:
        while self._actions:
            kind, resource_id, verb, action = self._actions.pop()
            try:
                action()
            except Exception as exc:  # recorded per resource; cleanup continues
                outcome = f"{verb} failed: {type(exc).__name__}"
                self._record.error(f"cleanup {kind}", exc)
            else:
                outcome = verb
            self._record.cleanup[f"{kind} {resource_id}"] = outcome
            self._record.status(f"cleanup {kind}", resource_id, outcome)
