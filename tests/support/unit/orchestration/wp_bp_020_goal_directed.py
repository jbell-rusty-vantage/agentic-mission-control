"""Builders, constants and fakes that other test files import.

Moved from tests/unit/orchestration/test_goal_loop_rules.py.
"""

from __future__ import annotations

from dataclasses import asdict, replace

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import GoalDirectedBlueprint
from mission_control.domain.authoring.fixtures import GENERIC_GOAL_DIRECTED
from mission_control.domain.programs.contracts import (
    GoalContinuationState,
    GoalDirectedExecutionState,
    GoalDirectedRunInput,
    GoalExecutionClaim,
    GoalExecutionResult,
    GoalHandoff,
    GoalRevision,
    GoalVerificationResult,
)
from mission_control.domain.programs.goal_directed import GoalDirectedInterpreter

ENVELOPE_DIGEST = sha256_digest("wp-bp-020-envelope")
STALE_FRONTIER_DIGEST = sha256_digest("wp-bp-020-stale-frontier")


def _blueprint(**updates: object) -> GoalDirectedBlueprint:
    payload = GENERIC_GOAL_DIRECTED.model_dump(mode="python")
    payload.update(updates)
    return GoalDirectedBlueprint.model_validate(payload)


def _revision(
    *,
    revision: int = 1,
    parent_revision_id: str | None = None,
    envelope_digest: str = ENVELOPE_DIGEST,
) -> GoalRevision:
    values = {
        "schema_version": "belllabs.goal-revision.v1",
        "revision_id": f"goal-revision:{revision}",
        "revision": revision,
        "parent_revision_id": parent_revision_id,
        "envelope_digest": envelope_digest,
        "objective": "Produce one independently verified bounded result.",
        "tactical_changes": (() if revision == 1 else ("triangulate another source",)),
        "evidence_refs": ("input:goal",),
        "unmet_obligations": ("fixture-obligation",),
        "proposer": "application:test",
        "deciding_authority": "authority:test",
        "applicability": "remaining_run",
        "tactics": (),
        "subgoals": (),
        "coverage_emphasis": (),
    }
    return GoalRevision(canonical_digest=sha256_digest(values), **values)  # type: ignore[arg-type]


def _run_input(
    configured: GoalDirectedBlueprint,
    *,
    revision: GoalRevision | None = None,
    continuation: GoalContinuationState | None = None,
) -> GoalDirectedRunInput:
    active_revision = revision or _revision()
    return GoalDirectedRunInput(
        run_id="run-goal",
        request_scope="tenant-1",
        effective_configuration_digest=sha256_digest("erc"),
        blueprint_digest=sha256_digest(configured),
        blueprint=configured.model_dump(mode="json"),
        envelope_digest=ENVELOPE_DIGEST,
        initial_revision=active_revision,
        required_obligation_refs=("fixture-obligation",),
        required_output_contract_refs=("fixture-output",),
        semantic_input_binding_ref="semantic-input:test",
        technical_segment=2 if continuation is not None else 1,
        continuation_state=continuation,
    )


def _claim(
    configured: GoalDirectedBlueprint,
) -> tuple[GoalDirectedInterpreter, GoalDirectedExecutionState, GoalExecutionClaim]:
    interpreter = GoalDirectedInterpreter(configured)
    state = interpreter.initial_state(_run_input(configured))
    claimed, claim = interpreter.claim_execution(state)
    return interpreter, claimed, claim


def _execution(
    claim: GoalExecutionClaim,
    *,
    handoff: GoalHandoff | None = None,
    tokens: int = 0,
    authority_breach: bool = False,
    hard_budget: bool = False,
    irrecoverable: bool = False,
) -> GoalExecutionResult:
    return GoalExecutionResult(
        identity=claim.identity,
        disposition="completed",
        operation_identity=f"{claim.identity.iteration.semantic_key}:executor",
        operation_binding_ref="binding:executor",
        session_id=claim.session_id,
        workspace_id=claim.workspace_namespace,
        writable_paths=("/goal/executor/work",),
        output_refs=("artifact:result",),
        completion_claim=True,
        actual_usage={"tokens.total": tokens},
        authority_breach_ref=("authority:breach" if authority_breach else ""),
        hard_budget_exhausted_dimensions=(("tokens.total",) if hard_budget else ()),
        irrecoverable_failure_ref=("failure:irrecoverable" if irrecoverable else ""),
        accepted_fact_refs=("fact:accepted",),
        evidence_refs=("evidence:accepted",),
        handoff=handoff,
        output_contract_ref="fixture-output",
    )


def _verification(
    claim: GoalExecutionClaim,
    *,
    decision: str = "rejected",
    progress: bool = True,
    accepted: bool = False,
    blocker: str = "",
    authority_breach: bool = False,
    hard_budget: bool = False,
    irrecoverable: bool = False,
    proposed_revision: GoalRevision | None = None,
    scope_expansion_route: str | None = None,
) -> GoalVerificationResult:
    values = {
        "schema_version": "belllabs.goal-verification.v1",
        "verification_id": f"verification:{claim.identity.semantic_key}",
        "executor_identity": claim.identity,
        "verifier_operation_identity": (
            f"{claim.identity.iteration.semantic_key}:independent-verifier"
        ),
        "verifier_binding_ref": "binding:verifier",
        "verifier_policy_binding_ref": "verifier:fixture@1",
        "verifier_session_id": f"{claim.session_id}:verifier",
        "verifier_workspace_id": f"{claim.workspace_namespace}:verifier",
        "verifier_writable_paths": ("/goal/verifier/work",),
        "decision": decision,
        "verification_ref": f"verification-ref:{claim.identity.semantic_key}",
        "rubric_ref": "rubric:fixture@1",
        "rubric_version": 1,
        "acceptance_contract_ref": GENERIC_GOAL_DIRECTED.acceptance_contract,
        "acceptance_version": 1,
        "progress_made": progress,
        "accepted_obligation_refs": (("fixture-obligation",) if accepted else ()),
        "findings": (),
        "evidence_refs": ("evidence:verified",),
        "admitted_executor_output_refs": ("artifact:result",),
        "admitted_executor_evidence_refs": ("evidence:accepted",),
        "unmet_obligations": (() if accepted else ("fixture-obligation",)),
        "obligation_applicability": (("fixture-obligation", True),),
        "stale_frontier_digest": STALE_FRONTIER_DIGEST,
        "blocker_class": blocker,
        "authority_breach_ref": ("authority:breach" if authority_breach else ""),
        "hard_budget_exhausted_dimensions": (("tokens.total",) if hard_budget else ()),
        "soft_budget_dimensions": (),
        "irrecoverable_failure_ref": ("failure:irrecoverable" if irrecoverable else ""),
        "proposed_revision": proposed_revision,
        "scope_expansion_route": scope_expansion_route,
        "route_ref": ("route:accepted" if scope_expansion_route else ""),
        "actual_usage": {"tokens.total": 1},
        "effect_refs": (),
        "output_contract_ref": "fixture-output",
    }
    draft = GoalVerificationResult(  # type: ignore[arg-type]
        verification_digest="pending",
        **values,
    )
    payload = asdict(draft)
    payload.pop("verification_digest")
    return replace(draft, verification_digest=sha256_digest(payload))
