"""Scripted evaluator invocation behind the normal exact-context/KS settlement machinery."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any


def install_scripted_trusted(
    lane: Any, pool: Any, application: str, *, producer_vendor: str
) -> Any:
    from tests.fixtures.models import DEPLOYMENTS

    from mission_control.adapters.deep_agents.evaluators import (
        AuditorAnswer,
        CallUsage,
        JudgeAnswer,
        KnowledgeEvaluationContextSource,
        ModelEvaluatorRunner,
        prices_from_rows,
    )
    from mission_control.adapters.postgres.context.transfer_plans import PostgresTransferPlanStore
    from mission_control.adapters.postgres.knowledge.operations import PostgresKnowledgeJournal
    from mission_control.adapters.postgres.knowledge.output_contracts import (
        PostgresOutputContractStore,
    )
    from mission_control.adapters.postgres.knowledge.use_decisions import PostgresMemberDecisions
    from mission_control.application.knowledge.effect_receipts import JournalEffectReceipts
    from mission_control.application.knowledge.evaluator_plans import (
        ConfiguredTrustedPlans,
        RolePin,
    )
    from mission_control.application.knowledge.judgment import TrustedJudgmentBridge
    from mission_control.application.knowledge.trusted_settlement import (
        TrustedSettlement,
        report_ref,
    )
    from mission_control.application.outputs.fulfillment import (
        OutputFulfillmentService,
        TrustedReferenceUses,
    )
    from mission_control.bootstrap.application_profiles import load_application_profile
    from mission_control.bootstrap.model_profiles import load_model_catalog_file, models_path
    from mission_control.domain.knowledge.judgment import TRUSTED_BRIDGE_ACTOR, EvaluatorPin

    calls: list[dict[str, Any]] = []

    async def invoke(evaluator: Any, prompt: str, body: str, schema: Any) -> Any:
        calls.append(
            {
                "role": evaluator.role,
                "credential": evaluator.credential_ref,
                "subject": evaluator.access.subject,
                "body": body,
                "instructions": prompt,
            }
        )
        assertion_part, remainder = body.split("\n# ", 1)
        assertions = re.findall(r"^(\d+)\. (.+)$", assertion_part, re.MULTILINE)
        if schema is JudgeAnswer:
            fragments = re.findall(r"^\[([^]]+)\] (.+)$", remainder, re.MULTILINE)
            verdicts = []
            for number, statement in assertions:
                matches = [
                    identity
                    for identity, quote in fragments
                    if statement in quote or quote in statement
                ]
                verdicts.append(
                    {
                        "assertion": int(number),
                        "attribution": "correct",
                        "support": "full_support" if matches else "insufficient_evidence",
                        "cited_fragments": matches,
                        "rationale": "Scripted exact quoted-text comparison.",
                    }
                )
            return JudgeAnswer.model_validate({"verdicts": verdicts}), CallUsage(((1, 1),))
        assert schema is AuditorAnswer
        claims = [
            {"quote": statement, "assertion": int(number)}
            for number, statement in assertions
            if statement in remainder
        ]
        return AuditorAnswer.model_validate(
            {"claims": claims, "rationale": "Scripted exact-body census."}
        ), CallUsage(((1, 1),))

    def now() -> datetime:
        return datetime.now(UTC)

    rows = {
        row.profile: row
        for row in load_model_catalog_file(models_path(DEPLOYMENTS, application)).models
    }
    judge = rows["judge.default"]
    if judge.vendor == producer_vendor:
        # The fixture producer can select another vendor than producer.default. Use
        # an existing exact opposite-vendor model row, retaining its truthful profile pin.
        judge = next(row for row in rows.values() if row.vendor != producer_vendor)
    auditor = rows["auditor.default"]
    context = KnowledgeEvaluationContextSource(lane.gateway)
    output_store = PostgresOutputContractStore(pool)
    profile = load_application_profile(DEPLOYMENTS, application).profile.outputs
    plans = ConfiguredTrustedPlans(
        producer_vendor=producer_vendor,
        producer_credential=(
            "OPENAI_API_KEY" if producer_vendor == "openai" else "ANTHROPIC_API_KEY"
        ),
        judge=RolePin(
            judge.profile, judge.vendor, judge.model_id, judge.structured_output, judge.api_surface
        ),
        auditor=RolePin(
            auditor.profile,
            auditor.vendor,
            auditor.model_id,
            auditor.structured_output,
            auditor.api_surface,
        ),
        context=context,
        report_of=lambda revision, tenant: report_ref(revision, tenant=tenant),
        clock=now,
    )
    fulfillment = OutputFulfillmentService(
        output_store,
        lane.submissions,
        clock=now,
        realizations=PostgresTransferPlanStore(pool),
        reference_uses=TrustedReferenceUses(output_store),
        effect_receipts=JournalEffectReceipts(PostgresKnowledgeJournal(pool)),
        trusted_validators=frozenset({profile.assessment_pin}),
        member_decisions=PostgresMemberDecisions(pool, bridge_actor=TRUSTED_BRIDGE_ACTOR),
    )
    runner = ModelEvaluatorRunner(
        context=context, invoke=invoke, prices=prices_from_rows([judge, auditor]), clock=now
    )
    bridge = TrustedJudgmentBridge(
        gateway=lane.gateway,
        fulfillment=fulfillment,
        store=output_store,
        profile=profile,
        runner=runner,
        judge_pin=EvaluatorPin(profile=judge.profile, vendor=judge.vendor, model_id=judge.model_id),
        decisions=lane.gateway.decisions,
        clock=now,
    )
    trusted = TrustedSettlement(
        bridge=bridge, store=output_store, plans=plans, assessment_pin=profile.assessment_pin
    )
    lane.toolset.trusted = trusted
    lane.toolset.uncomposed_trusted = None
    lane.startup_receipt["fixture_evaluators"] = {"kind": "scripted", "calls": calls}
    return replace(lane, trusted=trusted)
