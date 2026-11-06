"""`codex_agents` cognition points: one `thread_item` point per step of an Agents API turn.

Identity (DESIGN cross-provider-control section 5): `thread_ref` is the Agents session id and
`item_ref` is `<turn_id>#<item_id>`, so the locator reads `session#turn#item` like a session
cursor's `session#turn#step` and a point names its turn without the kernel's turn ledger.
The item id comes from the frame key `agents:<turn>:item~<item id>` the lane stores every
durable item under (live or recovered, one key); the terminal record is item `done`; a
live event without an item (an environment or status notification) is keyed by its event
id, and an id-less event falls back to the kernel's `<arrival_ordinal>:<kind>`.

Boundaries are the kernel `STEP_KINDS` as `application/frames/kinds.py` classifies the
notifications: every `agent.session.turn.item.done` (a `message` item is a `message` frame,
the user one being the turn's `input`; any other completed item a `tool_call_completed`),
the turn's terminal (`agent.session.turn.{completed,failed,cancelled}`, or the synthesized
`turn.final`) and a session or environment failure (`error`).

Usage: the Agents API reports tokens per turn on the turn record (`turn.usage`), not per
item, so the result point carries the turn's usage (`tokens.<name>`) and the intermediate
points none. Cost is never reported (the lane's describe says `cost: unknown`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from mission_control.adapters.openai_agents import frames as agents
from mission_control.adapters.remote_session.cognition_points import (
    HostedPointRules,
    bounded_text,
    frame_body,
)
from mission_control.application.execution.harness.points import default_step_ref
from mission_control.domain.execution.cognition_points import (
    CognitionPointRef,
    ThreadItemPoint,
)
from mission_control.domain.frames.contracts import ProviderFrame

KEY_PREFIX: Final = "agents"
ITEM_MARK: Final = "item~"
DONE_STEP: Final = "done"


def step_ref_of(frame: ProviderFrame, turn_ref: str) -> str:
    """The native step reference of a stored Agents frame (see the module doc)."""

    prefix = f"{KEY_PREFIX}:{turn_ref}:"
    if frame.provider_key.startswith(prefix):
        rest = frame.provider_key.removeprefix(prefix)
        if rest.startswith(ITEM_MARK):
            return rest.removeprefix(ITEM_MARK)[:256]
        if rest:
            return rest[:256]
    return default_step_ref(frame)


def item_ref(turn_ref: str, step_ref: str) -> str:
    return f"{turn_ref}#{step_ref}"[:512]


def split_item_ref(value: str) -> tuple[str, str]:
    """`(turn_id, item_id)` of an `item_ref` this module wrote."""

    turn, _separator, item = value.partition("#")
    return turn, item


def point_for(frame: ProviderFrame, session_ref: str, turn_ref: str) -> CognitionPointRef:
    return ThreadItemPoint(
        thread_ref=session_ref[:512], item_ref=item_ref(turn_ref, step_ref_of(frame, turn_ref))
    )


def terminal_usage(frame: ProviderFrame) -> Mapping[str, int]:
    """`turn.usage` of the terminal record (`tokens.<name>`); nothing when unreported."""

    turn = agents.mapping(frame_body(frame).get("turn"))
    usage = agents.mapping(turn.get("usage"))
    return {
        f"tokens.{name}": value
        for name, value in usage.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def facts_of(frame: ProviderFrame) -> Mapping[str, Any]:
    body = frame_body(frame)
    facts: dict[str, Any] = {}
    event_id = body.get("event_id")
    if event_id:
        facts["event_id"] = str(event_id)[:256]
    item = agents.mapping(body.get("item"))
    if item:
        facts["item_id"] = bounded_text(item.get("id"), 256)
        facts["item_type"] = bounded_text(item.get("type"), 64)
        for name in ("role", "phase", "status"):
            value = bounded_text(item.get(name), 64)
            if value:
                facts[f"item_{name}"] = value
        if body.get("recovered"):
            facts["recovered"] = True
    turn = agents.mapping(body.get("turn"))
    if turn.get("status"):
        facts["turn_status"] = bounded_text(turn.get("status"), 32)
    return facts


def is_input(frame: ProviderFrame) -> bool:
    item = agents.mapping(frame_body(frame).get("item"))
    return item.get("type") == "message" and item.get("role") == "user"


AGENTS_POINT_RULES: Final = HostedPointRules(
    point_for=point_for,
    usage_of=None,
    facts_of=facts_of,
    is_input=is_input,
    terminal_usage=terminal_usage,
)

__all__ = [
    "AGENTS_POINT_RULES",
    "DONE_STEP",
    "KEY_PREFIX",
    "facts_of",
    "is_input",
    "item_ref",
    "point_for",
    "split_item_ref",
    "step_ref_of",
    "terminal_usage",
]
