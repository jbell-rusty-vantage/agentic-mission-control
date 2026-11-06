"""Production composition of the trusted settlement with real independent evaluators (OVE-169).

Called by ``compose_knowledge_lane`` once the KS binding passed its describe preflight. With
neither evaluator credential configured the knowledge lane keeps the ``report.assess`` handoff
only (no trusted settlement). With both, it composes:

* the evaluator runner (``adapters/deep_agents/evaluators.ModelEvaluatorRunner``): the judge on
  ``judge.default`` under ``MC_JUDGE_OPENAI_API_KEY``, the auditor on ``auditor.default`` under
  ``MC_AUDITOR_ANTHROPIC_API_KEY``, each a separate admitted invocation;
* the plans (``ConfiguredTrustedPlans``) naming the producer's ``ANTHROPIC_API_KEY`` and
  ``producer.default`` vendor;
* the trusted judgment bridge (KS observe, seal, decide, resolve; promote; demotion record) and
  ``TrustedSettlement`` behind the WI-04 settlement seam.

Refusals (``KnowledgeConfigurationError``, startup stops): only one evaluator credential; an
auditor credential whose value is the producer's (``EVALUATOR_CREDENTIAL_SHARED``: a separate name
over the same key is not independence); a judge on the producer's vendor; a missing model row; and
a KS binding that advertises the scripted census auditor (``auditorKind: scripted``, a disposable
W0 double) while real evaluators are configured.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import asyncpg

from mission_control.bootstrap.settings import Settings


class TrustedCompositionError(ValueError):
    """The configured evaluators cannot be composed (startup refuses)."""


def _check_evaluator_schemas(*rows: Any) -> None:
    """W1 D16 at composition (before any run): each evaluator row declares a structured-output
    strategy, and a ``provider_native`` Anthropic row's answer schema is inside Anthropic's
    ``output_config.format`` subset; otherwise the trusted path never composes (no evaluation
    could succeed, so it must not become a durable wait)."""

    from pydantic import BaseModel

    from mission_control.adapters.deep_agents.evaluators import AuditorAnswer, JudgeAnswer
    from mission_control.adapters.deep_agents.output_format import (
        AnthropicOutputSchemaRefused,
        anthropic_output_schema,
    )

    schemas: tuple[type[BaseModel], ...] = (JudgeAnswer, AuditorAnswer)
    for row, schema in zip(rows, schemas, strict=True):
        if row.structured_output is None:
            raise TrustedCompositionError(
                f"OUTPUT_SCHEMA_UNSUPPORTED: {row.profile} declares no structured_output strategy"
            )
        if row.requires_responses_api() and row.api_surface != "responses":
            raise TrustedCompositionError(
                f"API_SURFACE_UNSUPPORTED: {row.profile} calls function tools on OpenAI and "
                'must declare api_surface = "responses" (W1 D24)'
            )
        if row.structured_output == "provider_native" and row.vendor == "anthropic":
            try:
                anthropic_output_schema(schema)
            except AnthropicOutputSchemaRefused as refused:
                raise TrustedCompositionError(
                    f"OUTPUT_SCHEMA_UNSUPPORTED: {row.profile} cannot bind {schema.__name__}: "
                    f"{refused}"
                ) from None


def compose_trusted_settlement(
    settings: Settings,
    pool: asyncpg.Pool,
    *,
    application_id: str,
    gateway: Any,
    output_store: Any,
    submissions: Any,
    auditor_kind: str,
    clock: Callable[[], datetime],
) -> Any | None:
    judge_key = settings.mc_judge_openai_api_key
    auditor_key = settings.mc_auditor_anthropic_api_key
    if judge_key is None and auditor_key is None:
        return None
    if judge_key is None or auditor_key is None:
        raise TrustedCompositionError(
            "independent evaluation needs both MC_JUDGE_OPENAI_API_KEY and "
            "MC_AUDITOR_ANTHROPIC_API_KEY"
        )
    producer_key = settings.anthropic_api_key
    if producer_key is not None and (
        auditor_key.get_secret_value() == producer_key.get_secret_value()
    ):
        raise TrustedCompositionError(
            "EVALUATOR_CREDENTIAL_SHARED: MC_AUDITOR_ANTHROPIC_API_KEY holds the producer's key"
        )
    if auditor_kind == "scripted":
        raise TrustedCompositionError(
            "the knowledge binding advertises the scripted census auditor (a disposable double); "
            "unset KS_KNOWLEDGE_AUDITOR_SCRIPT_FILE when real evaluators are configured"
        )

    from mission_control.adapters.deep_agents.evaluators import (
        KnowledgeEvaluationContextSource,
        ModelEvaluatorRunner,
        deep_agents_invoker,
        prices_from_rows,
    )
    from mission_control.adapters.postgres.context.transfer_plans import (
        PostgresTransferPlanStore,
    )
    from mission_control.adapters.postgres.knowledge.operations import PostgresKnowledgeJournal
    from mission_control.adapters.postgres.knowledge.use_decisions import PostgresMemberDecisions
    from mission_control.application.knowledge.effect_receipts import JournalEffectReceipts
    from mission_control.application.knowledge.evaluator_plans import (
        AUDITOR_CREDENTIAL,
        JUDGE_CREDENTIAL,
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

    root = settings.deployments_root
    rows = {
        row.profile: row
        for row in load_model_catalog_file(models_path(root, application_id)).models
    }
    try:
        producer, judge, auditor = (
            rows[name] for name in ("producer.default", "judge.default", "auditor.default")
        )
    except KeyError as missing:
        raise TrustedCompositionError(f"models.toml has no {missing.args[0]} row") from None
    if judge.vendor == producer.vendor:
        raise TrustedCompositionError(
            "JUDGE_VENDOR_NOT_INDEPENDENT: judge.default is the producer's vendor"
        )
    _check_evaluator_schemas(judge, auditor)
    profile = load_application_profile(root, application_id).profile.outputs
    context = KnowledgeEvaluationContextSource(gateway)
    runner = ModelEvaluatorRunner(
        context=context,
        invoke=deep_agents_invoker(
            {
                JUDGE_CREDENTIAL: judge_key.get_secret_value(),
                AUDITOR_CREDENTIAL: auditor_key.get_secret_value(),
            }
        ),
        # S2: every evaluator row (judge, second-family judge, auditor) is priced.
        prices=prices_from_rows(
            [
                rows[name]
                for name in ("judge.default", "second_family_judge.default", "auditor.default")
                if name in rows
            ]
        ),
        clock=clock,
    )
    plans = ConfiguredTrustedPlans(
        producer_vendor=producer.vendor,
        judge=RolePin(
            judge.profile,
            judge.vendor,
            judge.model_id,
            judge.structured_output,
            judge.api_surface,
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
        clock=clock,
    )
    fulfillment = OutputFulfillmentService(
        output_store,
        submissions,
        clock=clock,
        realizations=PostgresTransferPlanStore(pool),
        reference_uses=TrustedReferenceUses(output_store),
        effect_receipts=JournalEffectReceipts(PostgresKnowledgeJournal(pool)),
        trusted_validators=frozenset({profile.assessment_pin}),
        member_decisions=PostgresMemberDecisions(pool, bridge_actor=TRUSTED_BRIDGE_ACTOR),
    )
    bridge = TrustedJudgmentBridge(
        gateway=gateway,
        fulfillment=fulfillment,
        store=output_store,
        profile=profile,
        runner=runner,
        judge_pin=EvaluatorPin(profile=judge.profile, vendor=judge.vendor, model_id=judge.model_id),
        decisions=gateway.decisions,
        clock=clock,
    )
    return TrustedSettlement(
        bridge=bridge, store=output_store, plans=plans, assessment_pin=profile.assessment_pin
    )


def compose_native_write(
    trusted: Any,
    gateway: Any,
    output_store: Any,
    *,
    capability_pin: str = "knowledge.knowledge_apply@1",
) -> Any:
    """The in-invocation native write (W1), or ``None`` without a trusted settlement.

    The application's apply payload layout selects what exists in its native schema
    (ESCALATION H11): the plan-with-exact-use layout (AI Engineer AIDB) builds a
    ``claim.materialize`` intent and asks KS for the exact digest (``knowledge.plan_preview``);
    the intent-envelope layout (Biotech) computes the digest in MC but has no report intent, so
    its native write refuses ``SCHEMA_UNSUPPORTED``.
    """

    if trusted is None:
        return None
    from mission_control.application.context.resolution import ContentResolutionService
    from mission_control.application.knowledge.apply_payload import PLAN_WITH_EXACT_USE
    from mission_control.application.knowledge.native_write import (
        ClaimMaterializeIntentBuilder,
        KnowledgePlanPreview,
        LocalIntentEnvelopePreview,
        NativeWriteService,
        NoNativeIntent,
    )

    port = gateway.knowledge
    if port.intent_schema_ref == PLAN_WITH_EXACT_USE:
        builder: Any = ClaimMaterializeIntentBuilder(
            f"{port.apply_contract_name}.{port.apply_contract_version}"
        )
        preview: Any = KnowledgePlanPreview(gateway)
    else:
        builder = NoNativeIntent()
        preview = LocalIntentEnvelopePreview()
    return NativeWriteService(
        bridge=trusted._bridge,
        plans=trusted._plans,
        outputs=output_store,
        reports=ContentResolutionService(gateway),
        port=port,
        builder=builder,
        preview=preview,
        decisions=gateway.decisions,
        existing_effect=lambda handle, access: gateway.existing_decision_effect(
            handle, access, capability_pin=capability_pin
        ),
    )


def trusted_settlement_composable(settings: Settings, application_id: str) -> bool:
    """Whether this installation's worker composes the trusted settlement (review N2): the same
    `compose_trusted_settlement` with the binding's I/O left out (construction only, no call);
    the KS descriptor's auditor kind is the worker's startup check."""

    from datetime import UTC
    from datetime import datetime as _datetime

    class _Gateway:
        decisions = None

    try:
        composed = compose_trusted_settlement(
            settings,
            None,
            application_id=application_id,
            gateway=_Gateway(),
            output_store=None,
            submissions=None,
            auditor_kind="independent",
            clock=lambda: _datetime.now(UTC),
        )
    except TrustedCompositionError:
        return False
    return composed is not None


def trusted_receipt(settlement: Any | None) -> dict[str, Any]:
    """The startup receipt's evaluator section (credential NAMES only)."""

    if settlement is None:
        return {"composed": False}
    from mission_control.application.knowledge.evaluator_plans import (
        AUDITOR_CREDENTIAL,
        JUDGE_CREDENTIAL,
    )

    return {
        "composed": True,
        "judge_credential": JUDGE_CREDENTIAL,
        "auditor_credential": AUDITOR_CREDENTIAL,
    }


__all__ = [
    "TrustedCompositionError",
    "compose_trusted_settlement",
    "trusted_receipt",
    "trusted_settlement_composable",
]
