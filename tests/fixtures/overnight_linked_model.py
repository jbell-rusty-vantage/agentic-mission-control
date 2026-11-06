"""Scripted cognition for ordinary same-application linked report transfer."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatResult
from tests.fixtures.overnight_goal_model import GoalModel, GoalScript
from tests.fixtures.overnight_stagegraph_model import StageGraphModel, StageGraphScript


@dataclass
class LinkedScript:
    source: GoalScript
    consumer: StageGraphScript = field(default_factory=lambda: StageGraphScript(report={}))
    source_run: str | None = None
    consumer_run: str | None = None
    summaries: list[str] = field(default_factory=list)


def linked_script(report: dict[str, Any]) -> LinkedScript:
    first = deepcopy(report)
    first["report"]["revision"] = 1
    first["report"]["supersedes"] = None
    unused = deepcopy(first)
    unused["report"]["revision"] = 2
    for collection in ("assertions", "supportSets"):
        for row in first[collection]:
            unused = json.loads(
                json.dumps(unused).replace(
                    json.dumps(row["id"]), json.dumps(row["id"] + "-unused-r2")
                )
            )
    return LinkedScript(
        source=GoalScript(
            candidates=(first, unused), feedback="Source is bounded to one grounded candidate."
        )
    )


class LinkedSourceModel(GoalModel):
    """One grounded source iteration, with its independent actual verifier read."""

    def _answer(self, payload: dict[str, Any]) -> ChatResult:
        if "decision" in payload:
            payload = {
                **payload,
                "decision": "accepted",
                "findings": [],
                "unmet_obligations": [],
                "accepted_obligation_refs": list(self.obligation_refs),
            }
        elif "completion_claim" in payload:
            payload = {**payload, "completion_claim": True}
        return super()._answer(payload)


class LinkedConsumerModel(StageGraphModel):
    linked: Any

    def _consumer(self, tools: list[ToolMessage]) -> ChatResult:
        if tools:
            from tests.fixtures.overnight_goal_model import HANDLE

            exact = self.linked.source.registered.get(1)
            assert exact is not None, "consumer cannot precede observed source registration"
            selected = list(dict.fromkeys(HANDLE.findall(str(tools[0].content))))
            assert selected == [(exact["handle"], exact["digest"])], (
                "linked sealed index differs from exact source accepted report",
                selected,
                exact,
            )
        response = super()._consumer(tools)
        message = response.generations[0].message
        assert isinstance(message, AIMessage)
        for call in message.tool_calls:
            if call["name"] == "submit_output":
                summary = call["args"]["items"][0]["text"]
                self.linked.summaries.append(summary)
        return response


def linked_components(technical: Any, script: LinkedScript, log: list[dict[str, Any]]) -> Any:
    base = technical.components(log)

    def factory(bound: Any, _secrets: Any) -> Any:
        if bound.operation_id.startswith("goal-iteration/"):
            assert bound.run_id == script.source_run
            return LinkedSourceModel(
                run_id=bound.run_id,
                operation_id=bound.operation_id,
                log=log,
                script=script.source,
                output_contract_ref=script.source.output_contract_ref,
                obligation_refs=script.source.obligation_refs,
            )
        assert ":stage:consume:" in bound.operation_id, bound.operation_id
        return LinkedConsumerModel(
            run_id=bound.run_id,
            operation_id=bound.operation_id,
            position="consume",
            script=script.consumer,
            linked=script,
            log=log,
        )

    return replace(
        base, model_factories={**base.model_factories, technical.binding.model.ref.digest: factory}
    )
