"""Native `knowledge.apply` payload layouts, named by data (ADR-0063, OC-R4 / OVE-198).

The gateway composes the exact use of a host-recorded use decision into the native payload its
application's apply contract takes. Which layout is the profile's
`KnowledgePortBinding.intent_schema_ref`; the contract name and version are the profile's too.
So no application or binding is named here: an application picks one of these layouts in its
`deployments/<app>/application.toml`, and a new layout is a new entry, never a branch on an
application. An unknown reference refuses ``SCHEMA_UNSUPPORTED`` (fail closed).

- ``mc.knowledge_apply_payload.plan_with_exact_use.v1``: the plan's own fields with the full exact
  use merged in (decision, plan-level bound digest, epoch, normalized-values digest, effect key,
  originating origin). The planner computed the bound digest over bytes the host does not hold,
  so the host carries the recorded digest and the native executor recomputes it. A
  normalized-values digest is required.
- ``mc.knowledge_apply_payload.intent_envelope.v1``: ``{schemaVersion: "<name>.<version>",
  intent: <plan>, exactUse: {useDecisionId, processedEpoch, normalizedValuesDigest}}``. The plan's
  bytes are the bound bytes: the host checks the recorded digest binds the plan and the
  originating origin, and binds the plan itself.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from mission_control.application.knowledge.operations import KnowledgeRefused
from mission_control.application.ports.knowledge import RecordedUseDecision
from mission_control.contracts.knowledge_protocol import Origin, bound_effect_digest, canonical_json
from mission_control.domain.resolution.resolved import KnowledgePortBinding

PLAN_WITH_EXACT_USE: Final = "mc.knowledge_apply_payload.plan_with_exact_use.v1"
INTENT_ENVELOPE: Final = "mc.knowledge_apply_payload.intent_envelope.v1"


@dataclass(frozen=True)
class ApplyPayload:
    """The native payload plus what the effect binding binds: the plan's bytes or its digest."""

    payload: dict[str, Any]
    plan: dict[str, Any] | None = None
    bound_effect_digest: str | None = None


Layout = Callable[[KnowledgePortBinding, RecordedUseDecision, str, Origin], ApplyPayload]


def _plan_with_exact_use(
    _port: KnowledgePortBinding, decision: RecordedUseDecision, effect_key: str, origin: Origin
) -> ApplyPayload:
    if decision.normalized_values_digest is None:
        raise KnowledgeRefused(
            "SCHEMA_UNSUPPORTED", "this apply contract's exact use needs a normalized-values digest"
        )
    return ApplyPayload(
        payload=dict(decision.plan)
        | {
            "exactUse": {
                "useDecisionId": decision.use_decision_id,
                "boundEffectDigest": decision.bound_effect_digest,
                "processedEpoch": decision.processed_epoch,
                "normalizedValuesDigest": decision.normalized_values_digest,
                "effectKey": effect_key,
                "originatingOrigin": origin.model_dump(mode="json"),
            }
        },
        bound_effect_digest=decision.bound_effect_digest,
    )


def _intent_envelope(
    port: KnowledgePortBinding, decision: RecordedUseDecision, effect_key: str, origin: Origin
) -> ApplyPayload:
    plan = dict(decision.plan)
    if bound_effect_digest(canonical_json(plan).encode("utf-8"), origin) != (
        decision.bound_effect_digest
    ):
        raise KnowledgeRefused(
            "EFFECT_CONFLICT",
            "the recorded decision binds other bytes or another origin",
            effect_key=effect_key,
        )
    return ApplyPayload(
        payload={
            "schemaVersion": f"{port.apply_contract_name}.{port.apply_contract_version}",
            "intent": plan,
            "exactUse": {
                "useDecisionId": decision.use_decision_id,
                "processedEpoch": decision.processed_epoch,
                "normalizedValuesDigest": decision.normalized_values_digest,
            },
        },
        plan=plan,
    )


APPLY_PAYLOAD_LAYOUTS: Final[Mapping[str, Layout]] = {
    PLAN_WITH_EXACT_USE: _plan_with_exact_use,
    INTENT_ENVELOPE: _intent_envelope,
}


def apply_payload(
    port: KnowledgePortBinding,
    decision: RecordedUseDecision,
    *,
    effect_key: str,
    originating: Origin,
) -> ApplyPayload:
    """The native payload of one recorded decision under the profile's apply contract layout."""

    layout = APPLY_PAYLOAD_LAYOUTS.get(port.intent_schema_ref)
    if layout is None:
        raise KnowledgeRefused(
            "SCHEMA_UNSUPPORTED",
            f"apply contract {port.apply_contract_name}@{port.apply_contract_version} names "
            f"payload layout {port.intent_schema_ref}, which this host does not build",
        )
    return layout(port, decision, effect_key, originating)


__all__ = [
    "APPLY_PAYLOAD_LAYOUTS",
    "INTENT_ENVELOPE",
    "PLAN_WITH_EXACT_USE",
    "ApplyPayload",
    "apply_payload",
]
