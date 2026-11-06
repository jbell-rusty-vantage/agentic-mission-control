"""Held linked repair consumes actual sealed bytes/findings before proposing a successor."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any

from langchain_core.messages import ToolMessage
from langchain_core.outputs import ChatResult
from tests.fixtures.overnight_goal_model import GoalModel, GoalScript
from tests.fixtures.overnight_linked_model import LinkedScript
from tests.fixtures.overnight_stagegraph_model import StageGraphModel, _document

from mission_control.contracts.knowledge_protocol import ResearchReportPackage


@dataclass
class LinkedRepairScript(LinkedScript):
    grounded: dict[str, Any] = field(default_factory=dict)
    repair_observations: list[dict[str, Any]] = field(default_factory=list)
    registered_successor: dict[str, str] = field(default_factory=dict)


def linked_repair_script(
    held: dict[str, Any], grounded: dict[str, Any], *, feedback: str
) -> LinkedRepairScript:
    return LinkedRepairScript(
        source=GoalScript(candidates=(deepcopy(held), deepcopy(grounded)), feedback=feedback),
        grounded=deepcopy(grounded),
    )


def file_text(message: ToolMessage) -> str:
    content = message.content
    text = (
        content
        if isinstance(content, str)
        else "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    )
    lines = text.split("\n")
    rows = [re.fullmatch(r"[ \t]*(\d+)(?:\.(\d+))?  (.*)", line) for line in lines]
    if not rows or not all(rows):
        return text
    reconstructed: list[str] = []
    current_line, chunk = 0, 0
    for row in rows:
        assert row is not None
        line_number, continuation, source = row.groups()
        number = int(line_number)
        if continuation is None:
            assert number == current_line + 1, "read_file omitted source lines"
            reconstructed.append(source)
            current_line, chunk = number, 0
        else:
            assert number == current_line and int(continuation) == chunk + 1, (
                "read_file omitted or reordered a continuation chunk"
            )
            reconstructed[-1] += source
            chunk += 1
    return "\n".join(reconstructed)


def findings_from_read(message: ToolMessage, entry: dict[str, Any]) -> dict[str, Any]:
    text = file_text(message)
    candidates = {text.encode("utf-8"), (text + "\n").encode("utf-8")}
    matches = [
        raw
        for raw in candidates
        if len(raw) == entry["bytes"]
        and "sha256:" + hashlib.sha256(raw).hexdigest() == entry["digest"]
    ]
    assert len(matches) == 1, "full findings backend bytes differ from sealed digest/length"
    document = json.loads(matches[0])
    assert document["canonical_schema_version"] == "canonical-json/1"
    return document["payload"]


class LinkedRepairConsumerModel(StageGraphModel):
    repair: Any

    def _consumer(self, tools: list[ToolMessage]) -> ChatResult:
        if not tools:
            return self._call("read_file", {"file_path": "/.mission/transfer.json"}, 0)
        index = json.loads(file_text(tools[0]))
        assert index["schema"] == "mc.transfer_inputs.v1"
        entries = index["inputs"]
        assert entries and all(
            item["admission"] == "subject" and item["purpose"] == "repair" for item in entries
        )
        reports = list(
            dict.fromkeys(
                re.findall(r"(kh:[^\s\"#]+)#digest=(sha256:[0-9a-f]{64})", json.dumps(index))
            )
        )
        assert len(reports) == 1, "repair needs one exact source report from actual index"
        handle, digest = reports[0]
        assert self.repair.source.registered[1] == {"handle": handle, "digest": digest}
        finding_entries = [item for item in entries if item["member"].endswith("/findings")]
        assert len(finding_entries) == 1
        finding_entry = finding_entries[0]
        assert finding_entry["placement"] == "file" and finding_entry["read_with"] == "read_file"
        if len(tools) == 1:
            self.script.reads.append({"run_id": self.run_id, "index": str(tools[0].content)})
            return self._call("knowledge_read", {"handle": handle, "digest": digest}, 1)
        read = _document(tools[1])
        assert read.get("ok"), read
        content = read["result"]["content"]
        package = ResearchReportPackage.model_validate(content["manifest"])
        assert package.purpose == "repair"
        assert (
            f"kh:{package.report.binding}/report/{package.report.id}@{package.report.version}"
            == handle
        )
        assert package.report.digest == digest
        for name in ("body", "ledger"):
            part = getattr(package, name)
            raw = content[name].encode("utf-8")
            assert part is not None and len(raw) == part.bytes
            assert "sha256:" + hashlib.sha256(raw).hexdigest() == part.digest
        assert "Model X has 9B parameters." in content["body"], "actual held 9B body missing"
        if len(tools) == 2:
            self.script.reads.append({"run_id": self.run_id, "read": read})
            return self._call("read_file", {"file_path": finding_entry["path"]}, 2)
        findings = findings_from_read(tools[2], finding_entry)
        linked = finding_entry["linked_source"]
        assert findings["schema_version"] == "mc.linked-subject-findings.v1"
        assert findings["admission"] == "subject" and findings["official_use"] is False
        assert findings["source_run_id"] == self.repair.source_run
        assert findings["revision_id"] == linked["output_revision_id"]
        assert findings["content_digest"] == digest == linked["output_digest"]
        assert findings["export_id"] == linked["export_id"]
        assert findings["export_digest"] == linked["export_digest"]
        verifications = [item["payload"]["verification"] for item in findings["goal_findings"]]
        assert any(
            item["decision"] == "repair_required"
            and item["executor_identity"]["iteration"]["run_id"] == self.repair.source_run
            and item["executor_identity"]["iteration"]["goal_iteration"] == 1
            and self.repair.source.feedback in item["findings"]
            for item in verifications
        ), "exact full source verifier feedback missing from backend findings"
        assert findings["assessments"], "held subject needs actual assessment findings/status"
        if len(tools) == 3:
            self.script.reads.append(
                {
                    "run_id": self.run_id,
                    "findings": findings,
                    "findings_index": finding_entry,
                    "findings_backend_text": str(tools[2].content),
                }
            )
            self.repair.repair_observations.append({"held_read": read, "findings": findings})
            candidate = deepcopy(self.repair.grounded)
            assert "Model X has 7B parameters." in json.dumps(candidate["report"]["structuredBody"])
            candidate["report"]["supersedes"] = {"handle": handle, "digest": digest}
            return self._call("report_register", {"report": candidate}, 3)
        registered = _document(tools[3])
        assert registered.get("ok"), registered
        reports = [
            item for item in registered["result"]["affected"] if "/report/" in item["handle"]
        ]
        assert len(reports) == 1 and reports[0]["handle"] != handle
        assert reports[0]["digest"] != digest, "successor receipt reused held report digest"
        successor = {key: reports[0][key] for key in ("handle", "digest")}
        self.repair.registered_successor = successor
        self.script.registrations["current"] = successor
        if len(tools) == 4:
            return self._call(
                "submit_output",
                {
                    "obligation": "consume.report",
                    "items": [
                        {
                            "kind": "handle",
                            "ref": successor["handle"],
                            "digest": successor["digest"],
                        }
                    ],
                },
                4,
            )
        assert _document(tools[-1]).get("ok"), tools[-1].content
        progress = (
            f"Read held {handle} ({digest}) and full findings; proposed {successor['handle']}."
        )
        if len(tools) == 5:
            return self._call(
                "submit_output",
                {
                    "obligation": "consume.progress_note",
                    "items": [{"kind": "inline", "text": progress}],
                },
                5,
            )
        if len(tools) == 6:
            self.repair.summaries.append(progress)
            return self._call(
                "submit_output",
                {
                    "obligation": "consume.comparison",
                    "items": [{"kind": "inline", "text": progress}],
                },
                6,
            )
        if len(tools) == 7:
            return self._call("knowledge_read", successor, 7)
        successor_read = _document(tools[7])
        assert successor_read.get("ok"), successor_read
        successor_content = successor_read["result"]["content"]
        successor_package = ResearchReportPackage.model_validate(successor_content["manifest"])
        assert successor_package.report.digest == successor["digest"]
        assert (
            f"kh:{successor_package.report.binding}/report/"
            f"{successor_package.report.id}@{successor_package.report.version}"
        ) == successor["handle"]
        for part in ("body", "ledger"):
            descriptor = getattr(successor_package, part)
            raw = successor_content[part].encode("utf-8")
            assert descriptor is not None and len(raw) == descriptor.bytes
            assert "sha256:" + hashlib.sha256(raw).hexdigest() == descriptor.digest
        assert "Model X has 7B parameters." in successor_content["body"]
        self.script.reads.append({"run_id": self.run_id, "read": successor_read})
        return self._final()


def linked_repair_components(
    technical: Any, script: LinkedRepairScript, log: list[dict[str, Any]]
) -> Any:
    base = technical.components(log)

    def factory(bound: Any, _secrets: Any) -> Any:
        if bound.operation_id.startswith("goal-iteration/"):
            assert bound.run_id == script.source_run
            return GoalModel(
                run_id=bound.run_id,
                operation_id=bound.operation_id,
                log=log,
                script=script.source,
                output_contract_ref=script.source.output_contract_ref,
                obligation_refs=script.source.obligation_refs,
            )
        assert ":stage:consume:" in bound.operation_id
        assert bound.run_id == script.consumer_run
        return LinkedRepairConsumerModel(
            run_id=bound.run_id,
            operation_id=bound.operation_id,
            position="consume",
            script=script.consumer,
            repair=script,
            log=log,
        )

    return replace(
        base, model_factories={**base.model_factories, technical.binding.model.ref.digest: factory}
    )
