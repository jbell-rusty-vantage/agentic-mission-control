---
type: Concept
category: qualification
title: Trusted judgment and use review
description: "How separate judge and auditor invocations reach Knowledge Services sealing, exact use decisions and qualified review through the authenticated K01 transport, how MC records, supersedes and promotes from them, and where the review wait lives (Sprint OC WI-03)."
tags: [mission-control, knowledge-services, outputs, assessment, review, implementation]
aliases: [judge, auditor, use review, native write decision]
questions:
  - How do judge and auditor verdicts reach KS and get promoted?
  - Who may review a decision and what does review refuse?
  - How does a native write bind its exact digest to a decision?
updated: 2026-11-01
---

# Trusted judgment and use review

Ordinary independent judgments reach KS through
[`application/knowledge/judgment.py`](../../src/mission_control/application/knowledge/judgment.py),
never self-recorded and never from process memory. The judge, second-family judge and auditor are
separate admitted invocations (`EvaluatorBinding`: own credential reference, subject, operation;
a judge on another vendor than the producer and on `judge.default`;
[`domain/knowledge/judgment.py`](../../src/mission_control/domain/knowledge/judgment.py) refuses
`EVALUATOR_IS_PRODUCER`, `EVALUATOR_CREDENTIAL_SHARED`, `JUDGE_VENDOR_NOT_INDEPENDENT`,
`JUDGE_PIN_MISMATCH` before anything is sent). `KnowledgeGateway.trusted` sends `report.observe`
under a credential carrying the host's `evaluation` grant (`credential-evaluation.v1`), then
`report.seal`, `report.decide` and `decision.resolve`; KS binds the role from the grant and refuses
the producer's own subject. The bridge records one `Assessment@1` by its own assessor origin
citing the exact KS decision: only a KS rejection fails, ungrounded disagreement and a pending
review hold (`review`), an exhausted evaluator retry records `unavailable`. A passing verdict
promotes the revision through `promote_output` when every required deliverable requirement stands
at `pass`. `use_gate` applies the Application Profile minimums (`required_review_classes`,
`consequential_signoff_classes`) to the current resolution: official use versus authorized held
review/repair.

The wait lives behind the WI-04 settlement seam
([`trusted_settlement.py`](../../src/mission_control/application/knowledge/trusted_settlement.py),
`KnowledgeToolset.trusted`): a pass answers `waiting/review_pending` with the exact KS decision
refs, or raises while an evaluator is unavailable; after a restart the next pass re-resolves the
exact decision, supersedes and promotes. `knowledge_apply` resolves decisions from the durable
`PostgresUseDecisionStore` (release 1.7.0 migration `0059`). A seal KS cannot sign
(`CAPABILITY_UNAVAILABLE` / `seal_key_*`: the installation does not pin the executor's seal key)
raises a typed refusal whose `issues` carry KS's message (the key id) and the operator action;
the settlement waits `settlement_unavailable`, and the next pass recovers every observation from
KS by its dispatch marker and seals, with no paid evaluator rerun. The HTTP client never re-sends
`invoke` (W1 D25; `tests/unit/knowledge/test_w1_d25_seal_key_wait.py`).

Production composition ([`bootstrap/trusted_judgment.py`](../../src/mission_control/bootstrap/trusted_judgment.py)):
`compose_knowledge_lane` composes the trusted settlement when both `MC_JUDGE_OPENAI_API_KEY` and
`MC_AUDITOR_ANTHROPIC_API_KEY` are set, and refuses startup on one key only, an auditor key equal to the
producer's `ANTHROPIC_API_KEY`, a judge on the producer's vendor, or a KS binding advertising the scripted census
auditor. `ConfiguredTrustedPlans` (`evaluator_plans.py`) admits the auditor (first) and the judge as separate
invocations (own subject, operation `<producer op>/<role>`, credential name, `models.toml` pin).
`ModelEvaluatorRunner` (`adapters/deep_agents/evaluators.py`) runs each role as one bounded Deep Agents run
(`create_deep_agent`, structured `response_format`, no added tools or subagents) and builds the KS documents
deterministically: judge `attribution` per assertion and `support` per support set; auditor census occurrences
with UTF-16 spans. A judge batch must answer every assertion with a rule-valid verdict, else the evaluator waits
(a partial batch would trigger the KS role lock). Its context is KS `knowledge.read` `evaluation-context-read/v1`
under the evaluator's own grant, re-verified by body digest. `usage.costUsd` is priced from the `models.toml` row
and its long-prompt tier for every model call. A launch whose Stage Graph has dependent inputs refuses
`dependent_inputs_unavailable` when no trusted settlement can compose. Proof:
`tests/unit/knowledge/test_trusted_judgment.py`, `tests/conformance/test_trusted_assessment_protocol.py`,
`tests/integration/postgres/test_trusted_judgment_postgres.py` and
`tests/integration/temporal/test_wi03_trusted_review_restart.py` (deterministic KS double).

A role observes a run once (KS refuses a second batch with `evaluator_role_observed`; the bridge
treats it as observed), so a failing verdict is sticky for that revision and a judge cannot be
re-run until it passes. Promotion re-reads the standing assessment and current eligibility just
before the head compare-and-set. Heads are never deleted, so a revocation after promotion
demotes logically: a later pass records a superseding non-pass assessment (`TrustedOutcome.demoted`)
and `head_demoted` keeps every consumer from admitting that head; the produced-output resolver
re-resolves each head's KS decision first (`TrustedSettlement.recheck`); while the plans or KS are
unavailable that re-check changes nothing, so the standing record decides and a head revoked at KS
stays admitted until a re-check succeeds. Dependent-stage inputs are
therefore required (`DEPENDENT_INPUT_REQUIRED = True`). Rollback is one-way: this MC requires the
KS descriptor's `auditorKind`, which an older MC rejects.

Operator review (W1 D2, OVE-169): `TrustedJudgmentBridge.review` delegates to `ReviewRelay`, the one KS
`report.review` path ([`review.py`](../../src/mission_control/application/knowledge/review.py)).
`POST /v1/applications/{app}/runs/{run_id}/knowledge-reviews`, `missionctl knowledge review RUN --decision-file F
--outcome approve|hold|reject --bound-effect-digest D --rationale T` and the operator MCP tool `knowledge_review`
call `KnowledgeReviewService.review`, which refuses `unauthorized_review` (403) before anything is sent when the
actor lacks `knowledge.review` or is the producer runtime subject, its reconciler, the judge or the auditor, or
launched the run (`PostgresRunActors`), so review needs a principal distinct from the launcher; the run must
exist in the tenant and a trusted assessment of it must cite the exact decision (`decision_not_in_run`). The same
body twice is one KS request. KS needs a live reviewer grant (`knowledge-verify grant-reviewer`, provisioned by
`sprint_oc_deployment_file.py reviewer-grant`) and checks the exact digests (`review_refused`, 409); the
settlement's next pass re-resolves the successor and promotes. The Human Task service is not used. Proof:
`tests/unit/knowledge/test_knowledge_review.py`, `tests/integration/postgres/test_knowledge_review_postgres.py`.

Report digests (W1 D1): the producer's `report_register` carries content only; `report_registration.py`
completes tenant and binding, binds the effect's originating origin as every assertion's producer, computes
each `recordRef`, `qualifiersDigest` and a `text_quote`'s `selectedDigest`/`selectedSize`, and refuses typed
(`REF_DIGEST_MISMATCH`, `REF_UNRESOLVED`, `REF_CYCLE`, `PRODUCER_HOST_OWNED`, `REGISTRATION_MALFORMED`). The
effect key is over the exact content, so a retry is the same bytes. Proof: `tests/unit/knowledge/test_report_registration.py`
against a KS-built parity fixture.

KS refusals of evaluator documents (W1 D20): the auditor census spans carry research-core's `basis`
(`utf16-code-units-v1`) and the evaluators read an assertion's `proposition` and a fragment's selected text. A
KS refusal's bounded issues ride in `TrustedJudgmentRefused`, the `settlement_unavailable` wait detail and an
`unavailable` assessment whose `ks_<code>` findings inspection returns as `finding_details`. Parity:
`scripts/ks_evaluation_parity.mjs` and `tests/unit/knowledge/test_evaluator_parity.py`. Registration collisions
(D19) are typed `EFFECT_CONFLICT / record_id_conflict`.

Evaluator runs, causes and bounded attempts (W1 D22-D24) live on the revision's standing wait
assessment: one agent run per evaluation, the recorded cause, the billed-attempt bound and its
audited operator reset, observe dispatch markers and the recovery of a lost observation handle.
See [Evaluator attempts and observation recovery](evaluator-attempts.md).

Per-role cap: a role batch recorded only in part cannot be completed by a rerun with new observation ids
(`evaluator_role_observed`); Mission Control treats that as observed and the run seals with the partial batch, so
the likely outcome is a hold or an unmet obligation and only a reviewer decision moves it. The lock is observable
as `ks-evaluator-role-observed:<role>` in the assessment's evidence refs (`TrustedOutcome.locked_roles`).

**Official use of a reference (W1 D28).** A reference promise is fulfilled only with current
official-use evidence of the exact revision it names. Production composes `TrustedReferenceUses`
([fulfillment service](../../src/mission_control/application/outputs/fulfillment.py)) as the output
service's `reference_uses` port: the newest standing assessment citing a KS decision for exactly that
revision id and digest must be `pass` (`official_use_evidence`), and its cited decision is the
evidence. The bridge records `pass` only from an admitted, officially usable decision with no review
pending, an approved review arrives as its superseding `pass` (resume), and a revocation as a later
superseding non-pass (resume or recheck), so a held decision, another revision with the same digest
or readable bytes never count. Before D28 no port was composed, so every reference promise read
`REFERENCE_USE_UNPROVEN` even after an approved review and promotion (run 9cc17684).

## Native-write decisions (B3 and B3-R)

A native write of an accepted report runs inside the one invocation whose agent called `knowledge_apply` with a
report member of its sealed plan (`application/knowledge/native_write.py`): the member must be officially usable;
the application's existing native schema builds the intent (AI Engineer `claim.materialize`; Biotech has no report
intent and refuses `SCHEMA_UNSUPPORTED`); the exact native digest comes from `knowledge.plan_preview`; a
plan-level `report.decide` binds that digest; `record_apply_decision` stores it with the candidate-migration
columns `subject_ref`, `invocation_ref` and `decision_digest` (`adapters/postgres/knowledge/use_decisions.py:48-66`,
migration 0072, unregistered: [database component](database-component.md)); apply goes through the existing path,
or answers `pending_review` and the same invocation's settlement pass applies once KS reports the decision usable.
A changed digest leaves the earlier decision as harmless retained lineage; only recorded decisions can apply.
Integrated with focused restart proof after B3-R (NEXT-SESSION lines 844-905); W1 is not closed by it.

Built / specified / goal: judgment, review, promotion and native-write decisions are implemented and tested;
integrated, live paid (NEXT-SESSION line 97); qualified: no (W1 unreleased).

## Citations

- [Knowledge Services boundary](knowledge-services.md), [output contracts](output-contracts.md),
  [saved-result settlement](saved-result-settlement.md).
- ADR: [0058](../adr/0058-composable-output-obligations-and-one-submission-act.md),
  [0059](../adr/0059-application-content-and-shared-knowledge-authority.md),
  [0060](../adr/0060-authenticated-origin-and-native-receipt-provenance.md).
- Source: `src/mission_control/application/knowledge/judgment.py`,
  `src/mission_control/application/knowledge/review.py`,
  `src/mission_control/application/knowledge/report_registration.py`,
  `src/mission_control/application/knowledge/trusted_settlement.py`,
  `src/mission_control/application/knowledge/evaluator_plans.py`,
  `src/mission_control/adapters/deep_agents/evaluators.py`, `src/mission_control/bootstrap/trusted_judgment.py`,
  tests `tests/unit/knowledge/test_independent_evaluators.py`,
  `src/mission_control/domain/knowledge/judgment.py`, `src/mission_control/contracts/knowledge_assessment.py`.
