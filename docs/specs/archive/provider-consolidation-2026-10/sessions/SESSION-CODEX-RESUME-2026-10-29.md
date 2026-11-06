---
type: Session Instruction
title: "Codex resume: service-specific discovery, capture and report partial fixture"
description: "Current bounded local fixture assignment and setup instructions, followed by retained historical recovery authorizations."
date: 2026-10-29
status: archived
archived: 2026-11-02
archived_from: sprint-oc/SESSION-CODEX-RESUME-2026-10-29.md
archived_reason: "done (SE-15)"
---

> **Archived 2026-11-02** (done (SE-15)). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Instruction for the next Codex session

**Superseded entrypoint:** the owner expanded the assignment to functional workflows and a larger
repair allowance. Start the [overnight Astra/Sol workflow instructions](SESSION-OVERNIGHT-WORKFLOWS-2026-10-29.md).
The service-specific block below remains Phase 0 reference; its stop-at-submission and missing-code
pause do not restrict the later workflow phases authorized in the current overnight assignment.

## Retained Phase 0 reference: service-specific search/capture/report partial fixture

Owner steering after the foundation implementation: concentrate on service-specific partial
fixtures; put Tavily/Firecrawl and KS procedure skills into the sandbox; use a report-specific
schema projection with optional entity navigation and extra direction even if a full workspace
is available. This is deliberately guided, without supplying answers or verification verdicts.
This retained service-only assignment supplies Phase 0 detail; the overnight assignment above governs:

```text
Continue BellLabs Sprint OC's service-specific search → capture → report partial fixture.
Workspace: C:/Users/Pinda/Proyectos/BellLabs. Read applicable AGENTS.md and NEXT-SESSION.md,
especially "Service-specific fixture setup (2026-10-29)", then docs/REPORT_SOURCE_FOUNDATION.md
in platform/mission-control. Inspect live HEAD/status/worktrees; preserve dirty and ignored work.
Use existing sprint-oc primary checkouts. Do not repeat completed foundation integration.

Goal: AI Engineer only, two primary model sources, one named property (parameter count),
two-to-four producer-authored claims; stop at recorded report submission. No native entities,
publication, independent acceptance, consumer stage or full Temporal mission in this partial run.

First reproduce the sandbox preparation from platform/mission-control using fresh directories:
.venv/Scripts/python.exe scripts/report_source_context.py --profile ai-engineer --out .scratch/source-partial-context-<fresh>
.venv/Scripts/python.exe scripts/report_source_sandbox.py --context .scratch/source-partial-context-<fresh> --out .scratch/source-partial-sandbox-<fresh>
.venv/Scripts/python.exe scripts/report_source_sandbox.py --verify --out .scratch/source-partial-sandbox-<fresh>
.venv/Scripts/python.exe -m pytest -q --override-ini addopts= tests/unit/test_report_source_sandbox.py tests/integration/deep_agents/test_report_source_sandbox.py

Mount every prepared sandbox/skills/<name> directory as an exact ResolvedSkillBundle through the
existing Deep Agents materializer, preserving every relative reference file. The integration test
is executable wiring evidence. Merely copying files to scratch or listing skill names is not
runtime attachment. The bundle includes START_HERE, SCHEMA_ROUTE and partial-fixture.json under
/skills/report-source-procedure/references; use its entrypoint. Skills do not install binaries,
connect MCP servers or admit tools. Provider snapshots are transcribed historical evidence only.

Use the package's preselected domain/question/schema route/budgets; let the producer choose queries,
selection reasons, quotes, assertions, support sets, caveats and prose. Read only necessary contract
files. Optional entity cards are read-only navigation; never invent entity IDs or require ingestion.
Missing domain references require targeted canonical search/get, not a full-schema prompt.

Preflight the actual KS routes before starting the chain. Read data-plane guidance before any DB
or credential work. Prefer verified loopback disposable PostgreSQL and disposable local artifact
storage. Record endpoint/installation identities and live tool/schema digests without secrets.
Read KS skills/knowledge-acquisition-and-vetting/SKILL.md and executor knowledge-verify skill:
executor managed source discovery and platform candidate ranking are different operations.
Use ONE route: default host-managed KS discovery; alternatively direct admitted Tavily/Firecrawl
tools + a self-reported KS import. Never label the latter a managed dispatch. Do not wrap new
provider search tools inside KS MCP. Both provider skills are available; neither tool is assumed.

Run service fixtures in bounded order, saving explicit pass/fail/blocked/unrun evidence:
1. One scripted provider response, persisted discovery attempt and selected/omitted receipts;
   prove same-call retry does not dispatch again. Zero paid search/model calls.
2. Two fixed source documents served over local HTTP; capture through the existing KS acquisition
   path, read exact bytes, locate quotes, preserve provenance/digests. Reconstruct the service and
   read the captured bytes again. Missing storage is a blocker, not a skipped pass.
3. Prove capture/locator receipts can become exact K01 fragment references and their bytes can be
   read under the bound tenant. Inspect the existing custody/adapter boundary first. Do not bypass
   it with manually minted handles, fake custody, snippets or copied bytes under a new identity.
4. Scripted Deep Agents producer uses the real report_register and submit_output tools in one MC
   invocation. Preserve the full receipt chain and typed refusals. Check wrong/missing capture
   references fail and registration/submission retries create no duplicate effects.

Existing source routes: KS apps/verification-executor/src/knowledge/source-discovery.integration.test.ts,
knowledge/operations.ts, knowledge/context.ts, skills/knowledge-acquisition-and-vetting and
apps/verification-executor/skills/knowledge-verify. K01: packages/host/src/knowledge-operation/service.ts.
MC: tests/integration/deep_agents/test_report_source_real_service.py is the proven registration/
submission seam; do not mistake its prebuilt evidence for discovery/capture proof. Build KS protocol
before host to avoid stale runtime exports. Use one heavy build/test/database job at a time.

The owner has approved setup/code work and bounded local partial fixtures, including disposable
local storage and narrowly necessary integration fixes. No paid provider calls, remote installation,
push or unrelated cleanup. If a larger missing capture-to-K01 contract appears, stop at that edge
and present the concrete refusal, source ownership and proposed repair rather than silently
expanding architecture or authority. Prior authorization permits up to two bounded Astra helpers.

Finish with exact tested source pins, local commits after review/checks, a receipt/proof matrix,
and NEXT-SESSION updated in place. Keep private logs in ignored scratch. Distinguish setup, real
local service proof, scripted cognition and unrun live qualification. W1/W2 stay unreleased;
native application and full workflow recovery remain later work. Leave exact next instructions.
```

## Earlier assignment: foundation detour

Earlier owner steering (2026-10-29) put submission-tool enhancement and selective report/source
workspaces before the retained native-application proof. This block is historical; use the current
service-specific assignment above. Its implementation results are now recorded in NEXT-SESSION.

```text
Continue BellLabs Sprint OC from:
C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control/docs/specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md

Read its "Next-session foundation detour (2026-10-29)" section first, after applicable AGENTS.md.
Our nearest goal is complete workflow and agent configuration with Deep Agents as the principal
provider, common contracts provider-neutral and provider adaptation in deep modules. Center all
reports on the remaining outcome, what your work closes and the next unmet proof.

Complete the requested detour before returning to the already approved service-level native proof:
1. Enhance submit_output and its agent-facing workflow: actionable structured findings/refusals,
   pinned obligation discovery, truthful submission/acceptance/fulfillment status, progressive/final
   submission and safe revision handling where supported. Reuse existing services; preserve host
   authority, exact digests, tool-call idempotency, actor isolation and independent verification.
2. Reuse AI Engineer scope materialization and Biotech schema slicing to deliver a small, versioned,
   digest-verifiable report/source context. Include shared KS evidence/report contracts and necessary
   domain guidance. Do not copy/edit full schemas, optimize domain schemas or require native writes.
3. Build the bounded report/source foundation fixture: domain mission, admitted search/acquisition,
   captured evidence, producer-authored report, independent verification, failed-claim repair,
   exact accepted-revision transfer to a consumer and restart/redelivery checks. Start AI Engineer,
   then the same shape for Biotech. Use existing GoalDirected and StageGraph paths without assuming
   nested/linked workflows are implemented. Keep scripted/local proof and live qualification distinct.

Use the board's concrete source routes, work packages and acceptance criteria. Inspect live source
before designing changes; resolve existing issue coverage and record a short implementation plan.
Perform necessary local implementation, focused tests, independent review and verified integration
for this requested outcome. Do not repeat completed B4b/B4c recovery or request the same scope again.
Paid model/search runs, remote operations, push and unrelated cleanup remain separately controlled;
prepare a concrete target/budget packet if live qualification is needed. Preserve pending native
review/ingestion proofs and all W1/W2 gates rather than counting this narrower fixture as their release.

Reuse sprint-oc primary checkouts; inspect Git status/HEAD/worktrees and preserve dirty/ignored work.
Search only relevant source/test directories; do not scan all branches, scratch, outputs or schema IR.
Read data-plane guidance before database work. Use at most two previously authorized GPT-6 Astra
subagents for bounded implementation/review if helpful, with one heavy build/test/database job at a
time. The preparation's GPT-6.1 Sol research findings are already folded into the board; do not repeat
the discovery sweep. Do not create a new user chat.

Finish by recording implemented, tested, integrated and unqualified behavior separately, updating
NEXT-SESSION in place, and identifying precisely what remains before returning to report→review→
native application→consumer proof. Do not silently replace missing real-service evidence with mocks.
```

## Historical controlled assignment and retained authorization

The previous instruction selected GPT-6 Astra as lead. It replaced the earlier version's autonomous
W1–W4 assignment. The owner explicitly selected **“Approve each integration batch”** on 2026-10-29.
The approval requirement comes directly from the owner; it is not an inferred tooling restriction.

## Later owner authorization (2026-10-29)

After B4b/B4c integration, the owner approved the next recommendation (now queued after the detour): complete service-level
report→review→native application→consumer proof, and requested a new-chat handoff. Read the
[approved next-session scope](../docs/SPRINT-OC-LOG-2026-10-29-31.md#approved-next-session-scope-2026-10-29) before the
historical assignment below. Necessary local implementation, tests, independent review and
verified integration/commits for that outcome are authorized; do not re-request the same approval.
Paid calls, remote operations, push, cleanup and unrelated scope remain separate. The owner permits
up to two GPT-6 Astra subagents. B3/B4 source integration is complete; do not repeat the old queue.

OC-D206/207 supersede only the matching cleanup/source-custody limits in the baseline assignment
below. The owner authorized full recoverable consolidation from 58 registered checkouts to four
canonical primaries, including retiring the five unfinished physical checkouts after verified
source/evidence preservation. Original/recovery refs, branches, bundles and ignored material remain
recoverable. The nine W1 harness/fixture/evidence files have been selectively recovered into primary
with offline checks and independent source review passed. Full consolidation is verified complete:
58 to four primary registrations on `sprint-oc`; all 54 original nonprimary checkout paths are absent.
Recovery refs, branches, four verified bundles, five verified source ZIPs and 6,254 ignored objects
(including 11 link objects) remain preserved. Resume paired MC/KS native-write review.
Native/Swarm/EO recovery commits remain unreviewed and unintegrated. Runtime qualification, paid
fixtures, remote operations and branch deletion are not authorized by this cleanup direction.
Read [NEXT-SESSION](../../../provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md) for exact recovery homes, completed custody checks and the next
review batch.

```text
Act as the BellLabs Sprint OC recovery and integration lead. Help me consolidate existing work,
preserve unfinished functionality, retire proven-redundant temporary material and restore a clear
path to qualification. I approve EACH integration batch. Prepare concrete patches, focused checks,
independent review and rollback information before requesting approval. Wait for my response before
applying that batch to the sprint integration branch. Silence, elapsed time or an earlier broad
sprint authorization is not approval. A changed scope or patch needs renewed approval.

Workspace: C:/Users/Pinda/Proyectos/BellLabs
Primary owner: platform/mission-control
Companions: platform/knowledge-services, aiengineer/ai-engineer-db-contract,
biotech/biotech-knowledge-services
Packet: platform/mission-control/docs/specs/provider-consolidation-2026-10/sprint-oc/

Read applicable AGENTS.md, NEXT-SESSION.md and this instruction. Retrieve only the relevant sections
of RECOVERY-AUDIT-2026-10-29.md, source, contracts and tests for the current batch. Do not restart
from main or repeat R0/WI-01. Do not read the whole historical packet or all worktrees by default.
Older execution plans remain evidence, not permission to continue autonomously.

Team: you may use gpt-6-astra and gpt-6.1-sol subagents within this chat. Use Astra for integration
and difficult architecture/recovery decisions; Sol for a bounded repair/check. Normally use the lead
plus one worker, then an independent reviewer who did not implement the change. At most three agents
active, only one heavy test/build/database job at a time. Do not create separate chats. Do not spawn
workers before identifying a concrete bounded task. Provide exact checkout/base, writable paths,
contract excerpts, acceptance criteria and test commands; avoid full-history forks. These coding
model choices do not change mission runtime model pins.

Start with a read-only refresh of the four owners' HEADs/status, worktree registrations and the five
unfinished checkouts on NEXT-SESSION. Check who is still writing before adopting a checkout.
Compare live files with the ignored recovery inventory; preserve new differences as well. There
were 59 worktrees: four primary, five unfinished, 50 clean/ancestor candidates. Do not reclassify
them by name or age. Swarm/native reviews were CHANGES REQUIRED; EO is entirely uncommitted.
A branch-only merge cannot recover EO. Existing source ZIPs do not cover all ignored material.

FIRST CHECKPOINT — architecture and scope:
Prepare a compact evidence-backed comparison of the shared transfer mechanism, Swarm and EO.
For each show: accepted text, directly recorded owner answer, implementation choice, current source
and proof gaps. Separate labels in inherited specs from demonstrable owner answers. Explain who
receives which candidate/output/feedback, selection and timing, isolation, authority, durable
identity and restart behavior. Include a small concrete transfer example for each family.
Show whether current code conforms, needs repair, or contains a choice requiring my decision.
Ask me to retain, revise or defer the specific disputed choices; do not ask me to reapprove the
entire codebase. Do not finish Swarm/EO architecture or implement new disputed behavior before this
checkpoint. A deferral preserves source and leaves the relevant qualification gate unmet.
Update the control board with my actual answer. Preparation for unrelated batches may continue.

Then follow the proposed batch queue below, adjusting dependencies from actual evidence. One batch
is one coherent concern and a concrete frozen change set, not "finish Sprint OC." Prepare it fully
before approval. Use existing suitable checkouts; create a new one only when isolation is necessary
and existing ones are unsuitable. Do not reset, clean, stash, switch or detach another checkout.
Keep snapshots before editing interrupted work. Only stage named files; never bulk-add KS .claude/
or generated CRLF churn. Shared schema/authoring/release files have one writer.

For each batch record in the existing control board (brief summary plus local evidence link):
- ID, issue/scope, exact repositories/checkouts, base HEADs, proposed commits/patch hashes and paths.
- Behavior gained; intentionally deferred behavior; contract decision and prerequisites.
- Actual checks at exact pins: passed, failed, blocked and unrun; independent review and findings.
- Cleanup side effects, rollback/recovery method and any release/schema implications.
- My approval of that exact batch, execution result and resulting HEADs.
Keep private receipts, secrets and bulky logs in ignored scratch; source/status summaries may be
tracked. Approval summaries should normally fit 300 words, worker returns 500 words plus paths.
At two unsuccessful repair/review cycles, report the cause and propose a smaller scope rather than
burning tokens indefinitely. Do not hide a failed acceptance criterion as an unrelated baseline.

Approval authorizes only the listed local integrations/cleanup actions. Recheck bases, dirty files
and writer ownership immediately before applying. Any drift invalidates affected evidence and
requires re-review. Stop if the integrated result fails its checks; do not stack another feature
on it. Record recovery before proceeding. Prepare remote push separately with the exact commit
range and validation, because MC already has unverified local runtime commits ahead of origin.
No automatic session-end push of that range. No paid fixtures, remote installation, credential
changes, live migrations or database/volume deletion in this recovery assignment. If any becomes
necessary, present the concrete dependency as a separate proposal and wait.

Cleanup also requires my approval per exact batch. For every candidate verify resolved absolute
path, Git ownership/registration, no active writer, branch/HEAD and reachability, staged/unstaged/
untracked contents, and ignored-file disposition. Do not print credentials. Preserve unique
receipts, config and evidence in restricted local archives outside the candidate; record hashes
and verify restore. Disposable caches must be identified, not assumed from an ignored flag.
Preserve recoverable commit refs and needed LFS/submodule material where applicable.
Use the owner repository's normal git worktree remove for approved native Git checkouts; no force,
recursive blanket deletion or prune as a substitute for investigation. If removal refuses, stop
and explain the preserved contents. Managed Codex worktrees use the app's recoverable archive flow.
Branch deletion is a separate explicit action after reachability/recovery checks. Keep the five
unfinished checkouts until their source and evidence have an approved integrated or deferred home.
Never wipe .scratch: it holds W1 receipts and source recovery. Do not delete unknown PIDs or volumes.

Validation: inspect current test wrappers; timeout/nonzero pytest exits must propagate, not be
masked by a final grep. Run focused meaningful tests for each changed behavior and affected owner
lint/types/contracts. Run real local PostgreSQL/Temporal checks where the claim requires them;
doubled tests cannot qualify real execution. Run a combined regression once coherent approved
batches are integrated, and repeat only for changes/failures that warrant it. Record exact baseline
failures by test and cause, not "36 failures allowed." No source mutation under a running stack.
Use at most one heavy job; retain recorded memory constraints from audit §7 and maxWorkers=2.
Before database/env work, read BellLabs docs/navigation/DATA-PLANES-AND-CREDENTIALS.md.
Published MC 1.9.0, KS 2.5.0 and existing seeds stay immutable. Migration reservations 0068–0071
must be reconciled against live source before packaging; deferring a feature does not license
renumbering a published migration or silently omitting a required release dependency.

Maintain NEXT-SESSION as the single current control board. Keep only the current batch's compact
working packet in ignored scratch; use the existing audit for historical details. After compaction,
read the board and current batch, check Git, and continue. Do not reproduce the entire handoff.
Record newly accepted architecture in its established canonical/decision surfaces with provenance;
a working task plan does not rewrite a contract. Do not update issue completion without evidence;
if Linear is unavailable, record a sync queue rather than claim it was updated.

Finish this recovery run when every unfinished slice has a reviewed integrated or explicitly
deferred disposition, approved cleanup is verified recoverable, current source/checks/releases
have a truthful status, and documentation routes to the actual next action. Report retained
worktrees with reasons; do not chase a numeric target by deleting uncertain material.
Deliver a compact proposed W1 qualification batch and remaining W1→W5 dependencies. WAIT for my
next instruction. W0 is recorded released; W1 remains unreleased until its actual criteria pass.
Later W5/OVE-186 and stress checkpoints remain; this run does not bypass or execute them.
```

## Proposed batch queue

These are candidate scopes, not approvals. Architecture review is first; simple custody/navigation
preparation can proceed while disputed family choices wait. Native repairs precede final native
harness integration. Swarm/EO can be deferred without pretending the four-family destination is met.

| Batch | Concrete outcome and evidence |
| --- | --- |
| B1a — retrieval | Small current-state route, stale-entry corrections and a bounded sprint index/search remedy. Demonstrate three questions find the right owner/current state/contract. |
| B1b — test-result reliability | Repair masked test exits and demonstrate success/failure/timeout propagation before using the wrappers as integration evidence. Separate approval from B1a. |
| B2 — first cleanup tranche | Start with a small set of proven redundant checkouts in one repository; present exact path/HEAD/ignored-file/recovery manifest. Verify archive and restoration before removal. Expand only through another approved tranche. |
| B3 — MC + KS native write | Recover the paired changes-required review (audit §3.1): stale-plan redecision, per-decision refusal, already-applied recovery, effect receipt, run identity, decide-before-record crash, preview parity. Review both repositories as one dependency batch; report partial-apply rollback. |
| B4 — W1 harness and existing integrated regressions | Adapt the five fixtures/driver to the approved native behavior. Validate D27–D30 regressions and harness locally; no model spending. Preserve explicit Biotech native mapping/applicability blocker, not an invented mapping or waived test. |
| B5 — Swarm, conditional | After architecture disposition, repair busy loop, retry budgets, refused activation cleanup, settlement/lineage and required Temporal coverage (audit §3.2); explicitly identify remaining fan-out/governor/nesting gaps. |
| B6 — EO, conditional | Preserve dirty/untracked implementation; reconcile round identity, producer/evaluator transfer and restart/resume against approved decisions. Independent review plus relevant persistence/Temporal checks (audit §3.3). |
| B7 — consolidation and remaining cleanup | Reconcile combined migrations/schema/seeds, run justified combined checks, prepare release readiness without installation. Archive approved superseded checkouts/evidence; remove stale navigation through the established doc lifecycle. Produce the next qualification proposal. |

## Architecture evidence to start from

The common [output/context contract](../../../../knowledge/output-contracts.md)
is intended to serve different workflow shapes. Reuse of that mechanism does not specify selection,
timing or isolation for each family, and current runtime proof is incomplete.

| Evidence | What it establishes; what remains to clarify |
| --- | --- |
| [OC-D43 and OC-D72 owner answers](../answer-sets/gpt-6-astra-2026-10-24/ANSWERS.md) | Declared evidence/provenance across shapes; authored alternatives with settlement accountability. These do not establish review of every Swarm/EO implementation choice. |
| [OC-D128 owner answer](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md) | Progressive real fixture qualification with routine use still gated. It does not replace architecture provenance. This recovery instruction narrows execution authorization. |
| [Swarm contract §§3–6](../../../../knowledge/parallel-swarm.md) | Inherited text labelled accepted 2026-09-07: immutable shared inputs, peer isolation, selected accepted outputs into Convergence and explicit completion/settlement policies. Verify provenance and concrete code conformance. |
| [EO contract §§3–7](../../../../knowledge/evaluator-optimizer.md) | Inherited text labelled accepted 2026-09-07: typed candidate/findings/rubric, distinct producer/evaluator identities and sessions, fresh round activation. Clarify the current reuse of GoalDirected and actual receiving-context boundaries. |

A useful review example is two Swarm members receiving the same declared input while Convergence
receives only selected accepted outputs with lineage; for EO, the next producer receives explicitly
selected prior candidate/feedback while the evaluator receives the exact candidate, rubric and
permitted evidence in an independent session. These illustrate inherited requirements, not proof
that the interrupted implementation satisfies them or a new owner decision.

## Known retrieval defects and completion limits

On 2026-10-29 the default search for “sprint oc current resume interrupted worktrees” returned
ADR-0037, the knowledge index and collections, whereas explicit sprint-root search returned the
three recovery documents. Default search excludes `docs/specs`. The compressed index generator's
nonrecursive groups omit `sprint-oc`, even though `index-notes.toml` contains a stale note for it.
A passing docs check therefore did not establish discoverability. B1 should fix the narrow routing
gap and measure useful retrieval; adding the whole historical corpus or a new retrieval platform
would expand this recovery task unnecessarily.

The index generator also uses repository-wide `rglob("AGENTS.md")` before filtering hidden and
dependency paths. B1a should inspect traversal cost and prune excluded directories before descent
if confirmed material; filtering results does not prevent walking retained worktrees and caches.

The source audit remains the detailed backlog. WI-09→10→11/W3, WI-12/16/18/W4 and full nesting,
attention, reactions and async-child qualification are future work unless separately approved.
Cleanup and integration are not fixture qualification. No deletion, merge, paid run or architecture
approval is claimed by publishing this instruction.
