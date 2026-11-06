"""`missionctl wait` and `missionctl inbox`: the W1 wake channel (SPEC-04 §6, ADR-0049).

``missionctl wait --run RUN [--kinds terminal_result,blocked,review_required] [--wait S]``
long-polls the caller's coordinator inbox over the run (the one a launch subscribed, or a new
one replaying the run's journal from the start, so a run that already ended still wakes it).
Each matching notification prints as one JSON line on stdout; the inbox used is reported on
stderr. It exits 0 after the first matching notifications, or 6 when the deadline passes first
(the general CLI's wait-timeout code). ``--follow`` keeps printing until the deadline and exits
0 if it printed anything. Nothing is acknowledged unless ``--ack`` is given: acknowledgement is
explicit (``missionctl inbox ack``), and an unacknowledged notification is printed again by the
next one-shot wait.

Under Claude Code, run ``missionctl wait`` as a background task (its exit is the wake-up) or
``--follow`` under the Monitor tool; Codex and Cursor orchestrators call it between turns.

WI-19 (OUTPUT-CONTRACTS §12): each printed line carries the ``delivery_nonce`` of that delivery
(it exists only in this output; and, for an inbox that opted into bounded content, its
``content`` excerpts). The six delivery stages are recorded separately: the wait's HTTP answer
is the transport; the host then attests ``missionctl inbox observe ID --id N --stage wake
--nonce <delivery_nonce> ...`` (idle since, woken by the background task's exit) and then
``--stage visible`` (the payload reached the model), acknowledges with ``inbox ack``, retrieves
with ``inbox content`` and reads the verdicts with ``inbox attention``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx

from mission_control.interfaces.cli.exits import WAIT_TIMEOUT, exit_status

DEFAULT_WAIT_SECONDS = 3600.0
LONG_POLL_SECONDS = 60.0
TRANSPORT_GRACE_SECONDS = 15.0


class InboxClient(Protocol):
    """The coordinator-inbox calls of `MissionClient` this module uses."""

    def inboxes(self, target: str, target_id: str) -> httpx.Response: ...

    def create_inbox(self, body: dict[str, Any]) -> httpx.Response: ...

    def inbox_notifications(
        self, subscription_id: str, params: dict[str, Any], *, timeout: float
    ) -> httpx.Response: ...

    def ack_inbox(self, subscription_id: str, body: dict[str, Any]) -> httpx.Response: ...

    def observe_inbox(
        self, subscription_id: str, notification_id: str, body: dict[str, Any]
    ) -> httpx.Response: ...

    def inbox_content(
        self, subscription_id: str, notification_id: str, body: dict[str, Any]
    ) -> httpx.Response: ...

    def inbox_attention(self, subscription_id: str, params: dict[str, Any]) -> httpx.Response: ...


def add_wait_parsers(groups: Any, common: argparse.ArgumentParser) -> None:
    """Register `wait` and `inbox {list,ack}` on missionctl's subcommand groups."""

    wait = groups.add_parser("wait", parents=[common], help="block until the inbox wakes you")
    _add_target(wait)
    wait.add_argument("--kinds", help="comma-separated notification kinds (default: all)")
    wait.add_argument("--follow", action="store_true", help="stream until the deadline")
    wait.add_argument("--ack", action="store_true", help="acknowledge what is printed")
    wait.add_argument("--after-inbox-seq", type=int, dest="after_inbox_seq")
    inbox = groups.add_parser("inbox", parents=[common])
    inbox_commands = inbox.add_subparsers(dest="action", required=True)
    listing = inbox_commands.add_parser("list", parents=[common])
    target = listing.add_mutually_exclusive_group(required=True)
    target.add_argument("--run")
    target.add_argument("--mission")
    ack = inbox_commands.add_parser("ack", parents=[common])
    ack.add_argument("subscription_id")
    ack.add_argument("--id", action="append", dest="notification_ids", default=[])
    ack.add_argument("--through", type=int, dest="through_inbox_seq")
    # WI-19: the host-reported stages, explicit bounded retrieval and the six-stage report.
    observe = inbox_commands.add_parser("observe", parents=[common])
    observe.add_argument("subscription_id")
    observe.add_argument("--id", required=True, dest="notification_id")
    observe.add_argument("--stage", required=True, choices=("wake", "visible"))
    observe.add_argument(
        "--channel",
        help="wake: background_task_exit|monitor_event|session_prompt|connected_poll; "
        "visible: task_output|tool_result|session_prompt",
    )
    observe.add_argument(
        "--nonce", required=True, dest="nonce", help="the delivery_nonce your delivery carried"
    )
    observe.add_argument("--key", dest="observation_key", help="idempotency key (default stage)")
    observe.add_argument("--idle-since", dest="idle_since", help="ISO time the host went idle")
    observe.add_argument("--at", dest="observed_at", help="ISO time observed (default now)")
    observe.add_argument("--host-ref", dest="host_ref", default="missionctl")
    observe.add_argument(
        "--evidence", action="append", default=[], help="key=value (repeatable, short scalars)"
    )
    content = inbox_commands.add_parser("content", parents=[common])
    content.add_argument("subscription_id")
    content.add_argument("--id", required=True, dest="notification_id")
    content.add_argument("--obligation", action="append", required=True, dest="obligations")
    content.add_argument("--max-excerpt-chars", type=int, dest="max_excerpt_chars", default=1000)
    content.add_argument("--max-total-chars", type=int, dest="max_total_chars", default=4000)
    attention = inbox_commands.add_parser("attention", parents=[common])
    attention.add_argument("subscription_id")
    attention.add_argument("--after-inbox-seq", type=int, dest="after_inbox_seq", default=0)
    attention.add_argument("--limit", type=int, default=50)


def _add_target(parser: argparse.ArgumentParser) -> None:
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--run")
    target.add_argument("--mission")
    target.add_argument("--inbox", help="an existing coordinator inbox subscription id")


def _target(args: argparse.Namespace) -> tuple[str, str]:
    if getattr(args, "run", None):
        return "run", str(args.run)
    return "mission", str(args.mission)


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {"error": "non-JSON service response", "status": response.status_code}
    return value if isinstance(value, dict) else {"result": value}


def _fail(response: httpx.Response) -> int:
    """Report a refused request on stderr; its missionctl exit code."""

    print(json.dumps(_json(response), allow_nan=False), file=sys.stderr)
    return exit_status(response.status_code)


def resolve_inbox(client: InboxClient, args: argparse.Namespace) -> tuple[str | None, int]:
    """The subscription id to wait on: `--inbox`, else the caller's inbox over the target."""

    if getattr(args, "inbox", None):
        return str(args.inbox), 0
    target, target_id = _target(args)
    found = client.inboxes(target, target_id)
    if exit_status(found.status_code):
        return None, _fail(found)
    inboxes = _json(found).get("inboxes") or []
    if inboxes:
        chosen, created = str(inboxes[0]["subscription_id"]), False
    else:
        response = client.create_inbox({"target": target, "target_id": target_id, "after_seq": 0})
        if exit_status(response.status_code):
            return None, _fail(response)
        chosen, created = str(_json(response)["subscription_id"]), True
    print(json.dumps({"inbox": chosen, "created": created}), file=sys.stderr, flush=True)
    return chosen, 0


def run_wait(client: InboxClient, args: argparse.Namespace, deadline_seconds: float | None) -> int:
    """`missionctl wait`: long-poll until matching notifications are pending (see module)."""

    subscription_id, status = resolve_inbox(client, args)
    if subscription_id is None:
        return status
    deadline = time.monotonic() + (deadline_seconds or DEFAULT_WAIT_SECONDS)
    after: int | None = getattr(args, "after_inbox_seq", None)
    printed = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if printed:
                return 0
            print(json.dumps({"error": "wait_timeout", "inbox": subscription_id}), file=sys.stderr)
            return WAIT_TIMEOUT
        chunk = min(remaining, LONG_POLL_SECONDS)
        params: dict[str, Any] = {"wait": round(chunk, 3)}
        if args.kinds:
            params["kinds"] = args.kinds
        if after is not None:
            params["after_inbox_seq"] = after
        response = client.inbox_notifications(
            subscription_id, params, timeout=chunk + TRANSPORT_GRACE_SECONDS
        )
        if exit_status(response.status_code):
            return _fail(response)
        page = _json(response)
        notifications = page.get("notifications") or []
        nonces = page.get("delivery_nonces") or {}
        contents = page.get("content") or {}
        for notification in notifications:
            line = dict(notification)
            nid = str(notification.get("notification_id"))
            if nid in nonces:
                line["delivery_nonce"] = nonces[nid]
            if nid in contents:
                line["content"] = contents[nid]
            print(json.dumps(line, allow_nan=False, ensure_ascii=False), flush=True)
        printed += len(notifications)
        if notifications:
            after = max(int(item["inbox_seq"]) for item in notifications)
            if args.ack:
                acked = client.ack_inbox(
                    subscription_id,
                    {"notification_ids": [item["notification_id"] for item in notifications]},
                )
                if exit_status(acked.status_code):
                    return _fail(acked)
            if not args.follow:
                return 0


def observation_body(args: argparse.Namespace) -> dict[str, Any]:
    """`mc.coordinator_host_observation.v1` from `inbox observe` arguments."""

    now = datetime.now(UTC).isoformat()
    evidence: dict[str, Any] = {}
    for item in args.evidence:
        key, separator, value = str(item).partition("=")
        if not separator:
            raise ValueError("--evidence is key=value")
        evidence[key] = value
    channel = args.channel or ("background_task_exit" if args.stage == "wake" else "task_output")
    body: dict[str, Any] = {
        "stage": args.stage,
        "channel": channel,
        "observation_key": args.observation_key or f"{args.stage}-1",
        "delivery_nonce": args.nonce,
        "observed_at": args.observed_at or now,
        "host_ref": args.host_ref,
        "evidence": evidence,
    }
    if args.stage == "wake":
        if not args.idle_since:
            raise ValueError("a wake observation needs --idle-since (when the host went idle)")
        body["idle_since"] = args.idle_since
    return body


def run_inbox(client: InboxClient, args: argparse.Namespace) -> int:
    """`missionctl inbox list|ack|observe|content|attention` (see the module docstring)."""

    if args.action == "list":
        response = client.inboxes(*_target(args))
    elif args.action == "observe":
        response = client.observe_inbox(
            args.subscription_id, args.notification_id, observation_body(args)
        )
    elif args.action == "content":
        response = client.inbox_content(
            args.subscription_id,
            args.notification_id,
            {
                "obligations": list(args.obligations),
                "max_excerpt_chars": args.max_excerpt_chars,
                "max_total_chars": args.max_total_chars,
            },
        )
    elif args.action == "attention":
        response = client.inbox_attention(
            args.subscription_id,
            {"after_inbox_seq": args.after_inbox_seq, "limit": args.limit},
        )
    else:
        if not args.notification_ids and args.through_inbox_seq is None:
            raise ValueError("inbox ack needs --id NOTIFICATION_ID or --through INBOX_SEQ")
        body: dict[str, Any] = {"notification_ids": list(args.notification_ids)}
        if args.through_inbox_seq is not None:
            body["through_inbox_seq"] = args.through_inbox_seq
        response = client.ack_inbox(args.subscription_id, body)
    print(json.dumps(_json(response), allow_nan=False))
    return exit_status(response.status_code)


__all__ = [
    "InboxClient",
    "add_wait_parsers",
    "observation_body",
    "resolve_inbox",
    "run_inbox",
    "run_wait",
]
