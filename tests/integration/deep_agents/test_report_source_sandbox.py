"""Prepared skills parsed and fully read by real Deep Agents, without provider calls.

This proves skill and bundled reference attachment/readability only. MCP or CLI
execution is not exercised by skill attachment.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import replace
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from tests.acceptance.control_plane.test_wp_cp_040 import (
    exact_fixture,
    planned_invocation,
    registry,
    unit_bound,
)
from tests.integration.deep_agents.test_wi02_transfer_plan_lane import PlanReadingModel
from tests.unit.test_report_source_context import context

from mission_control.adapters.capabilities.capability_bundles import bundle_digest, bytes_digest
from mission_control.adapters.deep_agents.adapter import DeepAgentRuntimeAdapter
from mission_control.adapters.deep_agents.materializer import (
    ExactDeepAgentMaterializer,
    ResolvedSkillBundle,
)
from mission_control.application.execution.operations.checkpoint_lineage import (
    CheckpointLineageService,
    InMemoryCheckpointLineageRepository,
)
from mission_control.domain.execution.contracts import DeepAgentExecutionBinding


class SandboxSkillReader(PlanReadingModel):
    expected: dict[str, str]
    observed_text: dict[str, str] = {}
    calls: int = 0

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        del stop, run_manager, kwargs
        self.calls += 1
        results = [item for item in messages if isinstance(item, ToolMessage)]
        if not results:
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_file",
                        "args": {
                            "file_path": path,
                            "offset": 0,
                            "limit": len(text.splitlines()) + 1,
                        },
                        "id": path,
                        "type": "tool_call",
                    }
                    for path, text in self.expected.items()
                ],
            )
        else:
            for item in results:
                lines = {}
                for row in str(item.content).split("\n"):
                    match = re.match(r"^\s*(\d+)(?:\.(\d+))?  (.*)$", row)
                    if match:
                        number = int(match[1])
                        lines[number] = lines.get(number, "") + match[3]
                self.observed_text[item.tool_call_id] = "\n".join(lines[n] for n in sorted(lines))
            message = AIMessage(content="all sandbox skills read")
        return ChatResult(generations=[ChatGeneration(message=message)])


@pytest.mark.asyncio
async def test_prepared_skills_are_discovered_and_fully_read(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    application = "ai-engineer"
    monkeypatch.syspath_prepend(str(context.MC_ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "report_source_sandbox", context.MC_ROOT / "scripts/report_source_sandbox.py"
    )
    assert spec and spec.loader
    sandbox = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sandbox)
    source = tmp_path / "context"
    context.materialize_context(
        context.MC_ROOT.parents[1], context.PROFILES / f"{application}.json", source
    )
    prepared = tmp_path / "sandbox"
    sandbox.prepare(source, prepared)
    sandbox.verify(prepared)

    binding, _, original = exact_fixture()
    bundles = {}
    components = []
    expected = {}
    for entry in sorted((prepared / "sandbox/skills").iterdir()):
        files = tuple(
            (path.relative_to(entry).as_posix(), path.read_bytes())
            for path in sorted(entry.rglob("*"))
            if path.is_file()
        )
        bundle = ResolvedSkillBundle(bundle_digest(files), files, digest_format="bytes_v1")
        bundles[bundle.bundle_digest] = bundle
        skill = dict(files)["SKILL.md"]
        mount = f"/skills/{entry.name}"
        component = binding.skills[0].model_copy(
            update={
                "ref": binding.skills[0].ref.model_copy(
                    update={
                        "logical_id": f"skill.sandbox-{entry.name}",
                        "digest": bytes_digest(skill),
                    }
                ),
                "skill_name": entry.name,
                "bundle_digest": bundle.bundle_digest,
                "skill_md_digest": bytes_digest(skill),
                "mount_root": mount,
            }
        )
        components.append(component)
        expected[f"{mount}/SKILL.md"] = skill.decode().replace("\r\n", "\n").rstrip("\n")
    assert len(components) == 6
    references = "report-source-procedure/references"
    for relative in (
        f"{references}/START_HERE.md",
        f"{references}/SCHEMA_ROUTE.md",
        f"{references}/context/shared/packages/research-core/src/records/report.ts",
    ):
        content = (prepared / "sandbox/skills" / relative).read_text(encoding="utf-8")
        expected[f"/skills/{relative}"] = content.rstrip("\n")
    binding = unit_bound(
        DeepAgentExecutionBinding.create(
            **{**binding.model_dump(exclude={"binding_digest"}), "skills": tuple(components)}
        )
    )
    model = SandboxSkillReader(expected=expected)
    components_registry = replace(registry(binding, original, model), skill_bundles=bundles)
    adapter = DeepAgentRuntimeAdapter(ExactDeepAgentMaterializer(components_registry))
    lineage = CheckpointLineageService(InMemoryCheckpointLineageRepository())
    result = await adapter.execute(await planned_invocation(binding, lineage), {})
    assert result.output_text == "all sandbox skills read"
    assert model.observed_text == expected
    assert model.calls == 2
    inspection = result.event_payloads[0]
    assert {row["name"] for row in inspection["skills_metadata"]} == {
        component.skill_name for component in components
    }
    assert {row["path"] for row in inspection["skill_instruction_messages"]} == {
        path for path in expected if path.endswith("/SKILL.md")
    }
