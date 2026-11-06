"""`missionctl knowledge review`: an operator's review of one exact KS use decision (W1 D2).

``knowledge review RUN --decision-file FILE --outcome approve|hold|reject --bound-effect-digest D
[--qualifiers-digest D] --rationale TEXT`` posts the same body the HTTP route and the operator
MCP ``knowledge_review`` tool take and prints the one JSON document it answers. The decision
file holds the exact ``use_decision`` Ref the run's settlement waits on (``review_pending``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Protocol

import httpx

from mission_control.interfaces.cli.exits import exit_status


class KnowledgeClient(Protocol):
    def knowledge_review(self, run_id: str, body: dict[str, Any]) -> httpx.Response: ...


def add_knowledge_parsers(groups: Any, common: argparse.ArgumentParser) -> None:
    knowledge = groups.add_parser("knowledge", parents=[common], help="knowledge reviews")
    actions = knowledge.add_subparsers(dest="action", required=True)
    review = actions.add_parser("review", parents=[common])
    review.add_argument("run_id")
    review.add_argument("--decision-file", dest="decision_file", required=True)
    review.add_argument("--outcome", required=True, choices=("approve", "hold", "reject"))
    review.add_argument("--bound-effect-digest", dest="bound_effect_digest", required=True)
    review.add_argument("--qualifiers-digest", dest="qualifiers_digest")
    review.add_argument("--rationale", required=True)


def run_knowledge(client: KnowledgeClient, args: argparse.Namespace) -> int:
    try:
        decision = json.loads(Path(args.decision_file).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(json.dumps({"error": "decision file unreadable", "detail": type(error).__name__}))
        return 2
    body: dict[str, Any] = {
        "decision": decision,
        "outcome": args.outcome,
        "bound_effect_digest": args.bound_effect_digest,
        "qualifiers_digest": args.qualifiers_digest,
        "rationale": args.rationale,
    }
    response = client.knowledge_review(args.run_id, body)
    try:
        document: Any = response.json()
    except ValueError:
        document = {"error": "non-JSON service response", "status": response.status_code}
    print(json.dumps(document, allow_nan=False, ensure_ascii=False))
    return exit_status(response.status_code)


__all__ = ["KnowledgeClient", "add_knowledge_parsers", "run_knowledge"]
