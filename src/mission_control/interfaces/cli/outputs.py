"""`missionctl outputs`: exact output, fulfillment and transfer inspection (WI-19 / OVE-182).

``outputs show RUN`` prints the run's promises, accepted revisions, fulfillment, assessments,
transfer plans and actionable items; ``outputs revisions RUN KEY [--cursor C]`` one promise's
history; ``outputs events RUN [--cursor C]`` the output/transfer transitions; ``outputs plans
RUN`` the sealed plans and ``outputs plan PLAN_ID`` one plan with its attempt receipts. Every
command is one JSON document on stdout over the same HTTP handlers as the operator MCP.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Protocol

import httpx

from mission_control.interfaces.cli.exits import exit_status


class OutputsClient(Protocol):
    def outputs_read(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response: ...

    def quoted(self, value: str) -> str: ...


def add_output_parsers(groups: Any, common: argparse.ArgumentParser) -> None:
    outputs = groups.add_parser("outputs", parents=[common], help="exact output inspection")
    actions = outputs.add_subparsers(dest="action", required=True)
    show = actions.add_parser("show", parents=[common])
    show.add_argument("run_id")
    revisions = actions.add_parser("revisions", parents=[common])
    revisions.add_argument("run_id")
    revisions.add_argument("obligation_key")
    revisions.add_argument("--cursor")
    revisions.add_argument("--limit", type=int, default=50)
    events = actions.add_parser("events", parents=[common])
    events.add_argument("run_id")
    events.add_argument("--cursor")
    events.add_argument("--limit", type=int, default=100)
    plans = actions.add_parser("plans", parents=[common])
    plans.add_argument("run_id")
    plan = actions.add_parser("plan", parents=[common])
    plan.add_argument("plan_id")


def run_outputs(client: OutputsClient, args: argparse.Namespace) -> int:
    params: dict[str, Any] = {}
    if args.action == "show":
        path = f"runs/{client.quoted(args.run_id)}/outputs"
    elif args.action == "revisions":
        path = (
            f"runs/{client.quoted(args.run_id)}/outputs/"
            f"{client.quoted(args.obligation_key)}/revisions"
        )
        params = {"limit": args.limit, **({"cursor": args.cursor} if args.cursor else {})}
    elif args.action == "events":
        path = f"runs/{client.quoted(args.run_id)}/output-events"
        params = {"limit": args.limit, **({"cursor": args.cursor} if args.cursor else {})}
    elif args.action == "plans":
        path = f"runs/{client.quoted(args.run_id)}/transfer-plans"
    else:
        path = f"transfer-plans/{client.quoted(args.plan_id)}"
    response = client.outputs_read(path, params)
    try:
        document: Any = response.json()
    except ValueError:
        document = {"error": "non-JSON service response", "status": response.status_code}
    print(json.dumps(document, allow_nan=False, ensure_ascii=False))
    return exit_status(response.status_code)


__all__ = ["OutputsClient", "add_output_parsers", "run_outputs"]
