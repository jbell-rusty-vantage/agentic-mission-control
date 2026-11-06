"""Biotech report-only fixture adaptation; no graph apply, admission or promotion authority."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from mission_control.bootstrap.application_profiles import load_application_profile
from mission_control.bootstrap.model_profiles import load_model_catalog_file, models_path
from mission_control.contracts.knowledge_protocol import ResearchReportPackage
from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from mission_control.domain.resolution.profiles import ModelProfile

DEPLOYMENTS = Path(__file__).resolve().parents[2] / "deployments"
BINDING = "biotech-graph"


def biotech_model_profile(
    profile: str = "producer.default", *, deployments: Path = DEPLOYMENTS
) -> ModelProfile:
    """Actual application catalog row; row.pin() supplies the canonical ModelPin.

    Compose this row in the local ModelCatalog and serve its vendor/model_id under the
    existing exact fixture component ref. Map the same profile to that served ref in launch
    bindings; use the row's vendor in trusted evaluator composition. Only invocation is scripted.
    """
    application = load_application_profile(deployments, "biotech").profile
    if application.application_id != "biotech" or application.knowledge.binding_id != BINDING:
        raise ValueError("Biotech application profile has a different knowledge binding")
    if "reference" not in application.outputs.allowed_forms:
        raise ValueError("Biotech application profile does not admit reference outputs")
    rows = load_model_catalog_file(models_path(deployments, "biotech")).models
    selected = next((row for row in rows if row.profile == profile), None)
    if selected is None:
        raise ValueError("Biotech model profile is not in its application catalog")
    return selected


def validate_biotech_ready(ready: dict[str, Any], *, tenant: str) -> None:
    if ready.get("binding") != BINDING or not ready.get("reports"):
        raise ValueError("expected actual Biotech report-only ready payload")
    for candidate in ready["reports"]:
        task = candidate["task"]
        if (task.get("domain"), task.get("use"), task.get("rubric", {}).get("id")) != (
            "scientific",
            "label_reference.ingredients",
            "rubric-scientific",
        ):
            raise ValueError("Biotech fixture requires its scientific label-reference task")
        if candidate["report"]["kind"] != "evidence_report":
            raise ValueError("Biotech fixture requires the operational evidence-report contract")
        for record in [
            task,
            *candidate["assertions"],
            *candidate["fragments"],
            *candidate["supportSets"],
        ]:
            if (record.get("tenant"), record.get("binding")) != (tenant, BINDING):
                raise ValueError(
                    "Biotech ready record scope differs from the receiving application"
                )
        if not candidate["assertions"] or any(
            assertion.get("qualifiers", {}).get("profile") != "scientific.v2"
            for assertion in candidate["assertions"]
        ):
            raise ValueError("Biotech assertions must retain scientific.v2 qualifiers")


def biotech_linked_manifest(
    authored_yaml: str, ready: dict[str, Any], *, tenant: str, deployments: Path = DEPLOYMENTS
) -> str:
    """Adapt existing linked authoring using actual application/profile and ready contracts."""
    validate_biotech_ready(ready, tenant=tenant)
    producer = biotech_model_profile(deployments=deployments)
    document = load_manifest_yaml(authored_yaml)
    for mission in document["missions"]:
        mission["application"] = "biotech"
        mission["environment"]["model"]["profile"] = producer.profile
        mission["title"] = (
            "Biotech source label-reference report"
            if mission["key"] == "source"
            else "Independent Biotech report-only label comparison"
        )
        for goal in mission["goals"]:
            goal["description"] = (
                "Report only the ingredient explicitly listed in each frozen label quote. "
                "Register an evidence_report with scientific.v2 qualifiers, exact source citations "
                "and task obligations. Do not infer clinical effects. Submit root.report from the "
                "actual registration receipt, root.progress_note and root.summary. "
                "FROZEN PACK (task and sources, JSON): "
                + json.dumps(
                    {
                        "reportId": ready["reports"][-1]["report"]["reportId"],
                        "task": ready["reports"][-1]["task"],
                        "fragments": ready["reports"][-1]["fragments"],
                    }
                )
                if mission["key"] == "source"
                else "Summarize the accepted label report without adopting its obligation."
            )
        verifier = mission["program"].get("verifier")
        if verifier is not None:
            verifier["environment"]["model"]["profile"] = producer.profile
        for node in mission["program"].get("nodes", []):
            if node.get("environment", {}).get("model") is not None:
                node["environment"]["model"]["profile"] = producer.profile
            if node["key"] == "consume":
                node["instruction"] = (
                    "Read /.mission/transfer.json and knowledge_read its exact report access_ref. "
                    "Submit consume.comparison from the observed label. Preserve scientific "
                    "qualifiers and source attribution; no graph apply or clinical inference."
                )
    return canonical_manifest_bytes(document).decode("utf-8")


def biotech_summary_from_read(
    read: dict[str, Any], *, report_handle: str, report_digest: str, tenant: str
) -> str:
    """Summarize only verified observed label bytes, never registration/controller text."""
    if read.get("ok") is not True:
        raise ValueError("Biotech exact read was refused")
    content = read["result"]["content"]
    package = ResearchReportPackage.model_validate(content["manifest"])
    ref = package.report
    if (ref.binding, ref.tenant, ref.digest, f"kh:{ref.binding}/report/{ref.id}@{ref.version}") != (
        BINDING,
        tenant,
        report_digest,
        report_handle,
    ) or package.purpose not in {"dependent_input", "repair"}:
        raise ValueError("Biotech read differs from the exact scoped report selection")
    for part in ("body", "ledger"):
        descriptor = getattr(package, part)
        raw = content[part].encode("utf-8")
        if (
            descriptor is None
            or len(raw) != descriptor.bytes
            or ("sha256:" + hashlib.sha256(raw).hexdigest() != descriptor.digest)
        ):
            raise ValueError("Biotech read part differs from its exact receipt")
    if not package.assertions or any(
        member.record.get("qualifiers", {}).get("profile") != "scientific.v2"
        for member in package.assertions
    ):
        raise ValueError("Biotech read omitted scientific assertion qualifiers")
    statements = list(
        dict.fromkeys(re.findall(r"Product [^\n.]+ label lists [^\n.]+\.", content["body"]))
    )
    if not statements:
        raise ValueError("observed Biotech body contains no label-reference statement")
    return f"Read report {report_handle} ({report_digest}). " + " ".join(statements)


def biotech_technical_binding(technical: Any, profile: ModelProfile) -> Any:
    from dataclasses import replace

    from mission_control.domain.execution.contracts import DeepAgentExecutionBinding

    pin = biotech_served_model(profile)
    model = technical.binding.model.model_copy(
        update={
            "ref": pin.ref.as_ref(),
            "provider": profile.vendor,
            "model_name": profile.model_id,
            "structured_output": profile.structured_output,
        }
    )
    binding = DeepAgentExecutionBinding.create(
        **{
            **technical.binding.model_dump(mode="python", exclude={"binding_digest"}),
            "model": model,
        }
    )
    return replace(technical, binding=binding)


def biotech_components(technical: Any, script: Any, log: list[dict[str, Any]], tenant: str) -> Any:
    from dataclasses import replace

    from langchain_core.messages import ToolMessage
    from langchain_core.outputs import ChatResult
    from tests.fixtures.overnight_linked_model import LinkedSourceModel
    from tests.fixtures.overnight_linked_repair_model import file_text
    from tests.fixtures.overnight_stagegraph_model import StageGraphModel, _document

    class BiotechConsumer(StageGraphModel):
        def _consumer(self, tools: list[ToolMessage]) -> ChatResult:
            if not tools:
                return self._call("read_file", {"file_path": "/.mission/transfer.json"}, 0)
            index = json.loads(file_text(tools[0]))
            selected = list(
                dict.fromkeys(
                    re.findall(r"(kh:[^\s\"#]+)#digest=(sha256:[0-9a-f]{64})", json.dumps(index))
                )
            )
            assert len(selected) == 1
            handle, digest = selected[0]
            assert script.source.registered[1] == {"handle": handle, "digest": digest}
            assert all(
                item["admission"] == "accepted" and item["purpose"] == "dependent_input"
                for item in index["inputs"]
            )
            if len(tools) == 1:
                self.script.reads.append({"run_id": self.run_id, "index": str(tools[0].content)})
                return self._call("knowledge_read", {"handle": handle, "digest": digest}, 1)
            if len(tools) == 2:
                read = _document(tools[1])
                summary = biotech_summary_from_read(
                    read, report_handle=handle, report_digest=digest, tenant=tenant
                )
                self.script.reads.append({"run_id": self.run_id, "read": read})
                script.summaries.append(summary)
                return self._call(
                    "submit_output",
                    {
                        "obligation": "consume.comparison",
                        "items": [{"kind": "inline", "text": summary}],
                    },
                    2,
                )
            assert _document(tools[-1]).get("ok")
            return self._final()

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
        assert bound.run_id == script.consumer_run and ":stage:consume:" in bound.operation_id
        return BiotechConsumer(
            run_id=bound.run_id,
            operation_id=bound.operation_id,
            position="consume",
            script=script.consumer,
            log=log,
        )

    return replace(
        base, model_factories={**base.model_factories, technical.binding.model.ref.digest: factory}
    )


async def verify_biotech(
    stack: Any,
    scope: str,
    runs: dict[str, str],
    script: Any,
    lane: Any,
    technical: Any,
    profile: ModelProfile,
) -> dict[str, Any]:
    from mission_control.adapters.deep_agents.binding import execution_binding
    from mission_control.adapters.postgres.knowledge.output_contracts import (
        PostgresOutputContractStore,
    )
    from mission_control.adapters.postgres.run_control import canonical as mc
    from mission_control.domain.execution.contracts import OperationExecutionBinding
    from mission_control.domain.knowledge.lineage import ProvenanceRole

    assert scope.split("/")[2] == "biotech"
    application = load_application_profile(DEPLOYMENTS, "biotech").profile
    assert application.knowledge.binding_id == BINDING
    assert profile == biotech_model_profile()
    bindings = []
    async with stack.worker_pool.acquire() as connection, connection.transaction():
        args = await mc.begin(connection, scope)
        rows = await connection.fetch(
            "SELECT identity, payload, digest FROM mission_control.runtime_document "
            "WHERE installation_id=$1 AND application_id=$2 AND tenant_id=$3 "
            "AND contract='operation.binding/1' AND payload->>'run_id'=ANY($4::text[])",
            *args,
            list(runs.values()),
        )
    for row in rows:
        binding = OperationExecutionBinding.model_validate(mc.load(row["payload"]))
        assert binding.request_scope == scope and binding.run_id in runs.values()
        assert binding.lane_binding is not None
        actual = execution_binding(binding)
        assert (
            actual.model.provider == profile.vendor and actual.model.model_name == profile.model_id
        )
        assert actual.model.ref == technical.binding.model.ref
        bindings.append(
            {
                "identity": row["identity"],
                "digest": row["digest"],
                "run_id": binding.run_id,
                "operation_id": binding.operation_id,
                "model": actual.model.model_dump(mode="json"),
                "sealed_digest": binding.lane_binding.digest,
            }
        )
    assert {item["run_id"] for item in bindings} == set(runs.values())
    store = PostgresOutputContractStore(stack.worker_pool)
    source = next(
        item
        for item in await store.accepted_outputs(scope, runs["source"])
        if item.obligation_key == "root.report"
    )
    source_handle = source.candidate["ref"]
    assert isinstance(source_handle, str) and source_handle.startswith("kh:biotech-graph/report/")
    facts = await lane.toolset.lineage.facts(scope, source.candidate["ref"])
    producers = [item for item in facts if item.role is ProvenanceRole.PRODUCER]
    assert len(producers) == 1 and producers[0].actor_origin is not None
    assert producers[0].actor_origin.run_id == runs["source"]
    assert not any(item.role is ProvenanceRole.ADOPTER for item in facts)
    reads = [item["read"] for item in script.consumer.reads if "read" in item]
    assert len(reads) == 1
    summary = biotech_summary_from_read(
        reads[0],
        report_handle=source_handle,
        report_digest=source.content_digest,
        tenant=scope.rsplit("/", 1)[-1],
    )
    assert script.summaries == [summary]
    return {
        "verified": True,
        "scope": scope,
        "application": application.model_dump(mode="json"),
        "served_definition": biotech_served_model(profile).model_dump(mode="json"),
        "model_profile": profile.model_dump(mode="json"),
        "model_pin": profile.pin().model_dump(mode="json"),
        "actual_operation_bindings": bindings,
        "source": source.model_dump(mode="json"),
        "actual_dependent_read": reads[0],
        "summary": summary,
        "lineage": [item.model_dump(mode="json") for item in facts],
        "graph_apply": False,
        "cognition_transport": "scripted",
    }


def biotech_served_model(profile: ModelProfile) -> Any:
    """New exact fixture definition: never reuse the OpenAI WP-CP-040 definition identity."""
    from mission_control.adapters.capabilities.capability_pins import PinnedModel
    from mission_control.domain.authoring.canonical import sha256_digest

    definition = {
        "schema_version": "overnight.scripted-model.v1",
        "application": "biotech",
        "profile": profile.profile,
        "vendor": profile.vendor,
        "model_id": profile.model_id,
        "structured_output": profile.structured_output,
        "transport": "scripted",
    }
    return PinnedModel.model_validate(
        {
            "ref": {
                "kind": "model",
                "logical_id": "model.overnight.biotech." + profile.profile,
                "revision": 1,
                "digest": sha256_digest(definition),
            },
            "provider": profile.vendor,
            "model_id": profile.model_id,
        }
    )


def biotech_host_pins(path: Path, profile: ModelProfile) -> Path:
    """Add the exact declaration to an already verified local fixture pin file."""
    from mission_control.adapters.capabilities.capability_pins import CapabilityPins

    pins = CapabilityPins.load(path)
    model = biotech_served_model(profile)
    assert not any(item.ref.logical_id == model.ref.logical_id for item in pins.models)
    amended = pins.model_copy(update={"models": (*pins.models, model)})
    CapabilityPins.model_validate(amended.model_dump(mode="python"))
    path.write_text(amended.model_dump_json(indent=2), encoding="utf-8")
    return path


class BiotechDecisionCapture:
    """Record exact native decide/resolve answers without changing request identity or behavior."""

    def __init__(self, destination: Path) -> None:
        self.destination = destination
        self.records: list[dict[str, Any]] = []

    def install(self, lane: Any, monkeypatch: Any) -> None:
        bridge = lane.trusted._bridge
        original = bridge._call

        async def observed(operation: Any, request: Any, access: Any, **kwargs: Any) -> Any:
            result = await original(operation, request, access, **kwargs)
            if operation in {"report.decide", "decision.resolve"}:
                self.records.append(
                    {
                        "operation": operation,
                        "request_key": kwargs["key"],
                        "request_scope": access.scope,
                        "run_id": access.origin.run_id,
                        "operation_id": access.origin.operation_id,
                        "request": request.model_dump(mode="json"),
                        "response": result,
                    }
                )
                self.destination.parent.mkdir(parents=True, exist_ok=True)
                self.destination.write_text(json.dumps(self.records, indent=2), encoding="utf-8")
            return result

        monkeypatch.setattr(bridge, "_call", observed)
