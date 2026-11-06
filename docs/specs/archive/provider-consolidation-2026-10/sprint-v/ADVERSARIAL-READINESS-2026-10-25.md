---
type: Implementation Evidence
title: "Sprint V adversarial readiness review before IQ-07"
description: "Independent source review and fresh bounded tests of the four committed Sprint V repositories; distinguishes service foundations, runtime defects, interview decisions and unproven workflow qualification."
tags: [mission-control, sprint-v, review, readiness, output-contracts, context-transfer]
date: 2026-10-25
status: active
---

# Sprint V readiness before the final interview

## Verdict and scope

**Ready to conduct IQ-07 on an explicitly incomplete runtime baseline. Not ready to certify the
end-to-end coordinator → Deep Agents workflow → verified/admitted reports path.** The interview can
settle the remaining design and sequence the repairs below; it must not treat the prior blanket
“entry gate met” as proof those repairs are finished. No owner decision is manufactured by this review.

The review covers the commits the owner supplied, all clean on `main` at entry with only the primary
checkout registered: MC `fa1f778a`, KS `b45adf5`, AIDB `306efd7`, BKS `c398177`. Commit identity and local
state were checked; remote push status was not independently fetched. No product code, migrations,
deployment locks, work-item completion states or remote issues were changed. New probes use local
test doubles and disposable PostgreSQL; no paid model calls or live research were performed.

This is a fresh review, not a rerun of every historical proof in [PROOFS.md](PROOFS.md). In particular,
the historical paid control slice and Neo4j/HTTP fault proofs retain their original limitations.

## 1. What Sprint V actually joined

| Boundary | Current owner and responsibility | What this does not establish |
| --- | --- | --- |
| Coordinator → MC | MC authoring/admission, capability bindings, Temporal scheduling, lifecycle, grants, budgets, observation and control | A coordinator model is not the scheduler; provider success is not mission acceptance |
| MC → shared KS | Signed `ks.knowledge_operation.v2`, host-bound origin, effect journal/recovery, exact handles, submission/assessment and report delivery seams | Six tool definitions do not mean six usable capabilities; `verify.claims` currently refuses |
| Shared research process | KS `research-core`, `application/src/research`, common `knowledge_verification` SQL: assertions/support sets, report rendering/census, observations, seals, use decisions, review and invalidation | Pure rules and trusted in-process services do not establish an externally reachable judge/review/seal workflow |
| AI Engineer binding | KS PostgreSQL binding and ingestion port; AIDB owns domain SQL, report projections and commit-time guards | MC's `knowledge_apply` still needs a trusted decision producer/resolver; a native binding proof is not proof of that MC path |
| Biotech binding | KS common operational records in app PostgreSQL, admission/outbox adapter; BKS owns SDL, native planning/apply, graph marker, acknowledgment and eligibility-aware read v3 | PostgreSQL and Neo4j are not one transaction; queued dispatch is not completed ingestion; BKS does not host the semantic model |
| Transfer | MC resolves exact selected content, stages/probes bytes, binds runtime inputs; application retains canonical content | Delivery does not establish evidence validity, permission to use it officially, or that a model read/understood it |

Evidence routes: MC `mission-control-general/general-mission-control/expansion/KNOWLEDGE-SERVICES.md` (deleted 2026-11-01; last at `66185d2e`);
KS `packages/host/src/knowledge-operation/{service,config,backends,native-ports}.ts`,
`packages/research-core/src/verification/{aggregate,use-decision}.ts`,
`packages/application/src/research/{coordinator,assessment,review}.ts`;
BKS `packages/kg-ops/src/admission/{dispatch,verification}.ts`; AIDB migrations through
`20261025010200_research_admission_values_required.sql`.

Verification and adjudication remain separate: a producer supplies assertions and evidence;
independent observations and the final census support assessment; a sealed run supports a use decision;
review binds an exact decision/effect and a live reviewer grant. Approval cannot waive a failed integrity
check or missing evidence. Native admission rechecks the exact use and normalized values. Biotech
official reads recheck current eligibility, including revoked reviewer authority. A held report may be
useful evidence for a repair/review task without becoming an admitted official result.

## 2. Findings that affect the first fixtures

### RV-01 — P1: blocked finalization is ignored by the Deep Agents adapter

MC `adapters/deep_agents/adapter.py:280` awaits `knowledge.complete(invocation)` and discards the
returned `FinalizationReport`, then returns the provider result. `KnowledgeToolset.settle` reconciles
for a bounded time and returns `SubmissionService.finalize`; unresolved effects return `blocked`,
with no finalization row. Neither call raises merely because that report is blocked.

**Reproduced:** an adapter-level probe returned `provider-success` when completion returned
`blocked=True`, `finalization_id=None`, and a pending Biotech effect. This establishes that the adapter
does not enforce the barrier; it is not a claim that every mission's downstream completion expression
will accept the result. The existing helper tests prove the blocked report, not propagation through
the adapter to workflow settlement.

**Required repair:** make an unresolved effect a durable workflow wait/block owned by a reconciler;
decide terminal failure/repair behavior explicitly. Resume settlement after receipt recovery without
repeating the external write. Test through the actual adapter and operation reducer, including a
receipt arriving after the bounded poll and a worker restart. Do not map every domain hold to provider
failure: output disposition and operation execution need distinct contracts.

### RV-02 — P1: a multi-report selection assesses only its first report

MC `application/outputs/submission_service.py:465` returns the first report in `_selected_report`.
One assessment state is then attached to the entire submission. `SubmitArgs.items` accepts multiple
items, so the service neither rejects this shape nor assesses its remaining reports.

**Reproduced:** submit `[report-good, report-unchecked]`; the only `report.assess` call names
`report-good`; finalization reports `outcome=fulfilled`, `outcome_basis=assessed` for the collection.
This matters directly to “a few reports and a synthesis step.”

**Required repair:** either reject unsupported multi-report assessment at admission as a temporary
bound, or persist per-member assessments and aggregate under an explicit collection rule. Never let
the first member attest the rest. Add good+held, good+rejected, reordered members, duplicate members,
and revised-member cases before the multi-report fixture. Any temporary restriction must be explicit
in the capability descriptor and authoring surface.

### RV-03 — P1 before branching: report transfer is run-wide, not dependency-selected

MC `application/knowledge/toolset.py:357` reads all `finalized_selections(scope, run_id)`, excluding
only the current operation and duplicate handle strings. The SQL at
`adapters/postgres/knowledge/submissions.py:159` excludes `attempt_failed` but does not select a DAG
predecessor set, accepted frontier, current generation, or required assessment disposition. It keeps
the latest revision per invocation/obligation, not a current accepted revision across invocations.

**Reproduced:** an unrelated completed stage and a supposed predecessor each submitted a report;
the consumer received all six body/ledger/manifest files. The method has no declared-dependency input.
It can therefore disclose irrelevant sibling work inside the run, contaminate an independent verifier,
or block a consumer on an unrelated report that is no longer readable. This is not cross-tenant leakage.
Transfer to an agent without a knowledge tool is also bypassed by `uses_knowledge`, and linked missions
are outside this path. These were partially disclosed in the handoff, but are release-rule limitations,
not only efficiency opportunities.

**Required repair:** compile exact producer/output/member selectors at the workflow boundary and
feed those to the existing resolver. Make held/provisional input consumption an explicit review/repair
policy; never infer that every finalized submission is fit for synthesis. Test a disconnected sibling,
a diamond DAG, retry/generation changes, and a verifier that must not inherit producer reasoning.

### RV-04 — P1 before using admission: the trusted decision path is not composed

MC `bootstrap/composition.py:588` creates `InMemoryUseDecisionStore`. `knowledge_apply` calls
`gateway.apply_decision` (`application/knowledge/gateway.py:277`), which only looks up a handle there.
Search of production `src/` found no call to `decisions.record`; the writers are test setup. Thus the
gap is larger than persistence across restart: the normal composition has no producer/populator for
these handles in the first place. A fresh-store probe returns `NOT_FOUND` before dispatch.

On the KS side, `config.ts:122-125` chooses an injected auditor or an explicitly scripted proof double,
otherwise `report.assess` is unavailable. `service.ts` refuses `verify.claims`; K01 registration rejects
producer-supplied judge/reviewer observations. The application exposes trusted coordinator/seal/review
methods in process, but the reviewed K01 switch does not provide the complete trusted observation →
seal → use-decision → adjudication path. `report.assess` audits and aggregates; it does not itself
execute that whole chain. The direct proof harness performs trusted steps outside the model-facing tools.

**Decision plus implementation required:** choose where semantic judging/census runs (OC-D98 permits
KS-hosted or MC-hosted agents), how independent identities submit their step artifacts, and how a
trusted host resolves a sealed exact-use decision for apply. The durable authority belongs in KS;
MC may store a reference/cache but must not invent an admission decision. Wire review grants and
successors through an authenticated route, preserve current-eligibility rechecks, and prove both app
paths from an ordinary launch without test-only store injection. Advertise unsupported verification
truthfully. Do not restore the retired oracle to make a demo pass.

### RV-05 — P2: M04's byte budget is per report and outside the sealed packet budget

`toolset.py:387` gives every report the whole `delivery_budget_bytes`; `DeliveryPlanner` resets used
bytes per plan and stores `budget_tokens=None`. The runtime uses `inline="never"` regardless of the
consumer. Reports are added later through `CURRENT_KNOWLEDGE_INPUTS` and
`adapter.py::_context_seed_files`, separately from the ordinary `ContextPackService` selection/budget.

**Reproduced:** a configured 1,145-byte delivery budget admitted two packages totalling 2,275 bytes.
Each package fit individually. This is evidence that the setting is not an aggregate receiver ceiling,
not evidence that those bytes were all inserted into the model prompt.

**Required design/repair:** one effective receiver plan must account for all mandatory instructions,
state, tool/skill overhead, pointers, optional inline text, file bytes, and reserved generation budget.
Separate prompt tokens from filesystem bytes. Carry M04 inputs into that plan and its receipts; an
environment manifest recording seeded files is useful evidence but does not replace the sealed plan.
Readability must be proven through the selected backend's actual access permissions. A storage readback
alone does not prove the model's file tool can open the mounted path.

### RV-06 — P2: preserve the native-commit/protocol-receipt crash boundary in readiness

KS `packages/host/src/knowledge-operation/service.ts:606-618` calls native apply and only then
`buildReceipt(..., "protocol")`. This known window remains. AI Engineer has native transactional
admission/receipt protection; Biotech has an outbox and graph marker. Those are valuable, but do not
alone prove protocol lookup/recovery when the process dies before storing its K01 receipt.

Require a fault injection at that precise boundary: restart, recover by the same effect identity,
return the same native effect and correct protocol receipt, with no duplicate graph/domain write.
Either transactionally bind the protocol receipt where possible or implement explicit native-receipt
reconstruction. Coupled with RV-01, “pending_dispatch blocks finalization” is not a complete recovery
story. Historical lost-ack/rollback cases over the BKS HTTP boundary remain unrun.

### RV-07 — P2 documentation: the interview's briefing mixes checkpoints

The briefing still called work uncommitted, named absent projection classes that now exist, described
`toolset.py` as absent, reserved an AIDB timestamp before the current head, and cited an obsolete MC
fingerprint. It also presented use-class registration as future work although it exists. The active
interview, briefing and next-session pointer are corrected in this review; historical proof entries
and immutable release bytes remain untouched. The bundle's part-1 capability list is explicitly
historical; read `part2.capabilityMatrixFinal` and verify its pins rather than promoting every old cell.

### RV-08 — P1 before official use: exact operational report read is not native eligibility-aware read

The briefing's S3 claim that M04's Biotech `knowledge.read` calls BKS v3 was not supported by source.
KS `packages/host/src/knowledge-operation/service.ts:497-578` loads the report from the research
binding and reads body/ledger from its custody, returning an exact package. Biotech's
`packages/bindings/biotech-graph/src/research-binding.ts` reuses `PostgresResearchBinding` under the
Biotech binding id; it explicitly keeps these operational records and bytes in the app-local common
component. The host read path does not call the BKS official reader or `check_use_eligibility`.

This exact draft/read path is useful and not inherently unauthorized. But successful delivery through
it cannot attest that the report was projected to Neo4j, admitted for an official use, or remains
eligible after revocation. The manifest carries exact bytes and assertions, with an empty evidence
list; it is not a complete eligibility or selected-evidence expansion receipt. AI Engineer's K01 read
likewise must not be conflated with its separate native domain projection/read contract.

**Required contract:** distinguish operational/draft reads from native official-use reads in the
selector/profile and readiness evidence. When a consumer requires native ingestion/current eligibility,
resolve the admission/lineage receipt and current use decision through the appropriate binding;
block if unavailable/revoked. When it is a review task, permit exact held/draft content explicitly and
label that status. Prove a revoked native projection remains readable for authorized review while an
official-use consumer is blocked. Do not globally prohibit draft transfer to repair this distinction.

## 3. What is intentionally still design work

These are not all Sprint V regressions: compiled output obligations/fulfillment records, accumulation
across cycles, accepted revision frontiers, reusable five-guarantee assessments, transfer profiles,
linked-mission adoption, full review integration, and qualification across all four workflow systems
belong to the next contract/runtime work. Today `live_invocation()` defaults to no obligations;
`finalize()` infers them from what was submitted. That cannot detect an entirely omitted promised
deliverable. A `submission_coverage` result must never be promoted into the future fulfillment claim.

`ContentResolutionService`, `ReportRepresentation`, `DeliveryPlanner`, `ContextPackService`, prompt
segments and backend seeding already exist. Build a small, coherent prompt-materialization interface
over them rather than treating this as an empty subsystem or starting the deferred global refactor.

Existing coordinator observation also exists: `CoordinatorInboxService.wait`, launcher subscription,
HTTP inbox polling, `missionctl wait`, authenticated MCP inbox tools and a relay/webhook path. Read
`application/subscriptions/coordinator_service.py`, `application/subscriptions/launcher.py`,
`interfaces/{http/coordinator_inbox.py,cli/wait.py,mcp/subscriptions.py}` and
`bootstrap/subscriptions.py`. This review does not prove a callback wakes this Codex chat. New output/
transfer event kinds and their replay/ack behavior still need wiring and end-to-end proof.

## 4. Fresh validation and its limits

Commands ran from their owning repositories using installed runtimes. The KS `pnpm` wrapper attempted
an automatic dependency reinstall and aborted with `ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`.
No purge/reinstall was accepted. Direct `node node_modules/vitest/vitest.mjs` ran the installed 4.1.11
test runner. Package tests can consume existing built workspace exports; these results do not replace
a clean rebuild or fresh-install proof of every transitive package.

| Check | Fresh result |
| --- | --- |
| MC `.venv/Scripts/python.exe -m pytest tests/unit/knowledge tests/unit/domain/knowledge tests/conformance/test_knowledge_protocol_golden.py tests/conformance/test_knowledge_protocol_negative.py -q --tb=short` | 200 passed |
| MC PostgreSQL `test_knowledge_gateway_postgres.py` + `test_sprint_v_release_150.py` | 13 passed, fresh fixture-owned databases on the documented disposable `sprint-v-pg17` server |
| MC `tests/acceptance/mission_control/test_knowledge_gateway_runtime.py` | 1 passed in 110 s: real local Temporal/PostgreSQL, StageGraph and GoalDirected with deterministic technical agent and fake KS over HTTP. No live model or real KS executor in this fresh runtime run |
| Adversarial probes (test doubles; `.scratch/readiness-2026-10-25/probe.py`) | Five behaviors reproduced: unchecked second report, ignored blocked finalization, missing decision handle, run-wide six-file delivery, aggregate byte budget overrun |
| KS research-core / application research / host / K01 | 78 / 36 / 52 / 28 passed |
| KS AI Engineer binding / KS component with `KNOWLEDGE_DB_CONTRACT_ADMIN_DSN` set to the documented disposable server | 24 / 13 passed |
| KS Biotech binding with disposable PostgreSQL | 24 passed; native graph dispatch is represented by the suite's stub, not a fresh Neo4j proof |
| KS executor knowledge-operation selection | 22 passed, 4 skipped; the PostgreSQL test separately rerun with the disposable DSN: 1 passed. AIDB full-domain and Biotech real-executor cases still require their own setup |
| BKS contracts + kg-ops + executor (`--maxWorkers=2`) | 219 passed, 1 failed, 81 skipped. Failure: existing release-override test needs absent `biotech-meta/docs/schema/releases/biotech-schema-v2.0.1`; do not recreate that retired checkout |
| BKS initial full `pnpm test` | Completed with 385 passed, 1 failed, 89 skipped, plus two suite-collection failures; all three failing locations depend on the absent historical `biotech-meta` release directories. This is not a green full-suite result |
| AIDB `npm test` | 15 passed (schema-workspace generator tests, not native migration/admission proofs) |
| AIDB typecheck / workspace validation / workspace database check | Typecheck passed; validation passed with zero rerender differences; database-backed `workspace:check` blocked (`DB_UNREACHABLE`: no target URL supplied). No unrelated/shared database was selected to clear the check |
| Release hash audit | 115 comparisons passed: both 52-file MC bundle locks, both lock-file hashes, MC manifest, seven KS migration hashes, mirrored K01 golden vectors. AIDB source head `20261025010200`; BKS PIN names v2.2.0. No deployed-version assertion |

MC `docs/tools/check_docs.py` passed all seven offline checks after the interview/briefing changes;
`git diff --check` was clean. Fresh/repeat/interrupted
full AIDB and BKS installation, real Neo4j transactions, paid models, the complete Deep Agents backend,
and every workflow composition were **not requalified** by the unit/native-component checks above.
The prior evidence in PROOFS is useful but is not silently relabelled as a fresh run.

## 5. Recommended fixture ladder and repair order

The following is the reviewer's recommendation for IQ-07, not a new accepted owner answer:

1. **Repair prerequisite barriers:** RV-01/RV-02, explicit declared obligations and the trusted
   verification/decision route. Preserve failure receipts and restart ownership. Use deterministic
   synthetic evidence first; report generation may be scripted while plumbing is being tested.
2. **One goal, one report:** one evidence report, one declared deliverable, no domain write required
   by default; independent assess/repair/submit. Add an explicit admitted-write variant once RV-04
   is composed. Repeat against AI Engineer then Biotech, identifying the exact store used at each step
   and distinguishing operational report reads from native official-use reads (RV-08).
3. **Two-stage graph:** A produces a report; B consumes only A's selected revision and produces a
   synthesis/review. Prove B cannot start without required bytes/state; corrupt bytes, deny access,
   exhaust budget, omit output, and hold/reject the report. Explicitly permit held inputs only for a
   task that is allowed to review/repair them.
4. **Few reports plus synthesis:** two producers, explicit collection and accepted frontier, unrelated
   sibling output excluded, per-member verdicts and one aggregate receiver budget. This is where
   RV-02/RV-03/RV-05 must be closed, not hidden by a one-report happy path.
5. **Recovery and evolution:** stop/retry/restart, late native acknowledgment, changed source revision,
   revocation and exact replay; one iteration/cycle with accumulated obligations and no duplicate writes.
6. **Remaining required systems:** Parallel Swarm, Evaluator Optimizer, linked missions and relevant
   composition/control boundaries; then full Deep Agents qualification for both applications. The
   real-work gate remains closed until those proofs exist. Codebase-commit fixtures are outside this
   first ladder; other providers do not need to block it.

Every rung records the authored contract, compiled obligations, effective prompt and file index,
selected identities/digests, execution/assessment/admission/delivery outcomes separately, errors and
repair action, and resource use. Run a schema-fit check for MC, common KS, AIDB and BKS at each wave;
justify no-change findings instead of working around missing records. Global code/skill/coordinator
search simplification remains deferred; a usable prompt-materialization module is a first-version
requirement.
