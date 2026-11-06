---
type: Session Instruction
title: "Overnight Astra/Sol team: make Deep Agents workflows functional through small fixtures"
description: "Implement and prove service prerequisites, StageGraph, GoalDirected and same-application linked workflows in order, with evidence-driven repair and economical delegation."
date: 2026-10-29
status: archived
archived: 2026-11-02
archived_from: sprint-oc/SESSION-OVERNIGHT-WORKFLOWS-2026-10-29.md
archived_reason: "completed bounded assignment 2026-10-30"
---

> **Archived 2026-11-02** (completed bounded assignment 2026-10-30). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Overnight execution assignment

This is the current execution instruction. It supersedes older per-batch approval pauses,
two-cycle repair limits, and service-only stopping points for the local work below. NEXT-SESSION
remains the single current progress board. Earlier recovery and preparation documents are evidence.

## Goal and operating authority

Make workflows functional with **Deep Agents**, output contracts, context transfer and actual
capability materialization. Work in this order: shared service prerequisite → StageGraph →
GoalDirected → same-application Linked Workflows. For each workflow, implement the needed code,
run its small representative fixture immediately, repair, then advance. Do not implement all
families first and postpone the fixtures. Do not stop after preparing another plan.

Owner direction, this conversation 2026-10-29: allow more repair cycles, prioritize functional
workflows and partial fixtures, and move fast because the system is unreleased and has no real
users. The owner reports databases were wiped; this is context, not proof of any target's current
identity or permission for a new blanket wipe. Avoid speculative backward-compatibility layers.
Necessary contract-conforming refactors, adapters, local schema/install fixes, disposable local
fixture infrastructure, tests, review, documentation and verified local commits are authorized.
Do not request approval again for routine engineering within this scope.

No paid model/search calls, remote installs/wipes, push, unrelated cleanup or stress/W5 launch is
newly authorized here. Use scripted provider/model behavior with real local services first. Preserve
host authority, exact digests, actor/tenant isolation, independent evaluation roles and truthful
failure status. Unreleased does not justify disabling those requirements or silently editing
immutable published seed/release bytes; use coherent successors/fresh fixture installations.

## Team: spend Astra on reasoning, Sol on bounded work

- **Lead/integrator: GPT 6 Astra (`gpt-6-astra`).** Own dependency order, accepted-contract decisions,
  cross-service integration, evidence disposition and source custody.
- **Astra subagents (`gpt-6-astra`)** handle difficult runtime/authority/recovery implementation and
  independent review of consequential changes. Do not use Astra for inventory gathering or routine
  mechanical patches. Use one by default; a second only when an independently owned hard task merits it.
- **GPT 6.1 Sol (`gpt-6.1-sol`)** handles small tasks and context accumulation: narrow code tracing,
  test scaffolding, reproducible diagnostics, bounded mechanical fixes, documentation and receipts.
  Astra agents may delegate these subtasks to Sol. Give an exact question, writable files, expected
  output and stopping boundary. A Sol failure that requires architectural judgment returns to Astra.
- Maximum **four live agents including the lead**, respecting any lower available tool limit.
  Typical shape: Astra lead + Astra implementer/reviewer + Sol current-task helper + Sol next-phase
  scout. Idle/completed agents should be reused. Do not create user-visible chats for subtasks.
- Parallelize research, independent review and disjoint small edits. Serialize shared contract,
  bootstrap, migration and seed edits; one writer per shared file. Serialize integration and all
  heavy build/database/Temporal/fixture jobs. Nobody edits source under a running service fixture.

Model roles above concern the coding team. They do not select or authorize runtime mission model
profiles. Record those separately, even when the runtime model is a deterministic test double.

## Start from live source, not a historical branch

Workspace: `C:/Users/Pinda/Proyectos/BellLabs`. Read its AGENTS, platform/AGENTS, owning AGENTS,
NEXT-SESSION, OUTPUT-CONTRACTS and relevant WORK-ITEMS/PROOFS sections. Inspect status, HEAD and
worktrees in each owner. Reuse the primary `sprint-oc` checkouts; preserve dirty/ignored material.
Known preparation baseline: MC `5188747d`, KS `7fd88d06`, AIDB `74fd2c3`, BKS `8e8d3d1`.
Verify these rather than resetting to them. No broad branch/scratch/schema-IR scans.

Assign a Sol scout to produce a compact gap/entrypoint map while the lead checks the nearest
failing boundary. Use existing issue coverage, including WI-01/02/03/06/08/16/19; WI-16 is
OVE-179. Missing tracker connectivity queues a truthful sync; never claim issue completion.
Use one ignored evidence root with a phase/run subdirectory per attempt. Keep secrets out of logs.

## Phase 0 — shared service and sandbox prerequisite

Use the prepared partial fixture, not a newly invented search wrapper. From MC:

```powershell
.venv/Scripts/python.exe scripts/report_source_context.py --profile ai-engineer --out .scratch/overnight-<fresh>/context
.venv/Scripts/python.exe scripts/report_source_sandbox.py --context .scratch/overnight-<fresh>/context --out .scratch/overnight-<fresh>/sandbox
.venv/Scripts/python.exe scripts/report_source_sandbox.py --verify --out .scratch/overnight-<fresh>/sandbox
.venv/Scripts/python.exe -m pytest -q --override-ini addopts= tests/unit/test_report_source_sandbox.py tests/integration/deep_agents/test_report_source_sandbox.py
```

The six exact skills include Tavily/Firecrawl fixture guidance and canonical KS procedures.
Mount whole bundles through the Deep Agents materializer; references contain report contracts,
START_HERE, SCHEMA_ROUTE and `partial-fixture.json`. Optional entity cards are read-only navigation.
Skills do not connect tools or install CLIs. Historical MCP snapshots are not live schemas.
Inspect actual tool names/schema digests, profile routing, scope, grants and materialization receipts.
Prompt/skill instructions are guidance; actual runtime configuration and backend reads are the proof.

Prove in small steps: discovery attempt → selection → KS captured bytes → exact located fragments
→ K01 report registration → MC submission. Default to host-managed KS discovery with a scripted
provider response; direct admitted provider tools plus self-reported KS import is a distinct route.
Do not confuse executor managed discovery with platform candidate ranking. Use two local HTTP
documents, a parameter-count question, two-to-four claims, three queries/captures and three semantic
repair attempts per fixture. Give task/schema direction without supplying the producer's answer.

Read data-plane guidance first. Verify loopback database and disposable artifact-storage identity;
set up the necessary local storage rather than silently skipping it. Existing KS discovery tests
may skip when storage is absent: detect that and report the prerequisite unproved. Reconstruct the
service and read the captured bytes. Check replay, wrong/missing digest and scope refusal.

Inspect and implement the capture/locator→K01 fragment/custody bridge under the existing contracts
if missing. Missing code is an implementation task, not an automatic permission stop. Do not mint
synthetic references or replace capture identity with copied bytes to get a passing result.
Escalate only a genuinely unsettled authority/product contract, not an ordinary adapter gap.

Phase 0 may stop at submission. Workflow phases below must add their ordinary trusted settlement
and acceptance paths; do not inherit controller promotion as production behavior.

## Phase 1 — StageGraph: implement, then prove

Minimum representative fixture: one producer creates/submits a small evidence report; a dependent
consumer reads the exact accepted report and writes a short source-attributed summary. Use two
stages, one required report reference, a required progress/text output, and an optional output.

1. Inspect authoring/compile → launch → graph scheduling → Deep Agents materialization →
   submission/KS assessment → host settlement/fulfillment → sealed transfer → consumer backend.
2. Implement missing logic at the owning common module/adapter. Keep common contracts neutral.
3. Run through ordinary local execution interfaces with real PostgreSQL and Temporal for claims
   about mission scheduling/recovery. A direct adapter test is useful but is not that mission proof.
4. Positive proof: actual effective model/tool/skill/backend configuration, exact accepted revision,
   actual consumer reads, output fulfillment and terminal reason.
5. Negative/recovery probes: omitted/held required output blocks the consumer; an optional omission
   is explicit; stale/sibling/wrong-digest content is excluded; duplicate delivery after a targeted
   receiver restart does not repeat settled cognition or effects. Keep durable payload custody real.

Do not expand into Swarm, arbitrary branching/group reduction or nesting just to make this fixture
large. Existing behavior outside the changed boundary gets focused regression checks.

## Phase 2 — GoalDirected: implement, then prove

Use one producer and the normal independent verifier roles. Start with a small unsupported claim,
produce grounded findings, repair to a successor report, reassess and terminate under host control.
The local negative scenario may be scripted; candidate assertions/prose stay producer-authored.

Prove exact candidate/rubric/evidence delivery to the evaluator, distinct actor/session identities,
full actionable feedback to the next producer iteration, successor lineage, current fulfillment
and the actual stop decision. Unavailable evaluation waits/retries rather than becoming rejection;
stale findings cannot accept a successor. Persistent failure stops at authored iteration/no-progress/
budget bounds. Target a restart after saved cognition or before settlement and show no duplicate
cognition/registration. Do not waive a real review/use gate to make the loop finish.

Dedicated Evaluator Optimizer may be deferred if unintegrated. Approved EO shares GoalDirected
machinery (OC-D205); it is not a StageGraph variant. Ordinary GoalDirected verification and repair
are required here even when dedicated EO/Swarm work is deferred.

## Phase 3 — Linked Workflows: implement, then prove

Scope: two missions **within one application**, each with its own goals, grants and budget.
This is distinct from nested ProgramNode/subgraph execution (WI-13), which is not required here.
Current `domain/context/transfer_builders.py::linked_mission` refuses `LINK_INPUT_UNSUPPORTED`.
Reuse the existing chain release/relay/launch machinery and implement the accepted WI-16/§10
exact export/transfer/adoption behavior. Do not call a manual copy between runs a working link.

Start with mission A exporting one accepted report and mission B receiving that exact revision.
Record source/caller/receiver/adopter identity, explicit export, independent receiver authority,
purpose, sealed input and actual backend reads. Test acceptance gate before launch, duplicate relay,
restart, revocation and cancellation before/after consumer start. Preserve the accepted default:
an already-running consumer continues on valid sealed inputs after upstream cancellation unless
propagation is selected; distinguish spawned-child cancellation from attached-run detachment.
Add a separate held-report repair-purpose case when the basic link works: held content must not
become official accepted use or parent fulfillment merely because it is available to repair.

Run AI Engineer first. Repeat application-sensitive storage/qualifier/custody boundaries with the
Biotech report-only binding after the common route passes. Do not silently claim both-app coverage
from one app, and do not make Biotech native ingestion/mapping a prerequisite for report-only proof.

## Precise implementation and proof routes

GPT 6.1 Sol inspected these against clean MC `5188747d` / KS `7fd88d06` for this handoff.
Recheck live source; this map is not a new pass claim. MC paths are below `src/mission_control/`
unless prefixed `tests/` or `scripts/`; KS paths are explicitly marked.

| Boundary | Start here | Existing focused proof to extend, not rename as full acceptance |
| --- | --- | --- |
| Service/custody | KS `apps/verification-executor/src/knowledge/{context.ts,operations.ts,source-discovery.integration.test.ts}`; `packages/host/src/knowledge-operation/service.ts` | MC `tests/integration/deep_agents/test_report_source_real_service.py` starts with prebuilt evidence and controller promotion; it does not qualify discovery or independent settlement. |
| StageGraph | `adapters/temporal/workflows/stagegraph.py::StageGraphWorkflow.run`; `adapters/temporal/orchestration_activities.py::StageGraphActivities`; `application/programs/service.py::{StageGraphLaunchService,StageGraphDecisionService,StageGraphOperationPreparationService,_stage_transfer}` | `tests/integration/temporal/test_wi08_graph_routes_temporal.py`; `test_rrm_021_stagegraph_baseline.py`; `scripts/report_source_foundation.py --shape transfer` renders only. |
| GoalDirected | `adapters/temporal/workflows/goal_directed.py`; `application/programs/goal_directed.py::{GoalDirectedOperationPreparationService,GoalDirectedOperationResultService,_iteration_transfer}` | `tests/integration/temporal/test_rrm_016_goal_directed_journaled.py`; renderer `--shape repair`. Preserve intentional optional next-iteration fallback; do not blindly turn `FAMILY_INPUT_REQUIRED` into StageGraph's required-input policy. |
| Mission links | `domain/context/transfer_builders.py::linked_mission`; `application/chains/{service,reducer,relay,packet}.py`; `adapters/postgres/chains/store.py::{ChainReleaseHook,_admit_consumer,PostgresChainSupplies}` | `tests/integration/postgres/test_chain_release.py`; `tests/integration/temporal/test_chain_start_idempotent.py`; `tests/acceptance/mission_control/test_chain_two_goal_loops.py`. Older packet/release proof does not establish new exact linked transfer. |
| Adoption/child distinction | `application/outputs/adoption.py::OutputAdoptionService.adopt`; `application/programs/linked_runs.py`; `adapters/temporal/linked_run_workflow.py` | Adoption already retains source lineage and target checks. Sponsored child slots differ from independent mission-chain supply; use the relationship actually requested. |

The local production stack helper is `tests/fixtures/mission_control_production_stack.py::open_postgres_production_stack`.
It uses `MISSION_CONTROL_TEST_ADMIN_DSN` for verified loopback PostgreSQL 17/pgvector, fresh isolated
databases and restricted runtime/checkpointer roles. Local Temporal uses `MISSION_CONTROL_TEMPORAL_CLI`
or its cached SDK executable. `MISSION_CONTROL_E2E_KEEP_DATABASE=1` can retain a failing fixture DB
for diagnosis. Never print DSNs. Psycopg saver tests on Windows need the existing Selector-loop
convention; async subprocess fixtures must remain compatible rather than changing production logic.

KS discovery's `SOURCE_DISCOVERY_REMOTE_CUSTODY_REQUIRED` is a composition/configuration failure,
not permission to point at a remote target. Its existing `describe.skipIf` must be accounted for.
Use the supported artifact-storage configuration on a verified disposable local target.
Build KS protocol before host, from KS:

```powershell
corepack pnpm --filter @aiengineer/knowledge-operation-protocol build
corepack pnpm --filter @aiengineer/knowledge-host build
```

Narrow test selection template from MC: `.venv/Scripts/python.exe -m pytest -q --override-ini addopts= <exact-test-path>`.
Inspect the existing test's prerequisites and any doubles before interpreting its result.
Do not modify accepted scope/grants or bypass receipt custody to reuse an easier test harness.

For ordinary authenticated mission execution, reuse `scripts/sprint_oc_w1_driver.py` with
`--app ai-engineer --api http://127.0.0.1:<verified-port> --manifest <mission.yml> --pack <pack.json>
--evidence .scratch/overnight-<fresh>/<phase> --token-file <protected-local-token-file>`.
Select explicitly verified scripted runtime profiles with `--producer`/`--consumer`; do not
accidentally use paid default profiles. Subcommands are `compile`, `submit`, `start --run <id>`,
`wait --run <id> --timeout 1800`, `collect --run <id>` and `validate --run <id>`.
Use `--minimum-iterations 2` for a repair success; `--expected-unfulfilled <key>` only for an
explicit negative probe. Driver validation inspects persisted acceptance; it is not independent
qualification. Read the actual flags and authenticated target before executing placeholders.

## Required readable fixture evidence

Latest owner request: "I want to see the effective run configuration, what it materialized,
the workflow transcript and the outputs." This is a deliverable for every attempted fixture,
including failures, not an optional final summary. Prepare collection before the first run;
collect on success, failure and timeout while source/receipts are still available.

Create `.scratch/overnight-<session>/INDEX.md` with one row per phase/run/repair attempt, observed
result and relative links to readable files. Under each run, produce:

```text
README.md                         objective, result, real/scripted parts, missing evidence
01-authored-mission.yml            exact submitted fixture manifest
02-effective-run-config.json       full effective config snapshot with secret values redacted
02-effective-run-config.md         readable configuration summary, pins and config changes
03-materialized/<unit-or-attempt>/ actual provider binding/config, manifest and receipts
03-materialized/INDEX.md           authored → effective → actually materialized comparison
04-workflow-transcript.md          complete ordered readable transcript across steps/iterations
04-workflow-transcript.jsonl       corresponding machine-readable event/frame records
05-outputs/                       exact report bodies, summaries and other readable outputs
05-outputs/INDEX.md                producer/slot/revision/digest/status and file links
06-evidence/                       selections, captures, plans, delivery/assessment/fulfillment receipts
07-validation.md                   expected/observed checks, failures, fixes and next blocker
```

Effective config must show model/provider route, tools and schemas, skill versions/digests,
instructions/context policy, output obligations, budgets/governors, sandbox/backend/checkpointer,
and relevant application/run/unit identities. Materialized evidence must come from actual
bindings/manifests/receipts, including attached skill/context files and receiving read evidence;
do not regenerate the intended config and present it as observed materialization. Explain drift.
Retain distinct effective config versions when steering/revision changes them during a run.

The transcript must make producer/evaluator/consumer identity and chronology legible: stage,
iteration, attempt, tool calls/results/errors, observable model messages, feedback, submissions,
acceptance/hold decisions, waits/retries and completion. Include model-visible prompts/context
where recorded and authorized; do not invent private reasoning or fill missing events with prose.
Separate narrator summaries from observed events. Linked runs need a combined navigation timeline
and separate per-run transcripts so parent/child identities are not conflated.

Reuse `interfaces/http/transcript.py`, `interfaces/http/runtime_inspection.py`,
`interfaces/http/output_inspection.py`, `domain/frames/render.py`, and the documented transcript
projection. `sprint_oc_w1_driver.py collect` already saves inspection/output/transfer/transcript
JSON, but is not a complete readable exporter: follow all transcript cursors (`X-Transcript-Next-Cursor`),
request full bodies where supported, resolve run-authorized body refs, and render Markdown through
the existing renderer. Mark expired, denied, truncated or unavailable bodies explicitly. Paginated
or excerpt-only collection must not be labeled complete. Add the small exporter/collection glue
needed for this deliverable; do not build a new observability subsystem.
The Markdown renderer also caps displayed text: preserve authorized complete bodies in linked
readable sidecar files and mark excerpts. All-pages collection alone is not full-body completeness.

Export actual output artifact bytes through authorized reads, preserving digest and status.
Distinguish submitted drafts, held reports, superseded revisions and accepted outputs; include
the report text, not only its handle. Preserve source/capture/selection links for each claim.
Keep credentials, auth headers, cookies and DSNs out of readable files; preserve ordinary token
usage/cost metrics. Do not commit private transcripts/capture payloads. Final response must link
the session INDEX and each workflow's best available README/transcript/output index using absolute
local paths. If an export fails, record the gap and fix it within the ordinary repair loop.

Readable evidence is part of each phase's completion gate. A passing pytest count without these
files is insufficient for the owner's requested fixture result. For direct service-only probes,
label the transcript as a service-call trace and state that no mission transcript exists yet.

## Repair policy: persist, diagnose, keep moving

Use up to **six targeted implementation→rerun cycles per failing boundary before an explicit lead
reassessment**. This is an engineering default, not an owner-imposed hard stop. The previous
two-cycle limit does not apply. Continue in further batches when there is a concrete new hypothesis
or measurable progress. Never relax a required assertion, substitute a mock, or reclassify a failed
test as passing to advance. Coding repair cycles are separate from mission iteration/tool budgets.

After three identical failures without new evidence, stop repeating the same command: get an
independent diagnosis, improve observability or reduce to a smaller reproducer, then continue.
At six cycles record cause, attempts, evidence and revised strategy. The lead may change the
implementation approach within the accepted contract without asking the sleeping owner.
An unavailable external prerequisite blocks that proof, not all useful work: continue disjoint
implementation/review or a smaller captured-evidence workflow fixture, explicitly withholding
the combined search-to-workflow claim. Never relabel a skipped dependency as satisfied.

Pause only the dependent branch for missing credentials/authority, genuine contradictory semantics,
an unsafe/unidentified target, or a required paid/remote action outside authorization. Record an
exact next action and continue authorized independent work. No routine approval pings overnight.

## Review, integration and final report

Freeze tested source while a fixture runs. Preserve actual nonzero/timeout exits and diagnostic logs.
After each coherent change, get independent review, run relevant lint/type/contracts/tests, and
commit named files locally. Use recoverable small commits; no push. Rebuild changed package runtime
dependencies (KS protocol before host); source-mapped types alone do not prove fresh runtime builds.
One final affected-boundary regression after integration; do not repeatedly run the entire suite.

Update NEXT-SESSION in place with per-phase implemented/tested/integrated/blocked/unrun status,
exact commits and fixture/version/identity/policy/tool/model/schema pins; real vs scripted components;
receipt/plan/readback locators; failures and repair lineage; resources/cost and next blocker.
Run owner documentation checks. Do not claim W1/W2 or full sprint release from this narrower work.
Final report leads with which workflows now function through ordinary runtime and which do not.
Leave a paste-ready next action, not another broad investigation request.
