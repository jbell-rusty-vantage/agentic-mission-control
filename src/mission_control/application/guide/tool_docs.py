"""The full documentation of the tools whose listing description is short.

A tool listing is read on every session, so a tool's description there stays short: its
purpose, its required fields, where it helps one example. The rest lives here and is read on
demand with `tool:<name>`: the JSON schema of the request model the HTTP route validates the
same object with (where one exists), the notes (`tools/<name>.md`) and one valid example. The
notes are the documentation that used to be in the tool descriptions, moved, not rewritten;
a tool whose arguments the listing types in full has notes and a minimal call only.

`tests/unit/guide/` holds every entry to the surface: each name is a tool of the operator
server, each example validates against its model, and every tool that takes an object the
listing does not type has an entry here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from pydantic import BaseModel

from mission_control.application.execution.approvals_governed import GovernedPrepareRequest
from mission_control.application.guide.pages import PageSource, load_page
from mission_control.application.subscriptions.coordinator import CoordinatorProfile
from mission_control.contracts.contracts import MissionCommandRequest
from mission_control.contracts.runtime_contracts import MissionForkRequest

_RUN: Final = "<run_id>"


@dataclass(frozen=True, slots=True)
class ToolDoc:
    """One tool's request: `argument` is the object argument the notes document (`None`: the
    model is the whole call) and `model` the request model behind it. `example` validates
    against `model`; without a model it is a minimal call."""

    argument: str | None
    model: type[BaseModel] | None
    example: dict[str, Any]


TOOL_DOCS: Final[dict[str, ToolDoc]] = {
    "mission_command_send": ToolDoc(
        argument="request",
        model=MissionCommandRequest,
        example={
            "request_id": "0b8f6c1e-5d1a-4c57-9d0e-2f6a3b7c8d90",
            "expected_version": 7,
            "expected_generation": 1,
            "target": {"kind": "run", "id": _RUN},
            "kind": "queue_instruction",
            "payload": {"content": {"text": "Cite every source."}},
            "reason": "operator steer",
        },
    ),
    "coordinator_inbox_command": ToolDoc(
        argument="command",
        model=MissionCommandRequest,
        example={
            "request_id": "9a7b6c5d-4e3f-4a2b-8c1d-0e9f8a7b6c5d",
            "expected_version": 7,
            "expected_generation": 1,
            "target": {"kind": "run", "id": _RUN},
            "kind": "cancel",
            "payload": {"urgency": "normal"},
            "reason": "the run failed its review",
        },
    ),
    "mission_run_fork": ToolDoc(
        argument="request",
        model=MissionForkRequest,
        example={
            "request_id": "5c2d9a40-7e1b-4f0a-8b6c-3d4e5f6a7b80",
            "sponsorship_ref": "<your sponsorship>",
            "reason": "explore a stricter review",
        },
    ),
    "mission_governed_prepare": ToolDoc(
        argument=None,
        model=GovernedPrepareRequest,
        example={
            "tool_name": "repo_pr",
            "arguments": {
                "repository": "...",
                "branch": "mc/<run>/<unit>",
                "base": "main",
                "title": "...",
                "body": "...",
            },
            "run_id": _RUN,
            "harness_execution_id": "<harness_execution_id>",
            "generation": 1,
            "lane_profile": "deep_agents",
        },
    ),
    "mission_governed_execute": ToolDoc(
        argument="arguments",
        model=None,
        example={"intent_id": "<intent_id>"},
    ),
    "coordinator_inbox_subscribe": ToolDoc(
        argument="profile",
        model=CoordinatorProfile,
        example={"kinds": ["terminal_result", "blocked", "review_required", "failed"]},
    ),
    # The tools whose listing description was shortened to fit the listing's token ceiling:
    # their whole documentation is the notes, and the listing types their arguments, so each
    # entry is a minimal call (`model` is None).
    "coordinator_inbox_observe": ToolDoc(
        argument=None,
        model=None,
        example={
            "subscription_id": "<subscription_id>",
            "notification_id": "<notification_id>",
            "observation": {
                "stage": "visible",
                "channel": "tool_result",
                "delivery_nonce": "<delivery_nonce of the delivered page>",
                "observation_key": "<an id you choose>",
                "observed_at": "2026-01-01T00:00:00Z",
            },
        },
    ),
    "knowledge_review": ToolDoc(
        argument=None,
        model=None,
        example={
            "run_id": _RUN,
            "request": {
                "decision": {"kind": "use_decision", "id": "<id>", "version": 1},
                "outcome": "approve",
                "bound_effect_digest": "sha256:<64 hex>",
                "rationale": "the cited sources support the claim",
            },
        },
    ),
    "mission_approval_resolve": ToolDoc(
        argument=None,
        model=None,
        example={
            "human_task_id": "<human_task_id>",
            "request": {
                "request_id": "<an id you choose>",
                "expected_task_version": 1,
                "reviewed_digest": "sha256:<the task's packet_digest>",
                "decision": "approve",
                "answer": "Use the staging database.",
            },
        },
    ),
    "mission_governed_status": ToolDoc(
        argument=None, model=None, example={"intent_id": "<intent_id>"}
    ),
    "mission_human_task_get": ToolDoc(
        argument=None, model=None, example={"human_task_id": "<human_task_id>"}
    ),
    "mission_human_task_list": ToolDoc(
        argument=None, model=None, example={"run_id": _RUN, "lifecycle": "open"}
    ),
    "mission_human_task_resolve": ToolDoc(
        argument=None,
        model=None,
        example={
            "human_task_id": "<human_task_id>",
            "request": {
                "request_id": "<an id you choose>",
                "expected_task_version": 1,
                "reviewed_packet_digest": "sha256:<the task's packet_digest>",
                "decision": "approve",
            },
        },
    ),
    "mission_run_inspect": ToolDoc(argument=None, model=None, example={"run_id": _RUN}),
    "mission_run_list": ToolDoc(
        argument=None, model=None, example={"query": "phase='executing'", "limit": 20}
    ),
    "mission_run_points": ToolDoc(
        argument=None, model=None, example={"run_id": _RUN, "seedable": True, "limit": 20}
    ),
    "mission_run_points_reconcile": ToolDoc(argument=None, model=None, example={"run_id": _RUN}),
    "mission_run_replay": ToolDoc(
        argument=None, model=None, example={"run_id": _RUN, "point_id": "<point_id>"}
    ),
    "mission_run_state_as_of": ToolDoc(
        argument=None, model=None, example={"run_id": _RUN, "point_id": "<point_id>"}
    ),
    "mission_run_transcript": ToolDoc(
        argument=None, model=None, example={"run_id": _RUN, "limit": 20}
    ),
}


def tool_notes(tool: str) -> PageSource:
    """The field notes of one documented tool (`KeyError` for a tool without an entry)."""

    if tool not in TOOL_DOCS:
        raise KeyError(tool)
    return load_page("tools", tool)


def tool_document(tool: str) -> dict[str, Any]:
    """What `tool:<name>` answers with: argument, notes, request schema and example."""

    doc = TOOL_DOCS[tool]
    document: dict[str, Any] = {
        "tool": tool,
        "argument": doc.argument,
        "notes": tool_notes(tool).body,
        "example": doc.example,
    }
    if doc.model is not None:
        document["schema"] = request_schema(doc.model)
    return document


def request_schema(model: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON schema without the generated titles (each repeats its field's name)."""

    return untitled_schema(model.model_json_schema())


def untitled_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """A JSON schema without its generated titles (a tool listing's argument schema too)."""

    stripped: dict[str, Any] = _untitled(dict(schema))
    return stripped


def _untitled(node: Any) -> Any:
    if isinstance(node, dict):
        # A generated title is a string; a property that is named `title` is a schema.
        return {
            key: _untitled(value)
            for key, value in node.items()
            if not (key == "title" and isinstance(value, str))
        }
    if isinstance(node, list):
        return [_untitled(item) for item in node]
    return node


__all__ = [
    "TOOL_DOCS",
    "ToolDoc",
    "request_schema",
    "tool_document",
    "tool_notes",
    "untitled_schema",
]
