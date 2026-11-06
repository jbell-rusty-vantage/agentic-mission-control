"""Production trusted-assessment plans: who judges a revision, as whom, under which use (OVE-169).

:class:`ConfiguredTrustedPlans` is the :class:`TrustedAssessmentPlans` the production bootstrap
composes when both independent evaluator credentials are configured. For one exact output revision
it admits:

* the **producer** identity: the producing invocation's subject and operation, the producer
  credential *name* (``ANTHROPIC_API_KEY``) and ``producer.default``'s vendor;
* the **auditor** (``auditor.default``, Anthropic) under its own credential name
  (``MC_AUDITOR_ANTHROPIC_API_KEY``), its own subject ``mission-control-auditor`` and its own
  operation ``<producer operation>/auditor``; it runs first, so an auditor that cannot run spends
  no judge cognition;
* the **judge** (``judge.default``, OpenAI) under ``MC_JUDGE_OPENAI_API_KEY``, subject
  ``mission-control-judge``, operation ``<producer operation>/judge``.

Credential references are environment-variable NAMES (never values); ``evaluator_refusals`` compares
them, so the auditor never shares the producer's name (``EVALUATOR_CREDENTIAL_SHARED``), and the
bootstrap refuses configurations whose auditor value equals the producer's. The official use (use,
audience, policy and rubric of the exact KS task) comes from the evaluation context the KS binding
exposes for the revision (:class:`EvaluationContextSource`); while it cannot, the plan raises
:class:`~mission_control.application.knowledge.judgment.EvaluatorUnavailable` and the settlement
waits, never inventing a policy.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from mission_control.application.knowledge.access import InvocationAccess
from mission_control.application.knowledge.judgment import (
    EvaluatorBinding,
    EvaluatorUnavailable,
    UseSpec,
)
from mission_control.application.knowledge.trusted_settlement import TrustedPlan
from mission_control.contracts.knowledge_protocol import Ref
from mission_control.domain.knowledge.judgment import CognitionIdentity
from mission_control.domain.outputs.contracts import ExactOutput

PRODUCER_CREDENTIAL = "ANTHROPIC_API_KEY"
JUDGE_CREDENTIAL = "MC_JUDGE_OPENAI_API_KEY"
AUDITOR_CREDENTIAL = "MC_AUDITOR_ANTHROPIC_API_KEY"
JUDGE_SUBJECT = "mission-control-judge"
AUDITOR_SUBJECT = "mission-control-auditor"


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RolePin:
    """One ``models.toml`` evaluator row: vendor, model id and the family KS binds the grant to."""

    profile: str
    vendor: str
    model_id: str
    # W1 D16/D18: the row's structured-output strategy (`tool_forced`, `provider_native` or
    # `tool_auto`).
    structured_output: str | None = None
    # W1 D24: the row's OpenAI API surface (`responses` for a tool-calling OpenAI judge).
    api_surface: str | None = None

    @property
    def family(self) -> str:
        return family_of(self.model_id)


def family_of(model_id: str) -> str:
    """The model family a grant names (``gpt-5.6-terra`` -> ``gpt-5.6``; ``claude-haiku-5-5`` ->
    ``claude-haiku``): stable across tiers of one family, distinct across vendors."""

    parts = model_id.split("-")
    if model_id.startswith("claude-") and len(parts) >= 2:
        return "-".join(parts[:2])
    return "-".join(parts[:2]) if len(parts) >= 2 else model_id


@dataclass(frozen=True)
class EvaluationContext:
    """What an independent evaluator of one exact revision reads (never the producer ledger for
    the auditor). ``units``, ``support_sets`` and ``use`` are ``None`` while the KS binding does
    not expose them for the revision."""

    report: Ref
    body_artifact: Ref
    body_text: str
    assertions: tuple[dict[str, Any], ...]
    fragments: tuple[dict[str, Any], ...]
    units: tuple[tuple[str, int, int], ...] | None = None
    support_sets: tuple[dict[str, Any], ...] | None = None
    use: UseSpec | None = None

    def missing(self, *names: str) -> tuple[str, ...]:
        return tuple(name for name in names if getattr(self, name) is None)


class EvaluationContextSource(Protocol):
    async def load(self, evaluator: EvaluatorBinding, report: Ref) -> EvaluationContext:
        """The exact revision's evaluation context, read under the evaluator's own access and
        grant (KS scopes it by role); raises :class:`EvaluatorUnavailable` when it cannot now."""
        ...


class ConfiguredTrustedPlans:
    def __init__(
        self,
        *,
        producer_vendor: str,
        judge: RolePin,
        auditor: RolePin,
        context: EvaluationContextSource,
        report_of: Callable[[ExactOutput, str], Ref | None],
        judge_credential: str = JUDGE_CREDENTIAL,
        auditor_credential: str = AUDITOR_CREDENTIAL,
        producer_credential: str = PRODUCER_CREDENTIAL,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if len({producer_credential, judge_credential, auditor_credential}) != 3:
            raise ValueError("EVALUATOR_CREDENTIAL_SHARED: evaluator credentials must be distinct")
        self._producer_vendor = producer_vendor
        self._judge = judge
        self._auditor = auditor
        self._context = context
        self._report_of = report_of
        self._judge_credential = judge_credential
        self._auditor_credential = auditor_credential
        self._producer_credential = producer_credential
        self._clock = clock

    def evaluator_access(self, access: InvocationAccess, role: str) -> InvocationAccess:
        """A separate admitted invocation: own subject, own operation, new invocation id."""

        subject = JUDGE_SUBJECT if role == "judge" else AUDITOR_SUBJECT
        origin = access.origin.model_copy(
            update={"operation_id": f"{access.origin.operation_id}/{role}"}
        )
        return replace(
            access,
            origin=origin,
            subject=subject,
            invocation_id=f"inv-{role}-{uuid4()}",
            authenticated_at=self._clock(),
            recovery_grant=None,
            recovery_grants=(),
        )

    def bindings(self, access: InvocationAccess) -> tuple[EvaluatorBinding, ...]:
        auditor = EvaluatorBinding(
            role="auditor",
            credential_ref=self._auditor_credential,
            vendor=self._auditor.vendor,
            family=self._auditor.family,
            model_id=self._auditor.model_id,
            access=self.evaluator_access(access, "auditor"),
            structured_output=self._auditor.structured_output,
            api_surface=self._auditor.api_surface,
        )
        judge = EvaluatorBinding(
            role="judge",
            credential_ref=self._judge_credential,
            vendor=self._judge.vendor,
            family=self._judge.family,
            model_id=self._judge.model_id,
            access=self.evaluator_access(access, "judge"),
            structured_output=self._judge.structured_output,
            api_surface=self._judge.api_surface,
        )
        return (auditor, judge)

    async def plan(self, access: InvocationAccess, revision: ExactOutput) -> TrustedPlan:
        report = self._report_of(revision, access.origin.tenant_id)
        if report is None:
            raise EvaluatorUnavailable("the revision names no exact KS report")
        evaluators = self.bindings(access)
        context = await self._context.load(evaluators[0], report)
        if context.use is None:
            raise EvaluatorUnavailable(
                "EVALUATION_CONTEXT_INCOMPLETE: the KS binding exposes no task use/policy/rubric "
                "for this revision"
            )
        producer = CognitionIdentity(
            credential_ref=self._producer_credential,
            subject=access.subject,
            operation_ref=access.origin.operation_id,
            vendor=self._producer_vendor,
        )
        return TrustedPlan(evaluators=evaluators, use=context.use, producer=producer)


__all__ = [
    "AUDITOR_CREDENTIAL",
    "AUDITOR_SUBJECT",
    "JUDGE_CREDENTIAL",
    "JUDGE_SUBJECT",
    "PRODUCER_CREDENTIAL",
    "ConfiguredTrustedPlans",
    "EvaluationContext",
    "EvaluationContextSource",
    "RolePin",
    "family_of",
]
