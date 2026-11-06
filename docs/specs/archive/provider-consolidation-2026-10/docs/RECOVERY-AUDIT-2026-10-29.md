---
type: Audit
title: "Sprint OC recovery audit and remaining route to the W5 owner checkpoint"
description: "Source, Git, worktree, interrupted-review and recorded-proof reconciliation after Claude Code exhausted credits; a concrete continuation plan without new runtime qualification."
date: 2026-10-29
status: archived
archived: 2026-11-02
archived_from: sprint-oc/RECOVERY-AUDIT-2026-10-29.md
archived_reason: "remaining scope copied into the NEXT-SESSION board"
---

> **Archived 2026-11-02** (remaining scope copied into the NEXT-SESSION board). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Recovery audit

**Later owner steering, 2026-10-29:** the [controlled recovery assignment](../sessions/SESSION-CODEX-RESUME-2026-10-29.md)
replaces this audit's proposed autonomous execution/team sequence. The owner selected “Approve each
integration batch” and requested clarification of Swarm/EO architecture before completing it.
The evidence below remains dated; its W1–W5 backlog is not authorization to execute that backlog.
Use [NEXT-SESSION](../../../provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md) as the current control board; retrieve this audit by section.

This audit was requested to prepare the next Codex team, not to execute the sprint in this session.
It reconciles all four owners, retained worktrees, the accepted packet, ignored claims and W1 evidence,
and the interrupted Claude session's last reviews. Source and Git were freshly inspected on
2026-10-29. Remote branch heads were read with `git ls-remote`. Database/provider state and Linear
were **not** freshly queried. Historical test results below are attributed to their recorded heads.

Read [NEXT-SESSION](../../../provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md) for the short entry point and
[the team assignment](../sessions/SESSION-CODEX-RESUME-2026-10-29.md) for a paste-ready instruction.
This dated evidence supersedes the earlier handoffs' current-state claims, not the accepted contracts.

## 1. What happened and where the sprint actually is

The integrator stopped on 2026-10-29 at approximately 07:09 America/New_York when Claude reported its
weekly limit. Four implementation helpers stopped around 07:07–07:08, leaving edits on disk. Their
last activity was substantive repair work, not cleanup after successful completion:

| Work | Last recorded activity | Consequence |
| --- | --- | --- |
| MC native write | About to rewrite the service's write/settle/apply section after review | Core stale-decision and settlement findings remain in the inspected source. |
| KS native preview | Changing the integration test to use the binding's own normalized-values digest | Two test files dirty; final rerun and commit not completed. |
| Swarm | About to replace `start_swarm_body` | New reducer/authoring concepts are dirty, but the old busy-loop workflow remains. |
| Evaluator Optimizer | Debugging restart/resume after the initial wait behaved correctly | Entire feature is uncommitted, with no completed independent review. |
| Integrator regression | Twelve-way unit split, seed regression repaired and committed | Full integrated regression not finished; no push of the latest 15 MC commits. |

**W0 is recorded released. W1 is open.** Source ahead of W1 includes collections/current sets,
graph routes/release groups/revisits, recursive programs and future-family work. That is permitted
implementation overlap; it does not release the later gates. There is no evidence of W2, W3 or W4
real checkpoint release. W5 and the stress missions remain ahead.

The first mandatory owner wait is **W5 start / OVE-186**. W5 is the full four-family qualification
in both applications. The later complex real-world stress fixtures have two additional checkpoint
levels: stress setup OVE-187, then each OVE-189/190/191 mission. See OC-D203 and
[ESCALATION §4](../../../provider-consolidation-2026-10/sprint-oc/ESCALATION.md#4-owner-checkpoints-notify-and-wait-no-heuristic-applies).

## 2. Git, worktrees and recovery custody

Paths use the BellLabs root `C:/Users/Pinda/Proyectos/BellLabs`. All four primary owners are on
`sprint-oc`; do not use their `main` branches as a fresh starting point.

| Owner | Local sprint head at audit entry | Remote sprint head, freshly read | Main | Primary status on entry |
| --- | --- | --- | --- | --- |
| `platform/mission-control` | `d42b04b8f426dfb436545142ad1a0d80b9dc6a76` | `2c0738dcf204aad343308b4f93834dc48aaf20da` | `3e5043ed` | Clean; 15 commits ahead. |
| `platform/knowledge-services` | `22b47d251877b18fdd995aaa6a00ef43adfd4393` | Same | `1fb92de` | Untracked `.claude/` only. |
| `aiengineer/ai-engineer-db-contract` | `74fd2c3ef45dfa39eacedb590a2494791b7c182a` | Same | `306efd7` | Clean. |
| `biotech/biotech-knowledge-services` | `8e8d3d1e5f96d98d096abbb169f28d79d8c02eab` | Same | `c398177` | Clean. |

Read-only remote access worked during this audit despite the older GitHub-account warning. This
does not establish push permission. No fetch, push, merge, checkout or reset was performed here.
Documentation changes from this audit are additional to the entry-state snapshot.

### Work that is not integrated

Counts are `git rev-list --count sprint-oc..HEAD` and the reverse, within each owner.

| Repository / branch | Head | Unique / behind | Dirty state | Location and disposition |
| --- | --- | --- | --- | --- |
| MC `sprint-oc-w1` | `a5fd5286` | 20 / 15 | Clean | `.claude/worktrees/w1`; nine changed files: driver, bindings, pack builder, five manifests and `release/W1-EVIDENCE.md`. Review and update, then integrate; preserve runtime evidence separately. |
| MC `sprint-oc-w1fix-n` | `5ff29ff8` | 1 / 13 | 11 modified + 1 untracked test | `.claude/worktrees/w1fix-n`; changes-required review plus unfinished repairs. |
| KS `sprint-oc-w1fix-n` | `f457e8f` | 1 / 0 | 100 status entries | `.claude/worktrees/w1fix-n`; two substantive test edits, 98 generated files equal to HEAD after CRLF normalization. Do not bulk-stage generated churn. |
| MC `sprint-oc-wi14` | `4fa865b7` | 2 / 10 | 6 modified | `.claude/worktrees/wi14`; Swarm implementation/docs plus incomplete repair. |
| MC `sprint-oc-wi15` | `159f38d4` | 0 / 10 | 17 modified + 11 untracked files | `.claude/worktrees/wi15`; EO exists only as working-tree edits, including SQL, modules, fixtures and tests. A branch-only merge would lose the feature. |

There are **59 registered worktrees**: MC 42, KS 8, AIDB 4, BKS 5. All other retained non-primary
heads are ancestors of their owner's `sprint-oc` and have clean source status. They remain retained,
not deletion candidates. Branches without a worktree also exist; their names do not establish a
separate active assignment. The full registered inventory appears in the appendix and in the local JSON.

Recovery material created by this audit, ignored and not intended for commits:

- `.scratch/sprint-oc/codex-recovery-2026-10-29/inventory.json`: exact heads, paths, divergence and status.
- Four ZIPs named `<owner>-<branch>.zip`: dirty source copies, staged/unstaged binary patches,
  base/status metadata and per-file SHA-256. These supplement the original checkouts.
- `syntax.json`: AST-only checks of 40 dirty/new Python files; all parsed. This proves syntax only.

The archives contain the selected dirty source files, not credentials or runtime receipts. Do not
restore them over later edits. The ignored claims/evidence/runtime folders and W1 Temporal database
are still needed; a source ZIP is not a substitute for that runtime custody.

## 3. Recovered reviews: the immediate unfinished work

The reviews were present in Claude subagent logs but absent from the final claims rows. Treat them
as historical independent review findings, confirmed where noted against current dirty source.
No review approval was recovered for these final repair revisions.

### 3.1 Native write, OVE-169, MC and KS together

Design now being built: the later applying invocation selects an exact officially usable report from
its sealed plan; the host builds the existing native intent, previews the plan digest, requests a
**plan-level** KS use decision, records it, and applies under the same invocation identity. A report
review does not approve the native plan's different digest. A decision cannot simply be passed from
one invocation to another. The earlier plan to decide in iteration 1 and apply in iteration 2 was
rejected after inspecting the origin-bound native planner.

The implementation uses `ClaimMaterializeIntentBuilder` for AIDB's existing `claim.materialize`
intent. Biotech uses `NoNativeIntent` / `SCHEMA_UNSUPPORTED`: no report-to-graph mapping was admitted.
The prior integrator labelled this H11, not permission to invent a product mapping. Recheck whether
an existing admitted graph-intent fixture can satisfy the applicable native-write proof. If not,
record the exact blocked criterion and obtain its scope/applicability disposition; do not transform
the blocker into a pass or quietly drop Biotech.

The independent review of MC `5ff29ff8` + KS `f457e8f` returned **CHANGES REQUIRED**:

| Finding | Required repair/evidence | Current audit observation |
| --- | --- | --- |
| High: `write()` always reuses `recorded[-1]`; native DB drift makes the decision permanently stale | On `EFFECT_CONFLICT`/`STALE_DECISION`, preview again, re-decide if the bound digest changed, preserve immutable decision history and correct per-subject/invocation selection; test drift | The old `recorded[-1]` path is still present in dirty `application/knowledge/native_write.py`. |
| A rejected/stale decision raises out of the entire settlement loop | Handle refusal per decision, retain a visible typed outcome, continue independent decisions; skip already-applied effects; prove no duplicate dispatch | The inspected loop still calls `_apply_if_usable` without per-decision refusal handling. |
| Run identity parsed from `ud-<run>-<16hex>` | Prefer an authoritative recorded run field; otherwise pin the actual KS identity contract with tests | `_DECISION_ID` parsing still present. |
| Crash after KS decide but before MC record may orphan a decision when the digest changes on replay | Recover appropriately or explicitly document harmless retained lineage; test the crash window | No completed repair/review evidence recovered. |
| Settlement applies lose their returned receipt as an output | Expose effect keys/receipts in inspection/events and reconcile `effect_receipt` promise fulfillment | Internal journal observability alone is not proof of the W1 manifest's required native receipt. A reviewer cannot silently waive PROOFS §4. |
| Empty normalized-values digest must match native admission | Cross-language parity and actual preview→decide→apply test using the binding's own digest | KS dirty tests address this; final rerun/commit still needed. MC dirty code verifies the empty digest. |
| Millisecond attempt may defeat request coalescing | Trace resolve/decide request-key construction and prove which fields participate | Confirmation requested; no final completion report recovered. |

MC/KS contract alignment was also interrupted. KS preview is a synchronous read-only reply, not a
tracked operation handle. Dirty MC edits add a direct `plan_preview` gateway/client route and remove
the unnecessary handle-operation constraint change from 0069. Preview consumes a credential nonce;
each request needs a fresh credential. Preview's plan ID ignores decision fields, while native
receipt/idempotency semantics must remain stable. Test this over the actual HTTP/protocol boundary.

Key paths in the MC worktree: `application/knowledge/native_write.py`, `gateway.py`,
`adapters/knowledge/http_client.py`, `contracts/knowledge_protocol.py`,
`scripts/release_200/0069_native_plan_decisions.sql` (renumbered 0072 on 2026-11-01), `tests/unit/knowledge/test_native_write.py`,
`tests/integration/postgres/test_native_plan_decisions_postgres.py`, and untracked
`tests/integration/temporal/test_native_write_review_restart.py` (real PG/Temporal, doubled KS).
That new test's existence is not a passing result. KS paths: protocol `plan-preview.ts`,
host `service.ts`, AIDB `ingestion-apply.ts`, ingestion executor/planner, executor
`plan-preview.test.ts` and `aidb-apply.integration.test.ts`.

The prior H12 interpretation permits the same invocation's saved-result settlement to perform the
recorded apply after plan review. It is described in branch-local `docs/knowledge/native-write.md`
and claims, but not yet reconciled into DECISIONS §5 (which still ends at OC-D203). The next integrator
must record its provisional provenance and limitations without portraying it as a new owner answer
or rewriting an accepted ADR. The branch doc's unconditional replay claim needs correction after review.

### 3.2 Swarm, WI-14 / OVE-177

Committed implementation: StageGraph hosts the Swarm behavior behind `oc-wi14-swarm`; members and
convergence execute through the WI-13 nested-body machinery; pure reducer selects members; migration
0070 persists activation/member lineage. Historical helper report: five Temporal and two PostgreSQL
tests, plus focused regression. These results predate the interrupted repair.

Review of `159f38d4..4fa865b7`: **CHANGES REQUIRED**.

| Finding | Required repair and test |
| --- | --- |
| High: finished convergence remains in wait tasks while a member is active; `woke()` stays true and the workflow spins | Exclude finished convergence from wake tasks; real Temporal case where a best-effort/required/grace member outlives convergence. The old faulty code is still in the current worktree. |
| Retry shares can exceed the stage reservation | Bound shares over all permitted attempts plus convergence; charge all actual spend. Dirty lowering begins this repair; complete wiring and test retries. |
| Refused activation leaks reservation; failed settlement can still report stage result | Add guaranteed typed release/recovery, test activation refusal and settlement failure; do not accept with unresolved liability. |
| Lineage failures, including conflicts, are swallowed | Preserve typed conflicts, fail closed, record child run identity at start; prove crash/replay continuity. |
| Missing interaction tests | Late result, `finish_*`, grace, retry budget, cancelled-member effects, refused activation; cache-off restart is valid but must be explained. |

Dirty files add timeout/stop state, a release-request type, swarm input representation, retry share
changes and nested-body support. `swarm_body.py` itself has not yet been replaced; these pieces do
not establish functional repair. Review the six dirty files plus the two committed feature commits.

Remaining accepted-scope questions must become concrete code/proof dispositions: fan-out, actual
per-variant model/runtime, member timeout and swarm wall clock, other declared governors, swarm-level
input delivery, and Swarm as a Goal Loop executor body. The existing doc explicitly lists these
limits. Required family/C01–C13 rows cannot be passed by refusing selected behavior. Inspect the
underlying family annex as well as OUTPUT-CONTRACTS §9; avoid equating one quorum fixture with full Swarm.

### 3.3 Evaluator Optimizer, WI-15 / OVE-178

No unique commit. The working tree contains optimizer policy/authoring, pure round reduction,
`OptimizerRoundService`, PostgreSQL rounds/reports/attempts storage, GoalDirected workflow integration,
schema edits, migration `0071_evaluator_optimizer_rounds.sql`, fixtures and tests. It reuses the
GoalDirected round host with explicit optimizer semantics; it must still satisfy independent
producer/evaluator identity, exact candidates and hard gates.

Untracked files include `domain/authoring/optimizer.py`, `domain/programs/evaluator_optimizer.py`,
`application/programs/evaluator_optimizer.py`, `adapters/postgres/orchestration/optimization_rounds.py`,
and unit/PG/Temporal tests. The Temporal test declares doubled cognition/run control/fulfillment;
it is not a real-model or full PostgreSQL composition proof. The last helper message concerned
debugging restart/resume of an unavailable-evaluator wait. Do not assert the suite passes.

Preserve the implementation, finish that debugging, test stale findings and repair lineage,
accept-best hard gates, no-progress/budget/time bounds and restart. Independently review before
committing/integrating. Its base predates D27 verifier-role changes and D28–D30 settlement changes;
reconcile those explicitly. Swarm and EO both edit manifest/lowering/schema/deployment files: merge
one reviewed slice at a time and regenerate schemas from the combined source. Some EO diffs include
line-ending churn; inspect semantic changes without discarding the working files.

## 4. What W1 has actually proved

Evidence source: ignored `.scratch/sprint-oc/evidence/w1/W1-EVIDENCE.md` and `BUDGET.md`, mirrored
in the W1 worktree's tracked `docs/specs/.../sprint-oc/release/W1-EVIDENCE.md`. No new paid run occurred
in this recovery audit.

| Criterion | Recorded result | Remaining before W1 release |
| --- | --- | --- |
| AIE ordinary report | Real Sonnet report registered; `tool_auto` strategy used | Fresh complete successful run on integrated fixes. |
| Independent judgment | Real Terra Responses judge and separate Haiku auditor, KS observations and MC handles | Retain exact identity/input/usage evidence on final candidate. |
| Seal/use/review | After seal-key provisioning: seal→decision→held; launcher review 403; separate reviewer approval 200; promotion | Complete fulfillment and final acceptance after D27/D28 repairs. |
| Required note | Iteration-scoped progress note fulfilled | Keep scope and prove normal handoff behavior on final fixture. |
| Omitted required | Typed unmet and terminal failure observed | Regression on integrated head; preserve expected/optional distinction. |
| Saved settlement | Restart resumed saved result without repeated producer cognition; session 9 reused recorded observations | Full successful-path and native commit-before-receipt fresh-process recovery. |
| D27 verifier resubmitted producer output | Failed real run; role/tool/obligation fix merged `f292ee31` | Real rerun proves no verifier producer authority. |
| D28 promoted report not officially usable for fulfillment | Failed real run; reference-use provider wired, worst standing result wins; merged `00c0d0cd` | Real fulfilled report. Recorded standing evidence does not replace current eligibility checks at protected use/read. |
| D29 submitted text shown missing | Diagnostic fixed alongside D28 | Demonstrate `SUBMITTED_NOT_ACCEPTED`, not a false success. |
| D30 missing evaluator keys silently failed | Fixed `f9168027`: launch refusal and mid-run wait | Admission and changed-worker environment real probes; API/worker evaluator env alignment. |
| Held report / ungrounded disagreement | Review-held path observed; other negative criteria not fully demonstrated | Criteria-specific independent record; do not count review-required as every possible held/disagreement case. |
| AIE native write | Not run | Finish section 3.1; apply/readback/receipt/duplicate/crash proof. |
| Biotech report and native paths | Not started | All applicable W1 rows, AIE first; explicit native mapping/applicability disposition. |
| Gate release | No independent W1 release | Reviewer checks every positive/negative row; update evidence and tracker honestly. |

Last real main run `9cc17684...` terminalized failed after D27/D28. Missing-key run `76ddfa88...`
also failed. Inspect state before resuming anything; a terminal failed run is not automatically
re-opened by a code fix. Older runs `042beb7a...` and `29a1eae9...` have specific recorded settlement
and missing-handle history. Preserve their evidence and use fresh run/pack/record identifiers when
the replay contract requires a new run.

The W1 harness branch carries:

- `scripts/sprint_oc_w1_driver.py`, `sprint_oc_w1_bindings.py`, `sprint_oc_w1_pack.mjs`.
- `tests/fixtures/manifests/sprint-oc-w1/`: AIE report, omitted-required, native-write; Biotech report,
  native-write. The old planning note saying Biotech native fixture does not exist is obsolete.
- A committed evidence summary. Runtime captures, credentials and Temporal DB remain ignored.

Review and integrate the harness rather than rebuilding it. Its native instructions predate the
current contract and need repair. The saved stack used `temporal-w1-s4.db`; exact processes/ports/env
locations are in the runtime guide and evidence. Latest evidence says all W1 processes stopped.
This audit found no `claude` or `temporal` process by those names; that is not a complete port/stack check.

## 5. Remaining implementation and qualification map

This table distinguishes source presence from gate release. Issue status is from recorded local
evidence, not a fresh Linear read. WORK-ITEMS.json is a publication/dependency map, not current state.

| Items | Observed implementation | Remaining work / proof |
| --- | --- | --- |
| R0–R7 / OVE-195–202; WI-01–05 / OVE-163–167 | Integrated, prior reviewed completion recorded | Preserve; run affected regressions. R3 remainder OVE-203 is a later provider sweep unless an adopted W5 criterion needs it. |
| W0 / WI-24 / OVE-168 | Recorded released with limitations | Revalidate new releases and current environment at first use; do not repeat the original wipe by default. |
| W1 / WI-06 / OVE-169 | Sections 3–4 | Immediate critical path. |
| WI-07 / OVE-170 | Collection/current-set framework and 0066 integrated | Complete production trusted decisions for members of an actual collection manifest. Current `collections-and-current-sets.md` records `MEMBER_UNASSESSED` and YAML member-requirement limitations; accumulated report revisions alone do not close this. W3 proof. |
| W2 / WI-08 / OVE-171 | Conditional routes, groups, optional omissions, revisit code and six fixtures integrated | Real exact producer→consumer transfer in both apps, every W2 negative and public why-ready inspection. `DEPENDENT_INPUT_REQUIRED=True`; the separate `FAMILY_INPUT_REQUIRED=False` governs next-iteration fallback and is not evidence this W2 flip is missing. |
| WI-09 / OVE-172 | No delivered sprint transform implementation found | Versioned deterministic union/dedup/filter/sort/group/join/project/partition/validation; explicit populations/cardinality/unmatched/conflict policy; exact lineage and schema drift refusal. Reuse existing executor seams. |
| WI-10 / OVE-173 | No delivered inventory/partition slice found | Durable complete inventory, bounded activation windows, scoped leases, idempotent retry of same slice, governed successor/repartition, preserved successes and coverage, inspection/capacity fairness. No new pressure scheduling policy. |
| W3 / WI-11 / OVE-174 | Two report-collection manifests exist, no real gate evidence | Close groups using exact contributors or trusted channel closure; retain uncontested results; reduction regrouping/reordering qualification; realistic multi-report accumulation/transforms/synthesis, oversize and restart challenges. |
| WI-12 / OVE-175 | Existing revision primitives; no delivered selected reassessment slice found | Tracked changed revision and unchanged held-source acceptance; one active plus coalesced pending work; exact reuse; sealed running inputs; revocation independently enforced; no derived auto-approval. |
| WI-13 / OVE-176 | Integrated `159f38d4`, launcher/adoption, 0068 source | Release/install 0068; composed PG+Temporal proof and eventual real nested runs. Current docs note early exports are not delivered to running parent consumers and human-gate definition readers see whole revision: reconcile with accepted nested/export/control requirements before declaring complete. |
| WI-14 / OVE-177 | Unmerged and dirty | Section 3.2; no gate approval. |
| WI-15 / OVE-178 | Entirely dirty/untracked | Section 3.3; no gate approval. |
| WI-16 / OVE-179 | Reusable exact adoption seam exists from WI-13, old chain engine exists | Exact same-app exports/receiving grants, held repair, source goal acceptance, spawned cancel vs attached detach, pre/post-start cancellation, revocation and no duplicate effects; GD→GD and SG→GD in each app. |
| WI-17 / OVE-180 | Hook preparation integrated; historical Done as dormant code | Actual host consumption/install/preservation joins in W4; dormant code is not the live hook proof. |
| WI-18 / OVE-181 | Existing continuation/recovery base; selected delta not delivered | Consume validated preservation, prove post-compaction bytes, separate continuation generation, >=3 iterations/mid-stage threshold, historical fork bytes and missing-snapshot refusal. Reuse OVE-75 seam. |
| WI-19 / OVE-182 | Inspection/attention machinery integrated | C14 actual Codex idle→wake→model-visible→ack→retrieval in W5; six evidence stages. Coordinator KS excerpt origin still has a recorded fail-closed limitation. Surface held/exhausted evaluator roles actionably. |
| WI-22 / OVE-183 | Reaction code and 0061 integrated; historical Done/dormant | W4 fixture must compose it and prove duplicate, crash-after-admission, stale-generation, recursion/rate/time/spend controls. Investigate recorded release-after-start/BINDING_CONFLICT follow-up. |
| WI-23 / OVE-184 | Dynamic child binding/admission source integrated | C10–C13 real sync/async child tools/skills/MCP/models/backend, parent result use, controls, adoption, usage/effects and no duplicate child/admission in W5. |
| W4 / WI-32 / OVE-185 | No integrated checkpoint release | Independent cross-feature revision/recovery proof after WI-11/12/16/18/22. |
| W5 / WI-21 / OVE-186 | Four nested manifests exist; family set incomplete | Owner checkpoint before paid W5. Then all four actual families, eight forms, C01–C16, both apps, actual backend and host; selected OVE-73 human-gate seam. Routine use remains closed until release. |

### Gate fixtures and required completion criteria

| Gate | Reusable starting assets | Completion and important negatives |
| --- | --- | --- |
| W1 | Unmerged `sprint-oc-w1` harness and packs | Section 4; native readback and recovery are distinct from operational report storage. |
| W2 | `sprint-oc-w2/{ai-engineer,biotech}.producer-consumer.mission.yml`, route/group/revisit fixtures | Actually read selected revision. Compare prompt/files/handles, sealed plan, host state and aggregate resources. Exclude sibling/stale attempt/wrong slot; denied/corrupt bytes; combined overflow; held repair vs official use; new receipt on repeat delivery; unknown/order/quorum/optional rules. |
| W3 | `sprint-oc-w3/{ai-engineer,biotech}.report-collection.mission.yml` | Extend to transforms, bounded inventory and independent closure at a declared realistic envelope. Revisions cannot inflate distinct counts; mixed verdicts, concurrent heads, conflicts/unmatched joins, late/missing/unknown contributors, skew/indivisible oversize, restart mid-window, semantic loss challenge. |
| W4 | W3 outputs plus existing chain/continuation/hook/reaction tests | Author integrated fixtures for tracked/held reassessment, links/adoption, installed preservation and historical fork. Crash/race, late native ack, cancellation before/after start, no present-day substitution for historical bytes. |
| W5 preparation | Four nested `sprint-oc-w5` manifests; one Swarm worktree fixture; two EO worktree fixtures | Complete both-app family matrix and control/recovery/scale cases. Cover text, structured, file, reference, collection, code_change, effect_receipt, control_record. C14 must target the new Codex host, not inherit a Claude transport claim. |

### Dependency-aware execution order

1. **Recovery/integration front:** preserve dirty work; native MC+KS fixes and independent review;
   W1 harness; finish integrated regression; release/install required schema/protocol/seed changes.
   Swarm/EO repairs can proceed in separate worktrees, with shared schema/bootstrap ownership.
2. **W1:** AIE success and missing/held/evaluator/review/restart/native variants; then Biotech;
   independently release only on all applicable criteria. Record blocked native applicability honestly.
3. **W2 and collections:** W2 runtime proof plus WI-07 remaining collection authoring/bridge work.
   **WI-09→WI-10→WI-11** is the substantial remaining serial implementation chain leading to W3.
4. **Advanced independent scopes:** WI-12 reassessment, WI-16 links and WI-18 preservation/fork can
   develop against the integrated WI-07/08 seams while W3 implementation/proof progresses. Reconcile
   common context/output/bootstrap files through the lead. Finish WI-13/14/15 family requirements.
5. **W4:** integrated revision/recovery walkthrough and fault injection; independent WI-32 release.
6. **W5-ready handoff:** complete unpaid fixture/pin/model/backend/host/control preparation, review
   the matrix and unresolved gaps, then notify the owner and wait at OVE-186.

Do not use historical blockers OVE-75→181 / OVE-78→182 as a reason to redo entire older programs:
the recorded W0 seam audit replaced them. Verify current native relationships when Linear is available.
Do not make all OVE-150 a prerequisite; W5 closes its downstream SV-18.

## 6. Releases, runtime and budget

| Item | Last recorded or source state | Required next action |
| --- | --- | --- |
| MC common | 1.9.0, 58 migrations, fingerprint prefix `786f3aa9`; locks under `release/locks-190/`; remote apply/repeat recorded | Re-read actual target identity/version before install. Do not rebuild 1.9.0 in place. |
| MC next release | `scripts/release_200/0068_nested_program_activations.sql` integrated (renumbered 0071, native 0072, on 2026-11-01 after 1.10.0–1.12.0 took 0068–0070); 0069 native, 0070 Swarm, 0071 EO in worktrees; 2.0.0 not built/applied | Integrator sequences only finished/reviewed migrations, adds release artifacts/locks, installer pins, fresh/repeat/interrupted checks and live verification. If splitting releases, document new version allocation from live head. |
| KS component | 2.5.0, through 0008 effect journal; seal keys subsequently provisioned in both apps | Preview is runtime/protocol work; test whether component change is actually needed. Rebuild canonical executor dist and capture live descriptors after merge. |
| AIDB | Native migration head `20261025010200`, installer pins MC 1.9.0 / KS 2.5.0 | Native planner/apply/receipt tests and installer version synchronization. |
| BKS | Source/pin `biotech-schema-v2.2.0`; remote apply recorded | Owned SDL/native projection authority is BKS `schema/source`; old absent `biotech-meta` is not a blocker. |
| Seeds | workflow-parity 1.0.4 remotely applied and frozen; 1.0.5 successor at asset v6 local/unapplied; artifact-schemas 1.0.1 applied per claims | Reconcile WI-14/15 registrations, validate successor, seed-plan/apply/replan both targets. Never edit applied seed versions. |
| Local topology | Per-app remote PG saver; local Temporal development store; MC API/worker, KS and BKS executors per runtime guide | Verify ports/PIDs, model/evaluator keys, compiled source and built dist agree; never change source underneath a running stack. |

Use BellLabs' data-plane registry and the release environment guides for credentials **by name**.
Only the two named Supabase targets and Biotech Aura `8032ec07` are sprint targets; AI Engineer Aura
`4773dc72` is not. The registry's credential consolidation is a proposal, not evidence it happened.
Read wrappers before running them; they must load/scrub secrets inside the child, never print env files.

W1 last reported cumulative spend is approximately **USD 0.627**, of USD 6. Earlier uncertainty was
reduced from <=0.40 by observed evaluator costs; small session-4 uncertainty remains. The missing-key
probe appears twice in the budget prose and was counted once in the cumulative total: reconcile by
run/invocation before new reservations, rather than summing textual rows blindly. W0 probes ~USD 0.001.
No spending occurred in this audit. Coding subscription credits and runtime API budget are separate.

PROOFS §6 remains: USD 40 total, USD 15/session; allocations W0 1, W1 6, W2 4, W3 7, W4 5, W5 10,
reserve 7. Runtime pins remain producer `claude-sonnet-5-5`, independent judge `gpt-5.6-terra`, separate
auditor and children `claude-haiku-5-5`, with the documented fallbacks. These are packet pins, not a
fresh claim of current provider availability. Probe boundedly at first paid use, preserve vendor/role
independence, account for retries/children/evaluators and stop at caps. Stress budget is separate/unset.

## 7. Testing status and commands

Do not call the suite green. The last complete recorded integrated pass is on `2c0738dc` before
the local WI-13/D27–D30 merges: 36 named pre-existing unit failures, 420 conformance/architecture,
and the selected integration suite 161 passed / 1 failed / 2 errors. This audit read the integration
log and the latest partial unit logs; it did not rerun runtime suites.

| Latest local evidence | Result / interpretation |
| --- | --- |
| `unit-s3-n00.log` | 1456 passed, 20 skipped; only the first pair of the new twelve-way split. |
| `unit-s3-n02.log` | 1193 passed, 4 failed: two known digest-audit failures plus two seed regressions. |
| `d42b04b8` seed fix | Claims record 19 focused seed tests passed; new successor freezes 1.0.4. Complete chunk rerun still needed. |
| `unit-s3-n04.log` | 1265 passed, 1 skipped, 4 known cursor closing-facts failures. Remaining split coverage not found. |
| Native-write/Swarm older helper tests | Historical results on pre-review commits; do not certify dirty repairs. |
| EO tests | Test code present, restart/resume debugging incomplete; no complete passing evidence. |

The historical 36-unit baseline consists of 22 Run-2 PowerShell deployment-script cases, seven BKS
schema-pin/digest cases, four cursor closing-facts cases, two digest-set audits, one prerequisites
wording case. Match exact failing test and cause, never just the count. Shell changes can alter these.
The selected integration baseline has `test_mp22_local_profile_start` (missing example model profile)
and two `test_chain_two_goal_loops` errors (local tooling/custody fixture). Wider pre-sprint integration
failures are listed in IMPLEMENTATION §1. If a baseline defect blocks an adopted proof, its age does
not waive the proof; fix the needed seam with ownership.

Owner verification commands from each repository root:

| Owner | Gates |
| --- | --- |
| MC | `make ci`, `make docs-check`, `make skills-check`; affected actual PG/Temporal/acceptance; `make manifest-schemas-check`, `make test-db-contract`, `make seeds-validate` when touched. Underlying authoritative typing is mypy. |
| KS | `corepack pnpm verify`, affected protocol/host/binding/maintenance/context tests and native integration; `.agent-docs` build/check after authored docs updates. |
| AIDB | `npm run typecheck`, `npm test`, type drift, workspace check/validate, installer and native proofs. |
| BKS | `pnpm build`, `pnpm test`, `pnpm workspace:verify`, `pnpm client:pack-check`, required real Neo4j/HTTP proof. |

Existing local scripts `.scratch/sprint-oc/run_unit_chunk.sh` and `run_integ_s3.sh` document the
foreground test selection/environment. **Inspect their exit behavior**: they echo pytest's result,
then run grep; the shell's final status can be success after a failed/timed-out pytest. Capture the
test process status and completion summary explicitly. Integration script also names one fixed log;
avoid overwriting historical evidence when extending its selection. Its list does not cover all new
WI-13/native/Swarm/EO tests.

Check memory separately before each heavy job. Recorded owner floor: tests 1.5 GB available; W1
stack 0.8 GB on an exclusive machine; stop below 0.4 GB. Vitest `--maxWorkers=2`. Keep one heavy job,
use bounded foreground chunks, keep exact HEAD/test coverage, terminate only owned PIDs. Do not infer
success from absent output or restore obsolete aliases to satisfy stale traceback paths.

Audit verification itself: baseline and final `python docs/tools/check_docs.py` passed all seven
checks (OKF, index, three ledgers, links, shipped skills); `git diff --check` passed. All 40 dirty/new
Python files passed AST parsing; 98 KS generated status entries were compared to HEAD and matched
after newline normalization. All four recovery ZIPs passed integrity checks, and their source hashes
still matched the untouched original worktrees. These cheap checks do not validate runtime behavior.

## 8. Team assignments and shared-file ownership

Recommended first rotation, four active agents including lead:

| Slot | Model / responsibility | Scope |
| --- | --- | --- |
| Lead | GPT-6 Astra | Contracts, integration, migration/seed versions, evidence/gate status, runtime/paid jobs. Review cross-owner native semantics; keep formal independent gate reviewer separate from the run implementer. |
| A | GPT-6.1 Sol | Native-write repair across the existing MC and KS `w1fix-n` worktrees; one paired protocol owner prevents another mismatch. |
| B | GPT-6.1 Sol | Existing WI-14 worktree, review findings and missing required Swarm behavior. |
| C | GPT-6.1 Sol | Existing WI-15 worktree, EO completion and restart/resume tests. |

Once a slice is ready, free/rotate a slot for an independent Astra reviewer (or Sol if Astra implemented
the slice), using the exact base/head and dirty status. Do not exceed the harness slots to recreate
the prior six-helper paging bottleneck. Reviewers read only; they must not detach or switch the
integrator checkout. The lead may continue fixtures/claims/release preparation while reviews run.

Next rotations: W2/W1 harness and proof runner; WI-09→10→11 implementation owner; WI-12 / WI-16 /
WI-18 bounded owners; shared contract/bootstrap changes sequenced. Every claim contains issue,
absolute path, branch/base, writable files, migrations, blockers, tests and evidence. Shared files
include authoring manifest/lowering and generated schemas, `deployment_composition.py`, trusted
judgment/materialization/fulfillment, KS protocol/host service, database release builders and seeds.

No fresh product-policy decision is needed to resume routine accepted work. The unresolved Biotech
native mapping and any truly contradictory contract requirement use ESCALATION; lack of a Linear
connector is a tracker-sync limitation, not an invented technical blocker. This recovery session had
no Linear connector: all live statuses/comments must be refreshed before external updates. Do not
claim those updates occurred.

## 9. Concrete W5 checkpoint and downstream boundary

Before notifying the owner at OVE-186, prepare:

1. W1–W4 criterion-by-criterion evidence and independent release signatures, with every remaining
   failure/blocked/unrun cell visible; exact source/release/install/fixture pins and spend.
2. Actual W5 manifests and frozen packs for Goal Loop, Stage Graph, Swarm, EO and nesting in both
   apps; map all eight forms and C01–C16 to tests/runs. Required unsupported rows keep release closed.
3. Selected Codex host wake procedure and the distinction between notice, transport, idle wake,
   model-visible payload, acknowledgment and exact retrieval. A webhook 2xx or queued chat is insufficient.
4. Human-gate and lifecycle controls, actual sync/async child/backend readiness, remaining OVE-203
   scope choice if relevant; reservations and observation instructions so the owner can watch.
5. A checkpoint comment, OVE-186 Blocked when available, updated NEXT-SESSION and active-chat
   notification. Wait for the answer before paid W5 execution; unpaid preparation may continue.

After an authorized W5 release, OVE-187/188 prepare real capabilities and independent mission-work
evaluation. Then OVE-189 Generation Lab exhaustive discovery/report-intents; OVE-190 Qualia Life all
current products/ingredients with KS verification and three qualifying connected studies; OVE-191
up to 50 preferably 2025–2026 models with native ingestion/readback; OVE-192 grounded retrieval/ranking;
OVE-193 repair-loop closure/product-architecture handoff. Preserve the full fixture scope and truthful
gaps. No stress phase or mission starts without its own checkpoint/rubric/budget. TruDiagnostic is a
later fixture-version decision, not silently added to Sprint OC.

## 10. Evidence provenance and known stale entry points

- Primary local record: `.scratch/sprint-oc/CLAIMS.md`; corroborating W1 evidence/budget paths in §4.
- Interrupted Claude session: `C:/Users/Pinda/.claude/projects/C--Users-Pinda-Proyectos-BellLabs/33f077fc-9d2a-4798-9bc5-d920fd382d87.jsonl`.
  Only relevant messages/reviews were read; raw transcripts are not copied into Git.
- Within its `subagents/`: `agent-a73fb842de8dea83f.jsonl` native review;
  `agent-a4b6af6694d8afc78.jsonl` Swarm review; `agent-aafcf3d344d27fc17.jsonl` MC native implementer;
  `agent-a654063ae61be4627.jsonl` KS preview; `agent-ae76688e13d4ffe1e.jsonl` Swarm;
  `agent-a57e93e99c90bb837.jsonl` EO. Use narrow retrieval if further recovery is needed.
- `HANDOFF-2026-10-28.md`, `HANDOFF-2026-10-28-S3.md` and ignored `PLAN-W1-W5.md` predate the
  latest fixes, branches, 1.9.0 install, review findings and dirty work. Retain them as dated evidence.
- Umbrella navigation still says MC main/sole checkout and BKS older pin/absent schema authority;
  live Git, scoped owner instructions and current release evidence override those dated snapshots.
- README/WORK-ITEMS/ledger preparation rows often say ready/unrun/Todo. They are not fresh status.
  This audit adds navigation without rewriting historic sprint claims or tracker state.

## Appendix: all registered worktrees

The following generated snapshot is inventory only. `+N` means committed work unique to that
worktree relative to its owner's integration branch; dirty files are additional. All paths are
BellLabs-relative. Preserve every checkout regardless of ancestry.

| Owner | Branch | Head | Unique commits | Dirty files | Checkout |
| --- | --- | --- | --- | --- | --- |
| mission-control | `sprint-oc` | `d42b04b8` | +0 | 0 | `platform/mission-control` |
| mission-control | `sprint-oc-r7` | `9dd82514` | +0 | 0 | `platform/mission-control/.claude/worktrees/agent-a2c75fa62f434123b` |
| mission-control | `sprint-oc-wi17` | `6fe90dee` | +0 | 0 | `platform/mission-control/.claude/worktrees/agent-a3d832d044b370e18` |
| mission-control | `sprint-oc-r4` | `8cc5d834` | +0 | 0 | `platform/mission-control/.claude/worktrees/agent-a3de899b4b2445111` |
| mission-control | `sprint-oc-r3` | `e66377a5` | +0 | 0 | `platform/mission-control/.claude/worktrees/agent-a60e74ba17c1601da` |
| mission-control | `sprint-oc-r2` | `54755635` | +0 | 0 | `platform/mission-control/.claude/worktrees/agent-a6616a1a5d11e614c` |
| mission-control | `sprint-oc-wi04` | `bcb93a56` | +0 | 0 | `platform/mission-control/.claude/worktrees/agent-a7c31e290b0ca3e6d` |
| mission-control | `sprint-oc-wi02` | `cf50323c` | +0 | 0 | `platform/mission-control/.claude/worktrees/agent-a8318de5079cc99bd` |
| mission-control | `sprint-oc-wi01` | `64634255` | +0 | 0 | `platform/mission-control/.claude/worktrees/agent-a908192ca9f83f3b7` |
| mission-control | `sprint-oc-r6` | `c6f383f1` | +0 | 0 | `platform/mission-control/.claude/worktrees/agent-a97ff0ff5369812b6` |
| mission-control | `sprint-oc-r1b` | `03d4fdf4` | +0 | 0 | `platform/mission-control/.claude/worktrees/agent-ac9bf95183ce2b499` |
| mission-control | `sprint-oc-w0-custody` | `79685bba` | +0 | 0 | `platform/mission-control/.claude/worktrees/w0-custody` |
| mission-control | `sprint-oc-w0-finish` | `d5f560b9` | +0 | 0 | `platform/mission-control/.claude/worktrees/w0-finish` |
| mission-control | `sprint-oc-w0-runtime` | `067fc8d6` | +0 | 0 | `platform/mission-control/.claude/worktrees/w0-runtime` |
| mission-control | `sprint-oc-w0-runtime-2` | `17e561f8` | +0 | 0 | `platform/mission-control/.claude/worktrees/w0-runtime-2` |
| mission-control | `sprint-oc-w1` | `a5fd5286` | +20 | 0 | `platform/mission-control/.claude/worktrees/w1` |
| mission-control | `sprint-oc-w1fix-a` | `fcc44811` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-a` |
| mission-control | `sprint-oc-w1fix-b` | `603a4e46` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-b` |
| mission-control | `sprint-oc-w1fix-c` | `b4519e2b` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-c` |
| mission-control | `sprint-oc-w1fix-d` | `2ef89a73` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-d` |
| mission-control | `sprint-oc-w1fix-d9` | `7e60f429` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-d9` |
| mission-control | `sprint-oc-w1fix-e` | `d5e75ed6` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-e` |
| mission-control | `sprint-oc-w1fix-f` | `24cbac27` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-f` |
| mission-control | `sprint-oc-w1fix-g` | `9c846d1f` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-g` |
| mission-control | `sprint-oc-w1fix-h` | `6897f072` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-h` |
| mission-control | `sprint-oc-w1fix-i` | `9de914a3` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-i` |
| mission-control | `sprint-oc-w1fix-j` | `13acf54c` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-j` |
| mission-control | `sprint-oc-w1fix-k` | `31d56bd3` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-k` |
| mission-control | `sprint-oc-w1fix-l` | `62a63f8f` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-l` |
| mission-control | `sprint-oc-w1fix-m` | `eb265e40` | +0 | 0 | `platform/mission-control/.claude/worktrees/w1fix-m` |
| mission-control | `sprint-oc-w1fix-n` | `5ff29ff8` | +1 | 12 | `platform/mission-control/.claude/worktrees/w1fix-n` |
| mission-control | `sprint-oc-wi03` | `ebc6be4a` | +0 | 0 | `platform/mission-control/.claude/worktrees/wi03` |
| mission-control | `sprint-oc-wi05` | `9f61dfde` | +0 | 0 | `platform/mission-control/.claude/worktrees/wi05` |
| mission-control | `sprint-oc-wi06` | `ac091cdf` | +0 | 0 | `platform/mission-control/.claude/worktrees/wi06` |
| mission-control | `sprint-oc-wi07` | `5b38283d` | +0 | 0 | `platform/mission-control/.claude/worktrees/wi07` |
| mission-control | `sprint-oc-wi08` | `9156111c` | +0 | 0 | `platform/mission-control/.claude/worktrees/wi08` |
| mission-control | `sprint-oc-wi13` | `7f7d027a` | +0 | 0 | `platform/mission-control/.claude/worktrees/wi13` |
| mission-control | `sprint-oc-wi14` | `4fa865b7` | +2 | 6 | `platform/mission-control/.claude/worktrees/wi14` |
| mission-control | `sprint-oc-wi15` | `159f38d4` | +0 | 28 | `platform/mission-control/.claude/worktrees/wi15` |
| mission-control | `sprint-oc-wi19` | `a1dd6622` | +0 | 0 | `platform/mission-control/.claude/worktrees/wi19` |
| mission-control | `sprint-oc-wi22` | `a4ec4278` | +0 | 0 | `platform/mission-control/.claude/worktrees/wi22` |
| mission-control | `sprint-oc-wi23` | `bee15793` | +0 | 0 | `platform/mission-control/.claude/worktrees/wi23` |
| knowledge-services | `sprint-oc` | `22b47d25` | +0 | 1 | `platform/knowledge-services` |
| knowledge-services | `sprint-oc-w1fix-n` | `f457e8f9` | +1 | 100 | `platform/knowledge-services/.claude/worktrees/w1fix-n` |
| knowledge-services | `sprint-oc-w0-finish` | `e4589f0b` | +0 | 0 | `platform/ks-w0-finish` |
| knowledge-services | `sprint-oc-w1fix-a` | `6446da03` | +0 | 0 | `platform/ks-w1fix-a` |
| knowledge-services | `sprint-oc-w1fix-e` | `d82c9198` | +0 | 0 | `platform/ks-w1fix-e` |
| knowledge-services | `sprint-oc-w1fix-i` | `daa8970e` | +0 | 0 | `platform/ks-w1fix-i` |
| knowledge-services | `sprint-oc-wi05` | `740df8c1` | +0 | 0 | `platform/ks-wi05` |
| knowledge-services | `sprint-oc-wi06` | `fc2b63c3` | +0 | 0 | `platform/ks-wi06` |
| ai-engineer-db-contract | `sprint-oc` | `74fd2c3e` | +0 | 0 | `aiengineer/ai-engineer-db-contract` |
| ai-engineer-db-contract | `sprint-oc-w1fix-b` | `edba7bf6` | +0 | 0 | `aiengineer/aidb-w1fix-b` |
| ai-engineer-db-contract | `sprint-oc-w1fix-g` | `b2cfff0a` | +0 | 0 | `aiengineer/aidb-w1fix-g` |
| ai-engineer-db-contract | `sprint-oc-w1fix-i` | `0e020097` | +0 | 0 | `aiengineer/aidb-w1fix-i` |
| biotech-knowledge-services | `sprint-oc` | `8e8d3d1e` | +0 | 0 | `biotech/biotech-knowledge-services` |
| biotech-knowledge-services | `sprint-oc-component-grants` | `9902ea7f` | +0 | 0 | `biotech/bks-component-grants` |
| biotech-knowledge-services | `sprint-oc-w1fix-b` | `1ee16558` | +0 | 0 | `biotech/bks-w1fix-b` |
| biotech-knowledge-services | `sprint-oc-w1fix-g` | `e23af2d2` | +0 | 0 | `biotech/bks-w1fix-g` |
| biotech-knowledge-services | `sprint-oc-w1fix-i` | `4e7573a6` | +0 | 0 | `biotech/bks-w1fix-i` |
