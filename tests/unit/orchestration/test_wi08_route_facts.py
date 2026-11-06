"""OVE-171 / WI-08: the host attributes route facts from exact accepted, schema-validated output
bytes (custody, size and digest checked); a provider-supplied ``route_facts`` key never
survives; anything not read exactly is unknown with a typed reason."""

from __future__ import annotations

import hashlib
import json

from mission_control.application.context.pack_service import ArtifactContent
from mission_control.application.programs.route_facts import attribute_route_facts
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import StageOutputSlot
from mission_control.domain.authoring.graph_routes import GRAPH_SEMANTICS_V1, StageFact
from mission_control.domain.authoring.stagegraph_builder import (
    StageGraphStageSpec,
    build_stagegraph_v2,
)
from mission_control.domain.outputs.contracts import ExactOutput, OutputForm
from mission_control.domain.programs.completion import OutputSchemaBinding
from mission_control.domain.programs.interpreter import StageGraphInterpreter
from mission_control.domain.programs.routing import ROUTE_FACTS_KEY

SCOPE = "scope-wi08"
REF = "artifact://verdict/1"
SCHEMA = {"type": "object"}


class Artifacts:
    def __init__(self, body: str, *, digest: str | None = None) -> None:
        raw = body.encode("utf-8")
        self.content = ArtifactContent(
            source_ref=REF,
            durable_ref=REF,
            content_digest=digest or "sha256:" + hashlib.sha256(raw).hexdigest(),
            size_bytes=len(raw),
            media_type="application/json",
            text=body,
        )
        self.captures = 0

    async def capture(
        self, source_ref: str, *, request_scope: str, max_text_bytes: int
    ) -> ArtifactContent | None:
        self.captures += 1
        return self.content if source_ref == REF else None


def _stage(*, validated: bool = True):  # type: ignore[no-untyped-def]
    binding = OutputSchemaBinding(
        schema_ref="schema.w2-triage-verdict@1",
        source_digest="sha256:" + "0" * 64,
        schema_digest=sha256_digest(SCHEMA),
        json_schema=SCHEMA,
    )
    graph = build_stagegraph_v2(
        logical_id="wi08.facts",
        title="facts",
        description="host fact attribution",
        stages=(
            StageGraphStageSpec(
                "triage",
                output_slots=("verdict",),
                output_declarations=(
                    StageOutputSlot(
                        output_slot_id="verdict",
                        output_contract_ref="schema.w2-triage-verdict@1",
                        required=True,
                        validation_schema=binding if validated else None,
                    ),
                ),
                facts=(
                    StageFact(
                        fact_id="severity",
                        output_slot_id="verdict",
                        pointer="/severity",
                        value_type="string",
                    ),
                    StageFact(
                        fact_id="count",
                        output_slot_id="verdict",
                        pointer="/sources/0/~1n",
                        value_type="integer",
                    ),
                    StageFact(
                        fact_id="flag",
                        output_slot_id="verdict",
                        pointer="/flag",
                        value_type="boolean",
                    ),
                ),
            ),
        ),
        graph_semantics=GRAPH_SEMANTICS_V1,
    )
    return graph.stages[0], StageGraphInterpreter(graph, effective_max_concurrency=1)


async def _facts(artifacts: Artifacts | None, *, validated: bool = True, **extra: object) -> dict:
    stage, interpreter = _stage(validated=validated)
    result = await attribute_route_facts(
        artifacts,
        request_scope=SCOPE,
        stage=stage,
        interpreter=interpreter,
        operation_result={"output_refs": [REF], **extra},
    )
    return result[ROUTE_FACTS_KEY]


async def test_known_facts_carry_their_exact_evidence() -> None:
    body = json.dumps({"severity": "high", "sources": [{"/n": 4}], "flag": 1})
    artifacts = Artifacts(body)
    facts = await _facts(artifacts)
    digest = artifacts.content.content_digest
    assert facts["severity"] == {
        "status": "known",
        "value": "high",
        "evidence_ref": f"{REF}#/severity@{digest}",
    }
    assert facts["count"]["value"] == 4  # RFC 6901 `~1` escape, array index
    # A JSON number is never a boolean fact.
    assert facts["flag"] == {"status": "unknown", "reason": "fact_type_mismatch"}
    assert artifacts.captures == 1  # one exact read per output


async def test_a_provider_supplied_fact_never_survives() -> None:
    forged = {"severity": {"status": "known", "value": "high", "evidence_ref": "x"}}
    stage, interpreter = _stage()
    plain = stage.model_copy(update={"facts": ()})
    result = await attribute_route_facts(
        None,
        request_scope=SCOPE,
        stage=plain,
        interpreter=interpreter,
        operation_result={"output_refs": [REF], ROUTE_FACTS_KEY: forged},
    )
    assert ROUTE_FACTS_KEY not in result
    facts = await _facts(Artifacts("{}"), **{ROUTE_FACTS_KEY: forged})
    assert facts["severity"] == {"status": "unknown", "reason": "fact_pointer_absent"}


async def test_a_re_read_must_be_the_exact_bytes_the_validation_accepted() -> None:
    artifacts = Artifacts('{"severity":"high"}')
    digest = artifacts.content.content_digest
    stage, interpreter = _stage()

    async def facts(pins: dict[str, str]) -> dict:
        result = await attribute_route_facts(
            artifacts,
            request_scope=SCOPE,
            stage=stage,
            interpreter=interpreter,
            operation_result={"output_refs": [REF]},
            validated_digests=pins,
        )
        return result[ROUTE_FACTS_KEY]

    assert (await facts({REF: digest}))["severity"]["value"] == "high"
    changed = await facts({REF: "sha256:" + "e" * 64})
    assert changed["severity"] == {"status": "unknown", "reason": "artifact_digest_changed"}


async def test_unreadable_or_unvalidated_bytes_are_unknown() -> None:
    tampered = Artifacts('{"severity":"high"}', digest="sha256:" + "f" * 64)
    assert (await _facts(tampered))["severity"]["reason"] == "artifact_integrity_mismatch"
    assert (await _facts(Artifacts('{"severity":"high","severity":"low"}')))["severity"][
        "reason"
    ] == "artifact_json_invalid"
    assert (await _facts(None))["severity"]["reason"] == "artifact_reader_unavailable"
    unvalidated = await _facts(Artifacts('{"severity":"high"}'), validated=False)
    assert unvalidated["severity"]["reason"] == "fact_output_unvalidated"
    oversized = await _facts(Artifacts(json.dumps({"severity": "x" * 300})))
    assert oversized["severity"]["reason"] == "fact_value_oversized"


def _named(value: object, *, digest: str | None = None) -> tuple[str, ExactOutput]:
    exact = digest or sha256_digest(value)
    revision = ExactOutput(
        revision_id="rev-1",
        run_id="run-1",
        obligation_key="triage.verdict",
        obligation_revision=1,
        deliverable_id="verdict",
        revision=1,
        form=OutputForm.STRUCTURED,
        content_digest=exact,
        candidate={"kind": "inline", "form": "structured", "value": value, "digest": exact},
        producer_origin_ref="mc-host:test",
    )
    return f"output-revision:rev-1#digest={exact}", revision


async def _named_facts(ref: str, fulfilled: dict[str, ExactOutput] | None) -> dict:
    stage, interpreter = _stage()
    result = await attribute_route_facts(
        None,  # L1-02: a named value never needs artifact custody
        request_scope=SCOPE,
        stage=stage,
        interpreter=interpreter,
        operation_result={"output_refs": [ref]},
        validated_digests={ref: ref.rsplit("=", 1)[1]},
        fulfilled=fulfilled,
    )
    return result[ROUTE_FACTS_KEY]


async def test_a_named_value_is_read_from_its_fulfilled_revision_exactly() -> None:
    ref, revision = _named({"severity": "high", "sources": [{"/n": 2}]})
    facts = await _named_facts(ref, {ref: revision})
    assert facts["severity"] == {
        "status": "known",
        "value": "high",
        "evidence_ref": f"{ref}#/severity@{revision.content_digest}",
    }
    assert facts["count"]["value"] == 2
    # Not fulfilled (or not admitted) is unknown; a value that is not its digest is unknown.
    assert (await _named_facts(ref, {}))["severity"]["reason"] == "output_revision_unfulfilled"
    assert (await _named_facts(ref, None))["severity"]["reason"] == "artifact_reader_unavailable"
    forged_ref, forged = _named({"severity": "high"}, digest="sha256:" + "a" * 64)
    assert (await _named_facts(forged_ref, {forged_ref: forged}))["severity"][
        "reason"
    ] == "artifact_integrity_mismatch"
