---
type: Architecture Projection
title: "Output-contract sprint: implementation and team workspace"
description: "Concrete module seams, direct cutovers, schema ownership, ready frontiers and agent-team execution for the final output/context sprint."
tags: [mission-control, implementation, team, architecture, output-contracts]
status: accepted
date: 2026-10-26
---

# Implementation and team workspace

Build the [canonical contract](../../../knowledge/output-contracts.md)
at existing application seams. The fastest path is a shared output/current-set/transfer foundation,
then independent family and provider work, with progressive real proof. This is a projection, not
as-built documentation. [Work items](WORK-ITEMS.json) and [tracker map](README.md) name exact ownership
and blockers; [proofs](PROOFS.md) prevent an earlier wave from claiming later behavior.

Before tracing an application integration, read [application ports](APPLICATION-PORTS.md), then its
AI Engineer or Biotech schema card. These dated source maps distinguish operational report transfer
from native knowledge reads and effects; they do not change this implementation or proof frontier.

## 1. Verified starting point

Read-only inspection on 2026-10-26; no fresh runtime/deployment qualification:

| Repository | HEAD and source evidence | Starting limit |
| --- | --- | --- |
| MC | `1863017c779a1b138951c19a0abfcadc4f839a84`, `main`, sole checkout; interview/docs dirty on entry | Common release 1.6.0; Sprint V foundations exist, but RV-01–08 remain first-use obligations. |
| KS | `b45adf5ac517510c14842d8fd2909fca95ce1e24`, clean `main`, sole checkout | Shared component 2.4.0; KOP v2, report/assessment/native ports exist; ordinary trusted semantic composition incomplete. |
| AIDB | `306efd71291ffacd57c6ce698112a213c45621bb`, clean `main`, sole checkout | Package 0.5.0; migration head `20261025010200`; native transaction/projection guards exist. |
| BKS | `c398177f119d70cdba2606625785e70f780a2dc6`, clean `main`, sole checkout | Authored/pinned v2.2.0; `schema/source/` is authority. Historical missing-biotech-meta tests must be replaced. |

Unit-suite baseline on 2026-10-27 after the OC-D202 deletion (`make check`, Git Bash): ruff, format, ty and the
architecture tests pass; 5659 unit tests pass and **36 fail for reasons that predate this sprint**: 22
`tests/unit/runtime/test_run2_worker_deploy_script.py` cases need PowerShell, 7 `tests/unit/schema/*` cases
see the BKS pinned SDL differ from the published digest, 4 `tests/unit/harness/test_cursor_local.py` closing-facts
cases, 2 `tests/unit/control_plane/test_digest_set_order_guard.py` audits and 1 `tests/unit/prerequisites/test_setup.py`
text case. Name them as pre-existing in every handoff; fix them only when an issue owns them. Integration
baseline, bisected 2026-10-27 against pre-sprint `main` `3e5043ed` (all fail there too):
`tests/integration/test_run2_cursor_costs_postgres.py` (9; fixture pinned to component 1.4.1 lacks `unit_key`),
`tests/integration/temporal/test_pre_stage3_temporal_contracts.py` (1; stale `run_plan_v3` digest pin),
`test_owner_bootstrap_runtime.py` (1; `lane_turn_rejected`), `tests/integration/postgres/test_lane_bindings.py` (1;
seeded `claude_agent_sdk` describe lacks `subagents.fields`), `tests/integration/postgres/test_bundle_custody_composition.py`
(8; `ExactDefinition` equality), `tests/acceptance/mission_control/test_postgres_runtime_parity.py` (3),
`test_remote_mission_admission.py` (1 assertion), and `test_manifest_v2_provider_launch.py` (2; owner host-auth). Refresh
branch/status/worktrees before claiming paths. No third domain service or database is invented.
KS operational research records reside in each application's PostgreSQL; BKS graph contains admitted
native projections. Agent Server, standalone LangGraph saver and Temporal persistence remain distinct.
Historical proof in `../sprint-v/PROOFS.md` includes doubles: deterministic technical cognition/fake KS
for the fresh MC test and stubbed graph dispatch in Biotech binding tests. Preserve those limits.

## 2. Module map and interfaces

All MC source paths below are relative to `src/mission_control`. New files are proposed. Each public
entry point returns the closed result/refusal types in the canonical annex. Domain rules remain pure;
application owns transactions/ports; adapters perform I/O; bootstrap composes. Provider discrimination
belongs in the lane router/adapter, not scattered checks in the kernel.

| Deep module / layer | Interface and hidden mechanism | Refusal boundary |
| --- | --- | --- |
| `domain/authoring`, `application/authoring` | Compile named obligations, input bindings, family tree, profiles and governed successors into EffectiveRunConfiguration. | Missing binding/coverage/mode, weakened authority, unsupported required capability, invalid budgets. |
| `application/outputs`, `domain/outputs` (new rule modules as needed) | Submit/promote/assess/fulfill exact revisions/frontiers; hide canonicalization, concurrency and evaluator scheduling. | Conflicting submission key/head, undeclared promise, bad guarantee or stale assessment. |
| `application/context` | One materializer: selection → sealed plan → prompt/index/files/handles → attempt readiness. | Required content/access/use/form/resource failure; no silent fallback. |
| `application/knowledge` + KS host/research | Authenticated operation bridge, separate judges, exact decision resolver/review successor, purpose-aware read. | Self-asserted origin/role, unsealed report, unavailable/current-ineligible use. |
| `application/execution`, Temporal operation workflow | Persist completed result, schedule settlement/reconciliation and honor stop fences. | No cognition redispatch to repair a completed result's wait. |
| `domain/programs`, `application/programs`, Temporal families | Recursive ProgramNode dispatch and family reducers share contracts but keep control semantics. | Unsupported recursive body refuses; no flattening. |
| Deterministic catalog/dispatch + inventory | Versioned transforms, partitions, closure witnesses, bounded activation windows. | Unqualified tree reorder, unknown closure, lost coverage, invalid successor. |
| `adapters/deep_agents`, `adapters/agent_server` | Exact dynamic child binding materialization and check-time result admission. | Child config/digest/audience mismatch; pending result cannot masquerade as admitted. |
| Hooks/context/recovery | Host-mediated reads, staged installation, consumed preservation and existing continuation phase machine. | Live workspace mutation, forged origin, unavailable historical bytes. |
| Subscriptions/inspection | Exact projections and distinct notice/transport/wake/visible/ack/read evidence. | Transport 2xx cannot advance model acknowledgment. |

```python
# Target application signatures; implementations use existing ports and generated contract models.
async def submit_output(access: InvocationAccess, request: SubmitOutput) -> SubmissionAck: ...
async def evaluate_frontier(access: HostAccess, frontier: OutputSetRef) -> FulfillmentResult: ...
async def promote_output(access: HostAccess, request: PromoteOutput) -> PromotionResult: ...
async def materialize_invocation(request: MaterializeRequest) -> MaterializeResult: ...
async def settle_saved_result(invocation: InvocationIdentity) -> InvocationFinalization: ...
async def activate_contract_successor(access: AuthorAccess, proposal: ContractRevisionProposal) -> RevisionResult: ...
async def execute_program_node(binding: AdmittedProgramNode, parent: ActivationRef) -> NodeResult: ...
async def admit_child_result(access: ParentAccess, task: ChildTaskRef) -> ChildAdmissionResult: ...
async def install_context_candidates(request: CandidateInstallation) -> InstallationReceipt: ...
async def acknowledge_coordinator_delivery(access: CoordinatorAccess, receipt: VisibleDeliveryRef) -> AckReceipt: ...
```

```typescript
// KS service/port targets; publish schemas/golden vectors for the Python consumer.
observe(access: EvaluatorAccess, input: ExactObservation): Promise<ObservationRef>;
seal(access: SealAccess, input: ExactRunManifest): Promise<SealRef>;
decideUse(access: UseAccess, input: ExactUseRequest): Promise<UseDecisionRef>;
review(access: ReviewerAccess, input: ExactReview): Promise<SuccessorDecisionRef>;
readSelected(access: ConsumerAccess, input: SelectedReportRead): Promise<ReportPackage>;
reconcileNative(access: RecoveryAccess, input: OriginalOperationRef): Promise<KnowledgeReceipt>;
```

MC interfaces → application handlers → pure domain contracts/rules + ports → Postgres/KS/provider
adapters. Temporal schedules application operations and records deterministic outcomes; it does not
own evidence judgment. KS host → reusable research application/core → store/native ports → AIDB
transaction or BKS executor. Shared KS never imports BKS Cypher/Neo4j implementation.

## 3. Changed paths and direct cutovers

| Existing source anchor | Delivering change |
| --- | --- |
| `domain/authoring/manifest.py`, `stagegraph_builder.py:67–100`, `manifest_lowering.py:307–332` | Replace required-boolean-only promise projection, first-output/required-all lowering, last-stage goal assignment and nested-loop flattening. Preserve explicit named data/ordering contracts and recursive body. |
| `application/programs/stage_inputs.py` | Remove compatibility side-path selecting only `depends_on` sibling inputs. One compiled binding covers artifact/value/linked/current-set sources; data readiness does not need duplicate ordering syntax. |
| `application/outputs/submission_service.py:241–300` | Extend existing submission service and store. Remove declared-obligation fallback to submitted rows and row-count completion. Add immutable assessments/current sets/fulfillment and saved settlement. |
| `application/knowledge/toolset.py:376`, `application/context/delivery.py:129–175`, `adapters/postgres/context/selection_repository.py` | Retire run-wide selection and overlapping selection/M04 plan authorities; use one selected plan. Redelivery writes fresh attempt receipts; remove fixed one-repair behavior where admitted policy differs. |
| `adapters/deep_agents/adapter.py:280,823`, `adapters/temporal/workflows/operation.py` | Save/consume finalization outcome; preserve completed cognition through waits. Render all prompt/files from the canonical plan, including invocations without KS tools. |
| `adapters/deep_agents/async_subagents.py:262,815–837`, `adapters/agent_server/async_subagents/graph.py:84–93` | Replace fixed technical child with sealed dynamic assistant-per-binding; implement check-time admission and usable child result during parent cognition. |
| `adapters/deep_agents/compaction.py:224–235,558,641`, `hooks.py:1065`, `adapters/temporal/deployment_composition.py:1493` | Consume preservation proposals and register Deep Agents continuation/hydration through existing continuation service (OVE-75). |
| `application/subscriptions/coordinator_service.py:765–773`, `adapters/postgres/subscriptions/coordinator_inbox.py` | Separate webhook transport delivery from explicit acknowledgment; add selected content and real-host delivery stages (OVE-78 baseline). |
| KS `packages/host/src/knowledge-operation/service.ts:196,497–614,745,832` | Add trusted semantic/review transport, selected assertions/evidence/purpose-aware read and native receipt reconstruction; reuse implemented `report.derive`, correct its stale header. |
| KS `packages/research-core/src/verification/aggregate.ts:178`, `authority/rules.ts:155` | Replace blanket judgment official-use exclusion with typed policy/assessment and required review; preserve non-entailment. |
| AIDB `supabase/migrations`, generated types; BKS `schema/source` and native admission/read | Required exact projection/policy/effect schema amendments, generated clients/workspace and native readback. No edits to generated pins as authority. |

Proposed new files stay narrowly owned: `contracts/output_contracts.py`, pure `domain/outputs/` rules,
`application/outputs/fulfillment.py`, `application/context/materialization.py`, family reducers under
`domain/programs`, and their adapters/tests. Prefer extending a suitable existing module over creating
these exact names. Record deviations with invariant/proof preserved; broad reorganization is not a gate.

## 4. Transaction and schema projection

Each delivering slice owns its migration/type/release work. WI-24 verifies integration; it is not a
schema-only backlog that permits runtime completion with missing invariants. Select next migration and
component versions from live heads at claim time; do not reserve a stale version in this plan.

| Authority / projected objects | Required invariant and delivery |
| --- | --- |
| MC component: obligation revisions, output revisions/accepted heads, output sets/members, assessments, fulfillment | Scope-preserving keys/FKs, immutable canonical content, unique scoped submission keys, CAS accepted heads, stable set digest excluding later assessments, exact declared obligation frontier. WI-01/07. |
| MC: saved invocation result/finalization, review/effect wait bindings | Saved result precedes settlement; one durable recovery owner; stop/generation fence and pending effect references. WI-04/03/05. |
| MC: transfer plan + attempt receipts | One immutable selection/digest, receipt identity includes receiver attempt and realized backend; aggregate resource record/current access; no second canonical plan table. WI-02. |
| MC: inventory/partition/group closure, reaction causation, context install, delivery stages | Unique activation/reaction/install identity; exact plan membership/lineage, scoped leases/CAS; independent transport/visible/ack state. WI-10/11/17/19/22. |
| KS `knowledge_verification.operation`, report/observation/seal/decision/review | Reuse immutable request/origin/digest/effect journal; recover original native receipt; version judgment/policy fields and selected evidence manifests. No duplicate verification engine. WI-03/05. |
| AIDB native schemas/projections | Transactional exact-use/normalized-value guard, native result/readback, judgment projection where needed; migrations and generated types together. WI-03/05 and F3. |
| BKS source SDL/native executor | Versioned Report/Assertion/Activity/use lineage; graph effect+marker atomicity and separate PostgreSQL acknowledgment; current official-read eligibility. WI-03/05 and F2. |

Allocate descriptive migration suffixes such as `output_contracts_and_fulfillment`,
`saved_execution_settlement`, `sealed_transfer_attempts`, `work_inventory_and_reactions` at their owners.
No-change schema decisions cite existing enforced fields and real proof, not just JSON extensibility.
Build/install order: shared protocol/core → changed KS component in each app → AIDB/BKS native
projection releases → MC common release and runtime/service pins → integrated service/worker proof.
Use fresh/repeat/interrupted installs and identity/grant/checksum checks. Old experimental histories need
not replay across cutover; histories created by this version must recover correctly.

### 4.1 Disposable remote targets: the least-friction path (OC-D184)

The two Supabase Pro projects in `deployments/ai-engineer/target.toml` (`supabase-blue-ocean`) and
`deployments/biotech/target.toml` (`biotech-research-ingestion`) are the W0 install targets and the
W1–W5 proof targets. They are disposable until quality ingestion and reports exist; no retention is
enforced before then. The Biotech Aura graph is disposable on the same terms (OC-D196).
Keep the projects, their refs, pooler routes, credentials and `installation_id` values: wipe **schemas**,
never recreate projects, because recreation changes identity, routes and every credential.

1. **Local first, per issue.** Deterministic and crash-injection tests run on local disposable containers
   (a `sprint-v-pg17`-style PostgreSQL 17 and the BKS `neo4j-test` container). Nothing paid runs there.
2. **Identify before wiping.** `mission-db inspect --deployment-dir deployments/<app>`; compare project
   ref and installation id with `target.toml` and the stored identity evidence. A name is not identity.
3. **Wipe = drop app-owned schemas** through the admin DSN named by `database_url_env`, behind an explicit
   `--confirm-target <project_ref>:<installation_id>`: `mission_control`, `mission_control_runtime`,
   `knowledge_verification`, `knowledge_service`, the AIDB domain schemas (AI Engineer) and the Biotech
   component schemas; on Aura, the graph content and the `KsReleaseMarker`. WI-24 adds this as a `wipe`
   step of the two root installers (or a sibling subcommand) that writes a wipe receipt (target, schemas,
   timestamp, actor) to the ignored evidence directory. No snapshot is required before a wipe in this sprint.
4. **Install = the two root installers** pointed at the remotes: AIDB `scripts/install-ai-engineer.mjs` and
   BKS `scripts/install-biotech.mjs`, in the Sprint V order (preflight → KS component → domain migrations or
   graph release → custody/grants → MC common release `plan/apply/verify` → receipt). Their
   `DISPOSABLE_PROJECT_REQUIRED` / `DISPOSABLE_NEO4J_REQUIRED` refusals need an explicit remote-reinstall
   flag that requires the confirm-target string; WI-24 delivers it. Fresh = wipe + install; repeat = install
   again and observe `changed: false`; interrupted = kill mid-step, rerun.
5. **New versions ride the same path.** Each delivering issue releases its KS component, AIDB migration,
   BKS SDL or MC common version; W0 and every later gate reinstall from the current pins. Old experimental
   histories are not migrated forward (SV-D11).
6. **Savers.** The standalone LangGraph saver schema `mission_control_runtime` lives in each app's remote
   PostgreSQL for W1–W5 so persistence behaves like production; Docker PostgreSQL is acceptable for a local
   run; in-memory only in unit tests (OC-D188). Temporal and Agent Server keep their separate stores.
7. **Credentials** are the env names already present in `.env` and the Sprint V release bundle; never
   print values; a missing value follows ESCALATION H2.

## 5. Vertical slices and parallel frontiers

The stable WI keys preserve draft provenance, not old approval or publication order. WI-20 remains
unselected and receives no implementation issue. Actual native edges are in WORK-ITEMS.json/Linear.

1. **Ready now:** OC-R0 (OVE-195, the interface freeze of the [selection-and-routing design](../../archive/provider-consolidation-2026-10/specs/SELECTION-AND-ROUTING-DESIGN.md))
   and WI-01 common authoring/submission/fulfillment, in parallel. R1 and R5 follow R0; R2/R3/R4/R6 follow R1;
   R7 reviews. R2 precedes WI-02/04, R4 precedes WI-03/24, R5 precedes WI-03/05, R6 precedes W1, R3 precedes W5.
   Independently audit/pin environments and prepare W0 evidence, without prematurely running dependent fixtures. The older cards OVE-69, OVE-73,
   OVE-75, OVE-77 and OVE-78 are handled seam-only (OC-D195): a W0 baseline audit in WI-24 compares each
   card to source and tests with no paid runs, the integrator sets each card's honest state (closed with
   evidence, or remainder scoped in a comment and moved to Backlog), and the sprint builds only the seam a
   criterion needs: human gates for C08/C09 (OVE-73), interventions for C06/C07 (OVE-69), continuation for
   WI-18 (OVE-75), subscriptions for WI-19 (OVE-78). OVE-77 Socket.IO handlers are needed by no criterion
   and stay open. The native blockers OVE-75→OVE-181 and OVE-78→OVE-182 are replaced by the audit outcome.
2. **After the common contract:** WI-02 exact materializer, WI-04 saved-result settlement and WI-22
   durable reactions can develop on separate paths; WI-03 trusted judgment/review follows WI-02.
   WI-23 dynamic async binding/result admission follows WI-02/04. WI-05 native recovery follows WI-03/04.
3. **W0 then W1:** WI-24 verifies the integrated four-owner foundations; WI-06 runs ordinary real
   GoalDirected report proofs. Missing credentials/selected provider models are recorded external
   execution prerequisites, not another architecture interview.
4. **Parallel after W1:** WI-07 collections/current sets; WI-08 graph routing/W2 transfer checkpoint;
   WI-17 hook preparation; WI-19 focused observation. Schemas/shared files remain integrator-owned.
   WI-09→10→11 supplies large-work transforms/inventory/closure and W3. Inspection contributions land
   with each feature; WI-19 integrates the receiving host rather than becoming a UI bottleneck.
5. **Advanced integration:** WI-12 scoped reassessment, WI-16 same-app links, WI-18
   continuation/preservation/fork delta, and WI-13 recursive execution. WI-14 Swarm and WI-15 EO
   proceed independently after their shared recursive seam. WI-32 independently releases integrated
   W4 evidence; WI-21 independently releases W5.
6. **Post-sprint:** WI-25 stress capabilities and WI-26 mission-work evaluation → WI-27 F1, WI-28 F2,
   WI-29 F3 ingestion → WI-30 F3 retrieval/ranking; WI-31 closes repair/rerun loops and produces
   the evidence handoff for later full product architecture. WI-26 and each active fixture own immediate
   fixes/reruns; they never wait for blocked downstream WI-31 to start repairs.

W0–W5 is proof order, not a ban on independent implementation. A generic feature can be implemented
with protected paths truthfully refused, but cannot claim its real protected success until first-use
prerequisites pass. Do not add OVE-150 as a blocker: its downstream SV-18 depends on WI-21. Reuse
OVE-75 and OVE-78 baseline engines with their existing native blockers. Never close a historical card
solely because source appears present; attach reviewed applicable evidence through normal tracker work.

## 6. Team operating contract

One integrator owns contract/digest/state vocabulary, migration numbering, native dependency graph,
shared-file integration, claims and checkpoint release. Use a sprint integration branch per repository;
inseparable direct cutovers may be temporarily incomplete there until their integrated milestone passes.
Do not build compatibility scaffolding merely to make every intermediate commit separately shippable.
Preserve dirty source interviews when creating branches; new worktrees do not contain uncommitted inputs.

Each claim records: issue, actor, repository/absolute checkout, live base SHA, writable files, shared-file
coordination, exact contracts/ADRs, blockers/first-use gates, expected migrations, verification commands
and required evidence. One owner writes shared contracts/bootstrap/migrations at a time; other agents
return patches or coordinate handoff. Independent scopes proceed in parallel, with one heavy local
database/build job at a time on this laptop. Harness and models (OC-D186): in Codex the lead is `gpt-6-astra` with `gpt-6.1-sol` subagents; in
Claude Code the lead is Opus 5.5 or Fable 5.1 with Opus 5.5 and Sonnet 5.5 subagents. Implementer and
functional reviewer are different agents; a different model for the reviewer is preferred where the
harness offers it. The implementer harness is also the sprint's coordinator host (OC-D187). Runtime
model pins and the USD 40 sprint ceiling are in [PROOFS §6](PROOFS.md#6-operating-limits); blocked
questions follow [ESCALATION](ESCALATION.md).

Assignments authorize ordinary necessary code/schema/import/file changes within the declared scope and
disposable-data mandate. Identify the intended local test target before reset. Escalate missing authority,
credentials, conflicting goals or unavailable external prerequisites; do not ask routine refactor/migration
permission again. Commit when an issue's or milestone's work is complete and verified, on the repository's sprint
integration branch (owner rule OC-D183, 2026-10-27; it replaces "commit when told"). Push the
integration branch at every gate release and at session end so the checkpoint exists remotely; merge
to `main` at gate release. Approval to prepare this pack is not a claim a commit or push occurred.
No automatic deployment is implied.

Before each major commit/integration milestone: review clean code and spec behavior, update affected
semantic docs, run owner generators/checks, fix findings and rerun affected checks. Turn-end automation
is optional and does not replace this gate. Handoff names built behavior, source/contract changes, exact
pins, schema-fit rows, pass/fail/blocked/unrun proof, retained evidence and next ready work.

| Owner | Required affected checks and documentation |
| --- | --- |
| MC | `make ci`, `make docs-check`, `make skills-check`; affected real PostgreSQL/Temporal acceptance; `make manifest-schemas-check`, `make test-db-contract`, `make seeds-validate` when touched. Update authored OKF concepts/log, ADR/glossary/operator/removal docs, then `python docs/tools/agents_docs_index.py` and `python docs/tools/check_docs.py`. |
| KS | `corepack pnpm verify`; affected maintenance/context/protocol/binding tests and real integration; authored knowledge/module registrations then `node .agent-docs/cli.mjs build --repo .` and `check --repo .`. Never raise lint/boundary baselines to hide failure. |
| AIDB | `npm run typecheck`, `npm test`, generated type drift, `npm run workspace:check`, `npm run workspace:validate`; installer fresh/repeat/interruption/native proof; `.agent-docs` build/check. No invented generic OKF requirement. |
| BKS | `pnpm build`, `pnpm workspace:verify`, `pnpm test`, `pnpm client:pack-check`; source→generate/check/verify→pin→workspace/API/client; real Neo4j/HTTP proof. Authored AGENTS/navigation, no invented generic generator. |

## 7. Seams, receipts and design choices

Highest proof seam is ordinary coordinator launch → real MC/Temporal → selected Deep Agents/backend →
KS → native binding → inspection/Transcript. Lower deterministic tests diagnose exact identities,
state transitions and injected crash windows; they never replace functional checkpoint review.

Reuse `tests/unit/knowledge/test_gateway.py`, `tests/integration/postgres/test_knowledge_gateway_postgres.py`,
`tests/conformance/test_knowledge_protocol_golden.py`, `tests/acceptance/mission_control/test_wake_channels.py`
and Sprint V source tests as baseline seams. Add focused contract/fulfillment/transfer/family acceptance
tests with observable refused/waiting/fulfilled results, not implementation mirrors. Native receipt proof
must restart fresh processes across real commits. Provider tests must inspect actual received files/tools.

Engineering choices: one deep materializer beats adapter-side dual selection because prompt/files must
agree; recursive family dispatch beats compiler flattening because control/governor identity survives;
typed rank artifacts suffice for F3 unless native ranking persistence is explicitly added. Preserve these
reasons in conformance changes. No research prototype blocks accepted implementation. Upstream provider,
skills and host API versions are rechecked at first use, with bounded probes where docs cannot establish
behavior. Remaining product options stay in DECISIONS.md without mandatory issues.

## 8. Conformance and claims

No runtime implementation claims exist from this synthesis session. Start the live claim/evidence log
under the sprint's ignored session evidence directory and link compact reviewed summaries here/Linear.
Never commit credentials, private runtime receipts or sensitive fixture data. A new conformance row is:
`issue | projected seam | built seam/deviation | reason | schema pins | tests/evidence | reviewer | disposition`.
