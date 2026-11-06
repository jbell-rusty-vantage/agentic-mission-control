---
type: Concept
category: qualification
title: Evaluator attempts and observation recovery
description: "How the trusted bridge runs each independent evaluator once per evaluation, records the concrete cause of a failed run, bounds billed runs per exact revision and role (with an audited operator reset), and recovers a KS-accepted observation whose handle the host lost (W1 D22-D24)."
tags: [mission-control, knowledge-services, assessment, evaluators, implementation]
aliases: [evaluator bound, observation recovery, billed attempts, attempt reset]
questions:
  - Why is an evaluator waiting and how many runs are billed?
  - How do I reset the evaluator attempt bound?
  - How is a lost observation handle recovered?
updated: 2026-11-01
---

# Evaluator attempts and observation recovery

Part of [trusted judgment](trusted-judgment.md); the code is
[`application/knowledge/judgment.py`](../../src/mission_control/application/knowledge/judgment.py),
[`adapters/deep_agents/evaluators.py`](../../src/mission_control/adapters/deep_agents/evaluators.py)
and the gateway's `recover_trusted`.

**Handle operations (D22).** Release 1.9.0 migration 0067 makes the `knowledge_operation_handle`
operation check exactly `RECORDED_HANDLE_OPERATIONS` (`application/knowledge/operations.py`: the
effects, the non-effect handle operations and the trusted path's `knowledge.read` plus
`report.observe`/`seal`/`decide`/`review`/`decision.resolve`); 1.8.0 refused a KS-accepted
observation handle.

**One run, a recorded cause (D23, D24).** An evaluation is one Deep Agents run: the response tool
is bound with `handle_errors=False` (LangChain's default re-asked the model up to the recursion
limit: 11 billed calls, then a bare `GraphRecursionError`), the OpenAI judge binds
`parallel_tool_calls=False` on the Responses API (`api_surface`, see
[model catalog](model-catalog.md)), and the evaluator registers its provider's harness profile so
no implicit general-purpose child is added. A failed run raises `EvaluatorUnavailable` with its
cause (exception class and message, refusal, finish reason, validation errors; redacted, at most
400 characters) and whether it was billed: httpx connect, pool and proxy failures, builtin
`ConnectionError` in the cause chain, other `APIConnectionError`s and `APIStatusError`s are not;
read/write timeouts, a timeout of unknown cause and anything after the model answered are.

**The standing wait and the bound.** The bridge records each cause on the revision's one standing
wait assessment (origin `mc-evaluator-wait:`, finding `evaluator_unavailable` or
`evaluator_attempts_exhausted` "`<role>`: `<cause>`", each new wait superseding the last, KS
refusal evidence and `ks_*` findings carried) and counts billed runs there
(`mc-evaluator-attempts:<role>:<n>`); a KS outage after a billed run and a KS refusal of its
documents count too. At `EvaluatorRetryPolicy.max_attempts` (2, PROOFS section 6) billed runs for
one exact revision and role, later passes run no paid evaluator; the settlement wait records code
`EVALUATOR_UNAVAILABLE`, reason `evaluator_attempts_exhausted` and the causes as issues. The write
is a compare-and-set: the bridge re-reads at write time, the store refuses a second supersession
of one prior or a second first wait (`AssessmentSupersessionConflict`; PostgreSQL serializes per
exact subject with a transaction advisory lock), the loser retries once, then waits typed
(`EvaluatorWaitConflict`); a failed or refused write is `EvaluatorWaitUnrecorded`, never
swallowed. Two passes that both read a count below the bound before either runs can still each
spend one run (the claim fence makes that exceptional).

**Operator reset.** After `evaluator_attempts_exhausted`, an operator holding `knowledge.review`
(never the producer, an evaluator or the launcher) calls
`POST /v1/applications/{app}/runs/{run_id}/evaluator-attempt-resets` with
`{revision_id, role, reason}` (`KnowledgeReviewService.reset_evaluator_attempts`,
`EvaluatorAttemptReset`): a superseding wait with that role's count and cause removed, evidence
`mc-evaluator-reset:<role>:<digest>`, finding `evaluator_attempts_reset` naming the operator and
reason, origin `mc-evaluator-reset:<revision>:<operator>` (immutable rows keep the audit). No
attempt recorded answers 409 `nothing_to_reset`.

**Observation markers and recovery.** Before sending `report.observe` the bridge records the
request id on the standing wait (`mc-evaluator-dispatch:<role>:<request id>`); a KS refusal of a
second batch (`evaluator_role_observed`) or a sealed run records
`mc-evaluator-observed:<role>:ks-held`. A later pass never re-runs a dispatched or held role (its
first batch stands; reported locked). It reads the dispatched operation back without re-sending:
KS names a trusted operation by its request id (`trusted_operation_id`, mirroring KS
`service.ts`; golden vectors from KS's own code in
`tests/fixtures/knowledge_protocol/ks-operation-id-parity.json`, `scripts/ks_operation_id_parity.mjs`),
so the gateway calls `operation.get`, requires the answered id to be that id (else a typed
refusal) and records the handle. KS `NOT_FOUND` means the dispatch never landed (the evaluator may
run within its bound); an unreachable KS waits. A handle-record failure after KS accepted is
recorded as the cause but never counted, so a persistently failing handle insert retries the
recovery on every pass (an unbilled `operation.get`, no evaluator run) without consuming attempts
until the store accepts it. Seal and decide use KS's own observations, never the host handle row.
The session-6 run predates the dispatch marker: its next pass runs the auditor once more, KS
refuses that batch and the role becomes `ks-held`.

**No evaluator credentials (D30).** Where no trusted settlement composes (either
`MC_JUDGE_OPENAI_API_KEY` or `MC_AUDITOR_ANTHROPIC_API_KEY` unset), a launch of any family whose
promise requirements name the application's assessment pin refuses with
`trusted_assessment_unavailable` (`ManifestTrustedAssessmentUnavailable`, a kind of
`dependent_inputs_unavailable`, at `/outputs/<obligation>/requirements/<key>`). The check reflects
the environment of the process that launches: the API for a user launch, the worker for a chain
relay; so the API and the workers must share the evaluator environment. A worker that lacks the
keys while the launcher had them is caught mid-run: `UncomposedTrustedSettlement` keeps such a
report revision's saved result waiting (`settlement_unavailable`, reason `evaluator_unavailable`,
the cause naming both variables) instead of finalizing it unjudged, and the invocation's own
standing review wait holds too; a revision a credentialed worker already judged (a standing pass
or fail citing a KS decision) is never held again. A worker with both credentials settles the wait
on its next pass. Nothing else ends it: the wait is a Temporal timer between settlement passes
(`OperationWorkflow._wait_settlement`, continued as new after its bound), each pass is its own
activity under its own start-to-close timeout, no model call is made (so no turn budget applies),
and the parent starts the operation child with no execution timeout; only a cancel ends it. Proof:
`tests/unit/knowledge/test_w1_d30_uncomposed_evaluators.py` (both families, the real admitted
configuration, no workspace template, judged revisions, release),
`tests/unit/knowledge/test_knowledge_composition.py` (wiring),
`tests/integration/postgres/test_w1_d30_uncomposed_postgres.py`; the long-wait behaviour is
`tests/integration/temporal/test_wi04_saved_settlement_restart.py`.

**Not surfaced as a notice.** These waits are `unavailable` assessments: the coordinator attention
stream (WI-19) emits notices only for held or rejected assessments, so an exhausted bound or a
`ks-held` role reaches the coordinator through inspection (assessment findings) and the settlement
wait detail, not as an actionable inbox notice.

Built / specified / goal: the bounded attempts, recorded causes, operator reset and observation recovery are implemented and tested
on PostgreSQL (`tests/integration/postgres/test_w1_d30_uncomposed_postgres.py`); integrated in the paid fixtures; qualified: no (W1).

## Citations

- Tests: `tests/unit/knowledge/test_w1_d23_evaluator_causes.py` (request body, causes, bound,
  reset, recovery), `tests/unit/knowledge/test_ks_operation_id_parity.py`,
  `tests/unit/knowledge/test_w1_d22_handle_operations.py`, `tests/unit/knowledge/test_knowledge_review.py`,
  `tests/integration/postgres/test_w1_fixg_evaluator_ledger_postgres.py`,
  `tests/integration/postgres/test_sprint_oc_release_190.py`.
