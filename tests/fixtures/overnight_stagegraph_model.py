"""Unpaid scripted cognition using ordinary admitted report/read/submission tools.

No fixture callback writes output rows, assessments or promotions. The producer authors
the supplied report payload; normal host finalization and independent settlement own use.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tests.fixtures.rrm009_production_stack import _LoggedModel, call_usage


@dataclass
class StageGraphScript:
    report: dict[str, Any]
    wrong_digest_probe: bool = False
    prior_report: dict[str, Any] | None = None
    sibling_report: dict[str, Any] | None = None
    registrations: dict[str, dict[str, str]] = field(default_factory=dict)
    reads: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)


def _document(message: ToolMessage) -> dict[str, Any]:
    content = message.content
    if isinstance(content, list):
        content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return json.loads(str(content))


class StageGraphModel(_LoggedModel):
    script: Any
    position: str

    @property
    def _llm_type(self) -> str:
        return "overnight-scripted-stagegraph"

    def _reply(self, messages: list[BaseMessage]) -> ChatResult:
        self._record("parent", messages)
        tools = [item for item in messages if isinstance(item, ToolMessage)]
        if self.position == "produce":
            return self._producer(tools)
        if self.position == "consume":
            return self._consumer(tools)
        raise AssertionError(f"unexpected authored position: {self.position}")

    def _producer(self, tools: list[ToolMessage]) -> ChatResult:
        if self.script.prior_report is not None:
            return self._isolation_producer(tools)
        if not tools:
            return self._call("report_register", {"report": self.script.report}, 0)
        registered = _document(tools[0])
        assert registered.get("ok"), registered
        result = registered["result"]
        report = next(item for item in result["affected"] if "/report/" in item["handle"])
        if len(tools) == 1:
            return self._call(
                "submit_output",
                {
                    "obligation": "produce.report",
                    "items": [
                        {"kind": "handle", "ref": report["handle"], "digest": report["digest"]}
                    ],
                },
                1,
            )
        assert _document(tools[-1]).get("ok"), tools[-1].content
        if len(tools) == 2:
            return self._call(
                "submit_output",
                {
                    "obligation": "produce.progress_note",
                    "items": [
                        {
                            "kind": "inline",
                            "text": "Registered the cited report; awaiting host assessment.",
                        }
                    ],
                },
                2,
            )
        if len(tools) == 3:
            return self._call(
                "submit_output",
                {
                    "obligation": "produce.summary",
                    "items": [
                        {
                            "kind": "inline",
                            "text": "The report records the supplied source findings.",
                        }
                    ],
                },
                3,
            )
        return self._final()

    def _isolation_producer(self, tools: list[ToolMessage]) -> ChatResult:
        def report_at(index: int, name: str) -> dict[str, str]:
            answer = _document(tools[index])
            assert answer.get("ok"), answer
            exact = next(
                item for item in answer["result"]["affected"] if "/report/" in item["handle"]
            )
            self.script.registrations[name] = exact
            return exact

        if not tools:
            return self._call("report_register", {"report": self.script.prior_report}, 0)
        prior = report_at(0, "prior")
        if len(tools) == 1:
            return self._call("report_register", {"report": self.script.sibling_report}, 1)
        report_at(1, "sibling")
        if len(tools) == 2:
            current = deepcopy(self.script.report)
            current["report"]["supersedes"] = prior
            return self._call("report_register", {"report": current}, 2)
        current = report_at(2, "current")
        if len(tools) == 3:
            return self._call(
                "submit_output",
                {
                    "obligation": "produce.report",
                    "items": [
                        {"kind": "handle", "ref": current["handle"], "digest": current["digest"]}
                    ],
                },
                3,
            )
        assert _document(tools[-1]).get("ok"), tools[-1].content
        if len(tools) == 4:
            return self._call(
                "submit_output",
                {
                    "obligation": "produce.progress_note",
                    "items": [
                        {
                            "kind": "inline",
                            "text": "Registered three reports; submitted only the exact successor.",
                        }
                    ],
                },
                4,
            )
        if len(tools) == 5:
            return self._call(
                "submit_output",
                {
                    "obligation": "produce.summary",
                    "items": [
                        {
                            "kind": "inline",
                            "text": "Only the current sourced report is offered for acceptance.",
                        }
                    ],
                },
                5,
            )
        return self._final()

    def _consumer(self, tools: list[ToolMessage]) -> ChatResult:
        if not tools:
            return self._call("read_file", {"file_path": "/.mission/transfer.json"}, 0)
        if len(tools) == 1:
            # Resolve the actual materialized handle from the backend response; never use
            # the producer's registration answer or a fixture-held report reference.
            text = str(tools[0].content)
            self.script.reads.append({"run_id": self.run_id, "index": text})
            selected = re.findall(r'(kh:[^\s"\\#]+)#digest=(sha256:[0-9a-f]{64})', text)
            assert selected, f"actual input index names no exact KS handle/digest: {text}"
            handle, digest = selected[0]
            if self.script.wrong_digest_probe:
                digest = digest[:-1] + ("0" if digest[-1] != "0" else "1")
            return self._call("knowledge_read", {"handle": handle, "digest": digest}, 1)
        if self.script.wrong_digest_probe and len(tools) == 2:
            refused = _document(tools[1])
            assert not refused.get("ok"), refused
            assert "content" not in (refused.get("result") or {}), refused
            self.script.reads.append({"run_id": self.run_id, "wrong_digest_refusal": refused})
            handle, digest = re.findall(
                r'(kh:[^\s"\\#]+)#digest=(sha256:[0-9a-f]{64})', str(tools[0].content)
            )[0]
            return self._call("knowledge_read", {"handle": handle, "digest": digest}, 2)
        offset = int(self.script.wrong_digest_probe)
        if len(tools) == 2 + offset:
            read = _document(tools[1 + offset])
            assert read.get("ok"), read
            self.script.reads.append({"run_id": self.run_id, "read": read})
            text = json.dumps(read["result"], sort_keys=True)
            findings = list(
                dict.fromkeys(re.findall(r"Model [A-Za-z0-9_-]+ has [0-9.]+B parameters\.", text))
            )
            assert findings, "actual exact-read result contains no source-attributed finding"
            exact = re.findall(
                r'(kh:[^\s"\\#]+)#digest=(sha256:[0-9a-f]{64})', str(tools[0].content)
            )[0]
            summary = f"Read report {exact[0]} ({exact[1]}). " + " ".join(findings[:2])
            return self._call(
                "submit_output",
                {
                    "obligation": "consume.comparison",
                    "items": [{"kind": "inline", "text": summary}],
                },
                2 + offset,
            )
        assert _document(tools[-1]).get("ok"), tools[-1].content
        return self._final()

    def _call(self, name: str, args: dict[str, Any], ordinal: int) -> ChatResult:
        self.script.calls.append({"run_id": self.run_id, "position": self.position, "tool": name})
        message = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": args,
                    "id": f"overnight-{self.position}-{ordinal}",
                    "type": "tool_call",
                }
            ],
            usage_metadata=call_usage(),
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _final(self) -> ChatResult:
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content=json.dumps(
                            {"answer": "Named outputs submitted", "facts": {}, "output_refs": []}
                        ),
                        usage_metadata=call_usage(),
                    )
                )
            ]
        )


def stagegraph_components(
    technical: Any, script: StageGraphScript, log: list[dict[str, Any]]
) -> Any:
    base = technical.components(log)

    def parent(bound: Any, _secrets: Any) -> StageGraphModel:
        assert ":stage:" in bound.operation_id, "model binding must name a concrete stage"
        position = bound.operation_id.split(":stage:", 1)[1].split(":", 1)[0]
        return StageGraphModel(
            run_id=bound.run_id,
            operation_id=bound.operation_id,
            log=log,
            script=script,
            position=position,
        )

    return replace(
        base, model_factories={**base.model_factories, technical.binding.model.ref.digest: parent}
    )
