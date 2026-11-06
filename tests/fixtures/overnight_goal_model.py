"""Bounded two-iteration cognition; normal tools and host settlement retain authority.

The integration supplies producer-authored candidates and exact compiled contract refs.
This helper neither promotes outputs nor writes evaluator/fulfillment records.
"""

from __future__ import annotations

import ast
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tests.fixtures.overnight_stagegraph_model import _document
from tests.fixtures.rrm009_production_stack import _LoggedModel, call_usage

from mission_control.domain.programs.goal_directed_runtime import (
    GoalNamedExecutorObservation,
    GoalVerifierObservation,
)


def goal_context(content: str) -> tuple[str, int] | None:
    """Read the current continuation's root keys, never prior nested handoffs."""
    for start, character in enumerate(content):
        if character != "{":
            continue
        depth, quote, escaped = 0, None, False
        for end in range(start, len(content)):
            character = content[end]
            if quote is not None:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == quote:
                    quote = None
            elif character in ("'", '"'):
                quote = character
            elif character == "{":
                depth += 1
            elif character == "}":
                depth -= 1
                if depth == 0:
                    try:
                        expression = ast.parse(content[start : end + 1], mode="eval").body
                        value = (
                            {
                                ast.literal_eval(key): ast.literal_eval(value)
                                for key, value in zip(
                                    expression.keys, expression.values, strict=True
                                )
                                if isinstance(key, ast.Constant)
                                and key.value in ("operation_role", "goal_iteration")
                            }
                            if isinstance(expression, ast.Dict)
                            else {}
                        )
                    except (ValueError, SyntaxError):
                        break
                    if isinstance(value, dict):
                        role = value.get("operation_role")
                        iteration = value.get("goal_iteration")
                        if role in ("executor", "verifier") and type(iteration) is int:
                            return role, iteration
                    break
    return None


HANDLE = re.compile(r'(kh:[^\s"\\#]+)#digest=(sha256:[0-9a-f]{64})')


@dataclass
class GoalScript:
    candidates: tuple[dict[str, Any], dict[str, Any]]
    feedback: str
    accept_final: bool = True
    errors: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)
    reads: list[dict[str, Any]] = field(default_factory=list)
    contexts: list[dict[str, Any]] = field(default_factory=list)
    registered: dict[int, dict[str, str]] = field(default_factory=dict)
    output_contract_ref: str = ""
    obligation_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        first, second = (candidate["report"] for candidate in self.candidates)
        assert first["reportId"] == second["reportId"], "repair must retain report identity"
        assert second["revision"] == first["revision"] + 1, "repair requires successor revision"
        assert self.feedback, "full actionable feedback is required"
        for key in ("assertions", "supportSets"):
            old = {row["id"] for row in self.candidates[0][key]}
            new = {row["id"] for row in self.candidates[1][key]}
            assert old.isdisjoint(new), "immutable candidate member IDs must differ"


class GoalModel(_LoggedModel):
    script: Any
    # Must come from the compiled binding, not the historical RRM-016 constants.
    output_contract_ref: str
    obligation_refs: tuple[str, ...]

    @property
    def _llm_type(self) -> str:
        return "overnight-scripted-goal-directed"

    def _reply(self, messages: list[BaseMessage]) -> ChatResult:
        try:
            return self._respond(messages)
        except AssertionError as error:
            self.script.errors.append(
                {
                    "type": type(error).__name__,
                    "message": str(error),
                    "operation_id": self.operation_id,
                    "received": [
                        {"type": message.type, "content": message.content} for message in messages
                    ],
                }
            )
            raise

    def _respond(self, messages: list[BaseMessage]) -> ChatResult:
        self._record("parent", messages)
        contexts = [
            (index, str(message.content))
            for index, message in enumerate(messages)
            if message.type == "human" and goal_context(str(message.content)) is not None
        ]
        assert contexts, "actual goal context missing"
        start, context = contexts[-1]
        current = goal_context(context)
        assert current is not None
        role, iteration = current
        received = "\n".join(
            str(message.content) for message in messages if message.type == "human"
        )
        assert iteration in (1, 2), "fixture exceeded its two-iteration bound"
        assert self.output_contract_ref and self.obligation_refs
        if iteration == 2 and role == "executor":
            assert self.script.feedback in received, (
                "successor requires actual full feedback delivery"
            )
        self.script.contexts.append(
            {
                "role": role,
                "iteration": iteration,
                "operation_id": self.operation_id,
                "run_id": self.run_id,
                "received": received,
                "continuation": context,
            }
        )
        tools = [message for message in messages[start:] if isinstance(message, ToolMessage)]
        if role == "executor":
            return self._producer(iteration, tools)
        return self._verifier(iteration, tools)

    def _producer(self, iteration: int, tools: list[ToolMessage]) -> ChatResult:
        if not tools:
            candidate = deepcopy(self.script.candidates[iteration - 1])
            if iteration == 2:
                assert 1 in self.script.registered, (
                    "successor requires observed predecessor receipt"
                )
                candidate["report"]["supersedes"] = dict(self.script.registered[1])
            else:
                assert candidate["report"].get("supersedes") is None
            return self._call(
                "report_register",
                {"report": candidate},
                iteration,
                "executor",
                0,
            )
        registered = _document(tools[0])
        assert registered.get("ok"), registered
        affected = registered["result"]["affected"]
        reports = [row for row in affected if "/report/" in row["handle"]]
        assert len(reports) == 1, "registration must return one exact report handle"
        report = reports[0]
        exact = {"handle": report["handle"], "digest": report["digest"]}
        previous = self.script.registered.setdefault(iteration, exact)
        assert previous == exact, "registration replay changed exact candidate reference"
        if iteration == 2:
            assert exact != self.script.registered[1], "successor reused predecessor reference"
        if len(tools) == 1:
            return self._call(
                "submit_output",
                {
                    "obligation": "root.report",
                    "items": [
                        {"kind": "handle", "ref": report["handle"], "digest": report["digest"]}
                    ],
                },
                iteration,
                "executor",
                1,
            )
        assert _document(tools[-1]).get("ok"), tools[-1].content
        if len(tools) == 2:
            return self._call(
                "submit_output",
                {
                    "obligation": "root.progress_note",
                    "items": [
                        {
                            "kind": "inline",
                            "text": f"Candidate revision {iteration} submitted for review.",
                        }
                    ],
                },
                iteration,
                "executor",
                2,
            )
        observation = GoalNamedExecutorObservation(
            disposition="completed",
            # Named submission receipts, not provider-invented artifact references,
            # are the host's authority for these output obligations.
            output_refs=(),
            output_bindings={},
            completion_claim=iteration == 2,
            output_contract_ref=self.output_contract_ref,
        )
        return self._answer(observation.model_dump(mode="json"))

    def _verifier(self, iteration: int, tools: list[ToolMessage]) -> ChatResult:
        if not tools:
            return self._call(
                "read_file", {"file_path": "/.mission/transfer.json"}, iteration, "verifier", 0
            )
        selected = list(dict.fromkeys(HANDLE.findall(str(tools[0].content))))
        assert selected, (
            "verifier must receive real exact report handles through materialized inputs"
        )
        expected = self.script.registered.get(iteration)
        assert expected is not None, "verifier candidate has no observed registration receipt"
        received_reports = [row for row in selected if "/report/" in row[0]]
        assert received_reports == [(expected["handle"], expected["digest"])], (
            "verifier received stale or mismatched exact candidate"
        )
        if len(tools) <= len(selected):
            handle, digest = selected[len(tools) - 1]
            return self._call(
                "knowledge_read",
                {"handle": handle, "digest": digest},
                iteration,
                "verifier",
                len(tools),
            )
        reads = [_document(message) for message in tools[1:]]
        assert all(read.get("ok") for read in reads), reads
        self.script.reads.append(
            {
                "iteration": iteration,
                "operation_id": self.operation_id,
                "selected": selected,
                "read_results": reads,
            }
        )
        accepted = iteration == 2 and self.script.accept_final
        observation = GoalVerifierObservation(
            decision="accepted" if accepted else "repair_required",
            progress_made=True,
            accepted_obligation_refs=self.obligation_refs if accepted else (),
            findings=() if accepted else (self.script.feedback,),
            unmet_obligations=() if accepted else self.obligation_refs,
            obligation_applicability=tuple((ref, True) for ref in self.obligation_refs),
            output_contract_ref=self.output_contract_ref,
        )
        return self._answer(observation.model_dump(mode="json"))

    def _call(
        self, name: str, args: dict[str, Any], iteration: int, role: str, ordinal: int
    ) -> ChatResult:
        self.script.calls.append(
            {
                "run_id": self.run_id,
                "operation_id": self.operation_id,
                "iteration": iteration,
                "role": role,
                "tool": name,
            }
        )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": name,
                                "args": args,
                                "id": f"goal-{iteration}-{role}-{ordinal}",
                                "type": "tool_call",
                            }
                        ],
                        usage_metadata=call_usage(),
                    )
                )
            ]
        )

    def _answer(self, payload: dict[str, Any]) -> ChatResult:
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=json.dumps(payload),
                        usage_metadata=call_usage(),
                    )
                )
            ]
        )
