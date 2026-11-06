---
type: Handoff
title: "Sprint OC log 2026-10-29..31: the control board before the 2026-11-01 split"
description: "The full text of the Sprint OC control board as it stood on 2026-11-01 before the live board was cut to its checkpoint: dated owner steering, the overnight StageGraph and GoalDirected runs, the foundation detour, the OC-D206/D207 consolidation, and the B3-B4c batch records. Evidence by section; the live board is NEXT-SESSION."
date: 2026-10-29
status: archived
archived: 2026-11-02
archived_from: sprint-oc/SPRINT-OC-LOG-2026-10-29-31.md
archived_reason: "dated batch log cut from the Sprint OC control board on 2026-11-01; the live board is NEXT-SESSION"
---

> **Archived 2026-11-02** (dated batch log cut from the Sprint OC control board on 2026-11-01; the live board is NEXT-SESSION). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Sprint OC log 2026-10-29..31 (the board before the split)

The live board is [NEXT-SESSION](../../../provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md). This file is the dated record it was cut from.

**Agentic SDLC program opened 2026-11-01 (owner interview, AS-D1..D20):** the documentation and
lifecycle system is specified in [SPEC-01](../../../agentic-sdlc-2026-11/SPEC-01-AGENTIC-SDLC.md)
(ledger [here](../../../agentic-sdlc-2026-11/LEDGER.md), Linear project Agentic SDLC, parent OVE-205).
The owner's next session is [SESSION-NAVIGATION-QUALITY](../../../agentic-sdlc-2026-11/SESSION-NAVIGATION-QUALITY.md)
before any implementation; Sprint OC work resumes after that program merges. Qualification status unchanged.

**Latest sequencing clarification, 2026-10-31:** we may run W0/W1 work and generally refine
Mission Control locally before cloud coding-environment setup. The owner will make the next
session's instructions explicit; the order below is provisional. Qualification status is unchanged.

**Current owner direction, 2026-10-31:** cloud coding environments for Cursor, Claude Code and
Codex across MC/KS first (CloudRoom is a candidate), then Deep Agents/Agent Server/Temporal
deployment architecture and owner education. Continue the W0/W1 checkpoint, followed by a likely
remote-readiness coding sprint and the first major local-and-cloud deployment. W0 is already
recorded released; W1 remains open. The
[companion deployment roadmap](../../../provider-consolidation-2026-10/sprint-oc/CLOUD-ENVIRONMENTS-AND-DEEP-AGENTS-DEPLOYMENT-2026-10-31.md)
records sequence, service candidates, local/remote adapter choices, sandbox/state-transfer
requirements and proof deliverables. This board remains the implementation/qualification checkpoint.
Biotech entity/process and source/capability optimization is deferred to a dedicated effort.
No infrastructure choice, provisioning, deployment or gate release follows from this planning update.

**Completed AI Engineer fixtures and Selection Workspace, 2026-10-31:** the owner asked for AI
Engineer fixtures on frontier-model / agent-orchestration sources (GitHub, arXiv, Context7,
Firecrawl) and for Mission Control search/workspace support for harness and capability choice.
USD 60 and the Qualia model pins were authorized; USD 40.94 is accounted. Source-02 + fork-01
and source-04 + its Tavily fork pass the full engineering gates. Each passing run has seven Deep
Agents stages, a frameworks/literature coverage join and exact transfers. It also has applied
queued and interrupt/inject controls and independent KS verification with real repair. Each
ends with an admitted exact-use `knowledge.apply` into the disposable AI Engineer database, with
complete readback. The last fork wrote a paper, a repository, a technique and three
relationships, with 17/17 rows read back. Never the AI Engineer graph. Evidence:
`.scratch/aieng-stagegraph-2026-10-31/READ-FIRST.md` and `INDEX.md`; driver
`scripts/aieng_stagegraph.py`. KS host: `aieng-fixture-host.ts`, KS `3e3d8a7`/`8a38b0f`.
Exposed gaps:
- `plan_preview` admits subjects missing NOT NULL typed columns (the fixture now preflights).
- There is no production MC→AIDB producer-attempt projection (fixture-derived attribution).
- Judges see capture titles, not URLs, so the fixture now names commit and version there.

The merged **Selection Workspace** (`missionctl search`, `missionctl workspace check`, MCP
`mission_search`/`selection_check`, `POST …/selection/search|check`) composes capability search,
lanes, models, sandbox profiles and Workflow Types with read-only admission checks. Its
21 unit tests and 166 adjacent tests pass; it has not run against a live catalog. **Owner
decision:** moving its guidance into `skills/mission-control*` requires an agent-skills seed
1.0.4, because 1.0.3 is the released W0 seed. W1/W2 remain unqualified. **Open (2026-11-01):**
agent-skills 1.0.4 has since been built for the knowledge charters (provenance slice 6) without
this guidance (no `mission_search`/`selection_check` in `skills/`); whether the guidance joins
1.0.4 before it is published or waits for 1.0.5 is undecided.

**Completed owner steering, 2026-10-30:** concentrate on real Deep Agents StageGraph fixtures using
Qualia Life supplements, a partial Biotech schema, Firecrawl/Vercel agent-browser, shared Knowledge
Services evidence assertions and ingestion. Exercise branch/coverage joins, exact context/output
contracts, a live queued instruction, actual disruption/context injection, and a recorded-point fork
with added instructions and Tavily skill/tools. GPT-6.1 Sol/Terra and up to USD 100 total are explicitly
authorized, as are bounded writes to registered Biotech Aura `8032ec07`; separate graph enumeration
preflights are unnecessary. This assignment supersedes the earlier OpenAI API design priority and
older paid-fixture limits. It does not release W1/W2. Live evidence remains private under
`.scratch/qualia-stagegraph-2026-10-30/`; start with its `READ-FIRST.md` and `INDEX.md`.

**Completed bounded Qualia assignment, 2026-10-31:** source08/source09 and retained-source09
Tavily fork05 pass the full engineering gates. The seven-stage Deep Agents graph executes parallel
formulation/study branches, a two-member coverage join, exact accepted-revision transfers, schema
output obligations, independent KS claim verification with actual repair, native admission and
acknowledged Biotech Aura ingestion. Source09 has 21 fully supported claims and 146/146 verified
effects; fork05 has 24 fully supported claims and 165/165 verified effects, both with zero readback
failures. Effects include reused entities and repeated create/update operations, not just new nodes.
Both cover two Products, four distinct chemical/material subjects, a company, a public author and
snapshots of both product pages/all three studies. Native VETTING Assessments remain PROPOSED.

Source controls prove a queued instruction consumed in the active stage session and an actual
interruption/replacement with injected context, including applied receipts and digest-verified
model-visible directives. Fork05 seeds the exact retained studies checkpoint, preserves historical
messages and adds its directive, materializes Tavily-only research capabilities, executes fresh
stages and leaves the prepared template unstarted. The protected Workflow Type remains unchanged.
Failed attempts remain intact, including fork04's correct refusal of an unevaluated browser capture.
The final agent repaired claim-screening/qualified-support findings and a missing Organization field
through ordinary feedback before admission; no gate was bypassed to make the run pass.

The resulting repairs cover finite Deep Agents network grants, named-output settlement, schema-only
input gates, concurrent stage authority, producer-scoped effect liability, bounded queued turns,
trusted manifest fork provenance and explicit capture/assessment feedback. Final changed-unit checks
pass 427 tests; relevant real PostgreSQL/Temporal integration, scoped types, lint and dependency
checks pass. KS fixture checks pass 56 tests and BKS projection checks 18; overlapping selections are
not summed. Broad legacy test/type failures remain documented and are not presented as green CI.

The USD100 fixture ceiling is enforced by shared append-only ledgers, including retained unknown
call reservations. No remote deployment, schema migration or AI Engineer graph write occurred.
KS uses separate authenticated standalone producer/judge/auditor roles; the native Activity carries
the actual StageGraph run/operation. This does not qualify the production per-invocation Biotech
authority mapping. The next proof is the separately governed W1 packet against coordinated builds;
W1/W2 remain unqualified/unreleased. Preserve the companion KS/BKS fixture changes and private runtime
custody; do not rerun paid work merely to regenerate reports.

**Earlier owner steering, 2026-10-29 (OC-D208):** make Deep Agents workflows functional quickly
through small partial fixtures, with more repair latitude and Astra/Sol delegation. Start at the
[current overnight direction](#current-overnight-execution-direction-2026-10-29). Local implementation,
review, fixture work and verified integration proceed without the older per-batch approval pause.
The executing owner's subsequent instruction authorizes up to USD 10 per OpenAI/Anthropic fixture,
superseding lower/no-model-spend limits for this assignment. Scripted local fixtures remain first.
Remote operations and push remain separately controlled. Preserve actual proof gates.

Read the [overnight session instruction](../sessions/SESSION-OVERNIGHT-WORKFLOWS-2026-10-29.md). It defines
team roles, sequential gates, parallel tasks, repair policy and completion. Prior recovery
authorization remains historical evidence; it does not narrow the new local workflow assignment.
The [dated audit](RECOVERY-AUDIT-2026-10-29.md)
is evidence to retrieve by section, not mandatory reading in full on every restart.

## State and authority

The W1–W5 qualification state below is separate from the bounded overnight engineering fixtures.
Their current runtime evidence and local integration status are recorded in the overnight section.

W0 is recorded released; **W1 is not released**. The last AIE run reached independent evaluation,
seal, decision, separate review and promotion, then failed fulfillment. D27–D30 fixes are locally
integrated; complete regression and real rerun remain. Biotech W1 has not run; W2–W4 are unqualified.
No new runtime, database or Linear qualification occurred in this documentation recovery.

The broader destination remains W1→W4→the W5 owner checkpoint (OVE-186), with later stress waits.
The earlier cleanup-only stopping point is historical. The current overnight assignment implements
and proves the specified workflows locally; paid fixtures and remote installs remain separate.

## Source custody

Paths are relative to BellLabs. All four primary owners use `sprint-oc`; recheck live Git.
MC primary was `6ac58287` when this consolidation began; companion observations were
KS `22b47d2`, AIDB `74fd2c3`, BKS `8e8d3d1`. These are dated observations, not checkout commands.

| Retained source home | Original head | Recovery head / disposition |
| --- | --- | --- |
| MC `sprint-oc-w1` | `a5fd5286` | Same head; nine harness/fixture/evidence files recovered selectively into primary; independent source review passed |
| MC `sprint-oc-w1fix-n` | `5ff29ff8` + 12 dirty/untracked paths | `5d0923c8`; native-write repair preserved, unreviewed and unintegrated |
| KS `sprint-oc-w1fix-n` | `f457e8f` + 100 dirty paths | `e3c75b97`; companion native preview/tests and generated snapshot preserved, unreviewed and unintegrated |
| MC `sprint-oc-wi14` | `4fa865b7` + 6 dirty paths | `6c558096`; Swarm repair preserved, unreviewed and unintegrated |
| MC `sprint-oc-wi15` | `159f38d4` + 28 dirty/untracked paths | `0c14071a`; EO implementation preserved, unreviewed and unintegrated |

The OC-D207 starting inventory is **58 registered checkouts: four primary, 49 clean/ancestor
nonprimary candidates and five unfinished source homes**. The authorized destination is the four
canonical primary checkouts. **Consolidation is verified complete: 58 to four**, all four on
`sprint-oc`. Ordinary removal retired all 54 nonprimary registrations and their physical checkout
paths; retained branches and recovery refs preserve their source homes. **2026-11-01:** the
four-checkout state no longer holds for MC: a fifth registration,
`.claude/worktrees/agent-a3ad8c12b136e094c` on `sprint-oc-selection-workspace` (already merged by
`79525ed4`), was created after consolidation and is retained, not removed by this note.

Branches and `refs/recovery/oc-20261029/*-original` retain the original and recovery source homes.
Per-owner `.scratch/worktree-consolidation-2026-10-29/<branch>/` holds dirty-source ZIPs,
source manifests and restoration copies; `<branch>-checkout/` holds ignored-object custody manifests,
journals and preserved dependencies/evidence. The control inventory, per-owner bundle index and
five-source disposition are in MC `.scratch/sprint-oc/worktree-consolidation-2026-10-29/`.
Independent source-custody checks passed for the five ZIP digests, all 146 archived source-file
hashes against restoration copies, and original/recovery refs. This verifies preservation, not code
correctness. Completed ignored-object and quiescence checks preceded ordinary checkout removal; final
verification is recorded in `final-verification.json` in the MC control directory above.

No generated changes were normalized by the source-preservation step. Exclude the 98 KS generated
contract changes from the future native-write integration; their original bytes remain preserved.
Never add KS `.claude/` or private recovery receipts to Git.

## Retrieve only what the current batch needs

Read applicable workspace/domain/repository/scoped instructions. Before DB/env work, read BellLabs
`docs/navigation/DATA-PLANES-AND-CREDENTIALS.md`. Then read this board and the task instruction.
Select from the audit: §2 custody, §3 interrupted reviews, §4 W1 evidence, §5 remaining scope,
§6 releases/budget, §7 tests, appendix exact paths. Consult the relevant canonical contract and
actual source/tests before asserting behavior; historical worktree docs are not current authority.

Default `okf_search.py` now includes three selected sprint entrypoints: this board, the controlled
assignment and APPLICATION-PORTS. Other sprint/historical documents remain opt-in. From MC,
target the rest of the packet explicitly:

```powershell
python docs/tools/okf_search.py "sprint oc current resume interrupted worktrees" --root docs/specs/provider-consolidation-2026-10/sprint-oc --limit 3 --json
```

## Current control

Owner instructions OC-D206/207 authorize bounded recovery and full 58-to-four consolidation now,
with preserved source/evidence homes and recovery verification. The five unfinished slices have
retired their physical checkouts after verification; their recovery branches remain unreviewed
and unqualified. No branch deletion, paid/remote execution or runtime completion is authorized by
checkout consolidation. Runtime repairs remain separate reviewed batches.

- Architecture checkpoint: Swarm approved as a StageGraph composition/profile, not a separate workflow-system primitive (OC-D204, owner reply "Approved", 2026-10-29). Preserve group policies, common scheduling/transfer and behavioral qualification. [Exact scope/provenance](../../../provider-consolidation-2026-10/answers/SPRINT-OC-RECOVERY-SITTING-1-2026-10-29-ANSWERS.md). EO approved (OC-D205, "Yes approved."): share GoalDirected machinery while preserving distinct identities, exact sealed evaluator context/full producer feedback and host decisions; runtime repairs unimplemented.
- B0-Swarm approved by owner ("Yes I approve", 2026-10-29) and applied: four canonical files, exact SHA-256 d3055abd84027af9fd259e8b7e5f38ba0eee795a499ba729120d1e2a2eb2ee6b, base e643e473. Independent Sol review approved; base/patch/result hashes verified. Integrated documentation checks: 7 passed, 0 failed; diff whitespace check passed. Evidence: `.scratch/sprint-oc/recovery-checkpoint-2026-10-29/swarm-contract/`. No runtime/schema/release/cleanup changes. Rollback reverses only the approved patch after drift checks.
- Next action is set by the owner's explicit next-session instructions: local W0/W1 work and Mission Control refinement may precede the cloud coding-environment and deployment-architecture packet. Preserve the applicable W1 qualification frontier against coordinated MC/KS builds. The remote-readiness coding sprint follows W0/W1; deployment follows readiness proof. Do not repeat completed Qualia/overnight or AI Engineer (2026-10-31) fixtures or infer release from them; the next AI Engineer step is the KS planner typed-column fix and a production MC→AIDB producer-attribution mapping, then a live-catalog Selection Workspace run. Older setup evidence stays in `.scratch/sprint-oc/b4c-complex-fixtures-2026-10-29/` and `.scratch/sprint-oc/foundation-2026-10-29/`. Swarm/dedicated EO remain deferred; W1/W2 remain unqualified.
- Update these four control lines in place after decisions; do not create another competing handoff.

## Current overnight execution direction (2026-10-29)

**Completed bounded assignment, 2026-10-30:** the service prerequisite, StageGraph, GoalDirected
and same-application linked workflows now pass the requested local runtime and readable-evidence
gates. AI Engineer covers acceptance gating, exact delivery, duplicate relay, restart, current-use
revocation, explicit adoption, cancellation before/after receiver start and held-report repair.
Biotech repeats the actual application/catalog/scientific-qualifier/report-custody route in run-20;
run-21 confirms AI Engineer revocation after the final cross-service audience repair. This closes
the overnight engineering assignment, not W1/W2 qualification or a remote deployment. The next
proof is the separately governed W1 qualification against these coordinated MC/KS builds.

Execution evidence: `.scratch/overnight-2026-10-29-a/INDEX.md` (private, local readable receipts).
The initial primary heads were MC `3a6e70c2`, KS `7fd88d06`, AIDB `74fd2c3`.
MC `95405b50` integrates the readable exporter; `ef8cc631` and KS `f91e3fb` integrate
capture custody, and KS `d355136` adds the scoped public capture-fragment route. Phase 0 run-5
passes real local discovery, capture, immutable acquisition provenance, reconstructed object
custody, exact public fragment verification, K01 registration and MC submission. This is a service
trace, not a Temporal mission or report promotion. The six complete skill bundles were separately
mounted/read through Deep Agents; the current workflow fixture authors zero skills.

MC `8a2a41f9` integrates exact verified knowledge-read bodies, transfer access references and
named-output review packets. MC `8e88b800` integrates named stage settlement constrained to the
current attempt/generation, completion-only ordering edges, and local-slot → exact admitted owned
output-key mapping. Context regression (201 tests), targeted ordering/named-output checks, lint,
types and commit hooks passed. No remote push occurred.

StageGraph now passes the complete local probe set on canonical `mc.mission_run.v1`: run-18
positive, run-19/held (expected failed mission with no consumer), run-20/wrong-digest (typed refusal
without content, then correct read), run-21/restart (same saved cognition/result, no duplicate model,
registration, output revision or effect), run-22/isolation (real older/sibling/current registrations,
only exact current successor submitted/accepted/delivered). All five use identical source fingerprints
and await root completion/result materialization. Their complete readable evidence is indexed above.
Earlier runs 13–17 remain valid family/KS/recovery evidence, but used `belllabs.run.v1`; that root
scope gap was discovered by Goal run-3 and closed by these fresh reruns, not retrospective relabeling.

GoalDirected run-4 passes the ordinary root, full two-iteration repair and durable result:
`a00c112b-ce8f-5051-beb3-601099ab6ba2`, effective configuration
`sha256:eccd9aa90162f51a20e4f6cb7d2bcc2da6c1c3a94aa26c05f9b593a829873e1b`.
The exact held subject reaches independent verifier 1; full persisted findings reach producer 2;
its report successor explicitly supersedes the observed predecessor; verifier 2 accepts the exact
current candidate. Required report/progress fulfillment, distinct producer/verifier sessions and
workspaces, and exact candidate plus verifier-decision human-task review are proved. Review is
scripted identity/digest approval, not semantic human qualification. Historical held and current
accepted bodies retain separate statuses/digests. Goal run-1 failed a fixture context parser before
tools; runs 2/3 completed the family but failed the durable-result assertion. Root-3 history exposed
the legacy technical root; the ordinary scoped submitter fixed that gap without manual materialization.
The earlier race-only diagnosis is superseded. Original failures and logs remain intact.

MC `965e7aa5` integrates the Stage fixture/recovery collector. MC `d2378a0c` integrates the
reviewed Goal and scoped-root changes. Goal changes add exact finalized-attempt evaluator/repair subjects without
loosening ordinary dependencies; full immutable verifier feedback as mandatory untrusted context;
and named candidate review preserving the verifier decision. The scoped root composition honors its
trusted application binding. Focused context/output checks (255), exact-context checks (23), existing
Goal checks (47), relevant lint/types and the real runs pass. Broad mypy following imported legacy
test helpers reported 188 errors in 14 unchanged files; the explicit changed-file checks with
`--follow-imports=silent` pass. Do not present the broad imported-test check as passing.

Goal run-5/persistent-failure failed before verifier 2: a successor registration reused an
identical content-addressed report-body artifact, and MC attempted a second producer fact, refused
by `content_lineage_one_producer_idx`. Both KS registration effects applied; the ordinary root
terminalized the runtime failure without a durable aggregate result. Failed evidence stays intact.
The reviewed repair adds atomic registration-specific lineage recording: retain the original
producer, record the new caller/receipt, reject conflicting subject bytes and preserve the strict
generic second-producer refusal. Crash recovery takes producer coordinates from the durable journal.
Focused unit checks and the real PostgreSQL gateway regression, including concurrent reversed-order
registrations and atomic integrity refusal, pass. MC `29acf3f7` integrates this repair;
`f40faf12` integrates the Goal negative/recovery probes. The broader knowledge selection passed
396 tests and exposed two stale registry-count assertions; `3bed59fd` corrects them against the
exact retained legacy submit schema, and both affected files pass (16 checks). No extra semantic
tool was added by that test correction. Commit lint/type/dependency hooks pass.

Goal run-6/persistent-failure now passes using the unchanged unsupported 9B candidates: two actual
KS held assessments, two `repair_required` decisions, authored `iteration_limit`, public terminal
failure, no review, no accepted report and no required-report fulfillment. The canonical root
completes and materializes the failed family result. Reused body custody has one original producer,
two callers and two distinct applied registration effects. Stale-feedback proof replays actual
verifier-1 records against the actual verifier-2 subject at the host resolver and refuses them;
it is not a live stale-operation dispatch.

Goal run-8/unavailable and run-9/restart pass on identical final source fingerprints. Unavailability
persists `waiting/settlement_unavailable`, leaves the exact report unaccepted, and resumes that same
revision to a native passing decision and acceptance. Worker replacement preserves the saved result,
binding, attempt/generation, checkpoint, cognition, output revisions and original registration
receipt/effect. Both complete the canonical root and scoped durable result after ordinary verification
and the authored exact-review gate. Run-7 remains an earlier passing unavailable probe; final helper
assertions in run-8 target the exact report independently of progress text. Complete readable evidence,
actual bodies and body-digest checks for Goal 4/6/8/9 are closed; each run retains its original pins.

The StageGraph and GoalDirected bounded local engineering gates are closed. Linked AI Engineer
run-2 now passes ordinary chain release/relay/launch: a one-iteration independently verified and
reviewed source GoalDirected mission exports its exact accepted report; a separate StageGraph
mission reads the pinned source bytes and accepts its own attributed summary. Both canonical roots
complete with durable scoped results. Delivery does not implicitly adopt the source into a receiving
obligation. Common exact export/transfer, receiving preparation, authoring policy and additive database
release 1.10.0 are implemented, tested and locally integrated in `abac1fde` with the 1.11.0 successor.
Fresh install
and upgrade from the unchanged 1.9.0 prefix pass local PostgreSQL checks; no remote install occurred.

Linked run-1 failed before admission because the smaller consumer manifest retained a removed goal
reference. Its refusal and absent execution evidence remain preserved. Run-2 corrects that fixture
reference and adds semantic authoring preflight. Independent evidence review verifies the combined
timeline against both per-run transcripts and exact source/receiver bodies. One saved consumer body
sidecar suffered Windows CRLF conversion (422 bytes versus the actual 405-byte read); its original
file remains, and a digest-verified UTF-8 supplement now carries the observed bytes. The exporter has
been repaired to verify exact bytes on disk. This was an evidence-file defect, not a runtime transfer
mismatch. Source/schema pins remain those actually used by each run.

Linked run-3/gate, run-4/duplicate and run-5/restart pass on identical source/schema/KS fingerprints.
The gate retains an accepted source report but no export, receiver admission or start intent until
the actual human review completes. Losing the first start acknowledgment causes real lease expiry
and redelivery to the same canonical Temporal execution, without repeated registration/read/submission.
Real worker replacement preserves the saved consumer result, exact export and plan identities,
source accepted heads and original registration receipts/effects. Both roots materialize durable
results in all three cases. Independent readable/body/transcript checks are closed.

The affected regression exposed old artifact-only test setup compiling the new exact binding shape
without named promises, plus a real missing family-writer read grant. The historical packet fixture
now explicitly persists the legacy binding shape and retains its assertions. Additive release 1.11.0
preserves every built 1.10.0 migration byte and adds scoped read access for sealing exact exports;
family-writer document inserts are restricted to `linked.export/1`, without output mutation grants.
Fresh installation, upgrade, prefix preservation, scoped role/security checks and the legacy chain
regression pass (10 checks). These remain local engineering results; no remote installation occurred.
The named owning-Goal gate also needed to recognize exact named bindings without invented legacy
artifact evidence; atomic export sealing still requires actual accepted owned revisions.

Linked run-6/revocation failed the real current-use gate: a genuine KS source correction advanced
the epoch and affected the exact report/use decision, but the receiver's original delivery still
returned `ready`. The fixture assertion stopped cognition; that is not a production refusal.
The prior MC passing assessment remained standing. The current-use resume reused a durable
`decision.resolve` request identity from sealing, replaying the earlier eligibility answer.
The repair uses fresh read identities, records promotion-time demotion and makes linked current-use
unavailability a typed wait without changing the standing judgment. Existing write identities and KS
receipts remain immutable. Complete failed-run readables preserve the correction, ready receipt,
empty receiver cognition and actual `execution_failed` chain result.

Linked run-7 proves the repaired runtime boundary: the exact native passing assessment is superseded
by review, `source_head_demoted=true`, and actual delivery records `refused` with
`LINK_OUTPUT_REVOKED`, before receiver cognition. The overall test still failed its readable gate:
the exporter reported deliberately absent receiver materialization/report bodies as collection gaps.
The narrow expected-absence repair passes run-8/revocation, including its readable gate. Source
sidecars now distinguish a retained accepted head from current demoted use. Run-7 is not a passing
pytest result; its original exit and all receipts remain preserved.

Linked run-9/adoption passes: an explicit host adoption act under the actual receiver invocation
creates its separately authored required report as an unaccepted, unfulfilled draft. Ordinary trusted
settlement later accepts that same receiver revision and fulfills its promise; exact source derivation,
one adopter fact and unchanged native original producer are checked. This is a fixture-invoked host
service, not a newly exposed agent tool. Exact adopted body/ledger readbacks are exported as receiver
outputs. Runs 8/9 have identical full source/schema/KS pins.

Linked run-10/cancel-pending reaches genuine governed cancellation of source and receiver. The receiver
never starts a Temporal root: accepted chain cancellation and unstarted terminalization close it with
zero cognition, output evidence and budget liabilities. The overall test fails only its collector's
three executed-receiver expectations (outputs HTTP 404, materialization and report body). Narrow
never-started handling passes fresh run-11 with actual scoped accepted/applied cancellation receipts,
Temporal NOT_FOUND and zero receiver work. No direct rejected start-gate call is claimed from these
attempts. The original run-10 nonzero exit remains preserved.

Linked run-12/default-continue and run-13/propagate both pass runtime and readable gates on identical
source pins. The already-running receiver completes with its own accepted comparison under default
continue; explicitly selected propagation cancels it and retains its comparison as an unaccepted draft.
Actual cancellation commands, unchanged exports/plans/source heads, complete separate transcripts and
exact output bytes are checked. These are independent mission-chain cases, not new spawned/attached
run qualification.

Linked run-14/held-repair passes: the source stops after one unsupported iteration with its report held
and unfulfilled. Explicit execution-complete/finalized-subject repair delivery carries exact report bytes
and full 6,882-byte verifier findings. The receiver's actual registration names that exact predecessor;
its grounded successor earns ordinary trusted acceptance and required fulfillment, with a distinct
producer and no adoption. Both body/ledger pairs and the full findings read are exported and verified.
The source and chain remain failed while the independent receiver succeeds; no parent fulfillment is
fabricated. Both canonical roots and scoped results are retained.

MC `abac1fde` integrates the reviewed common linked runtime, current-use checks, governed cancellation,
explicit adoption and held-repair route with immutable database successors 1.10.0/1.11.0. The affected
chain/context/trusted-judgment/architecture/prefix selection passes (375 checks), authoritative source
mypy passes (1,030 files), public manifest schemas match their generators, and commit hooks pass.
MC `6f4eb9c6` integrates the fixture/evidence batch. These are local commits; no push occurred.

Biotech run-15 failed before admission because the actual Anthropic catalog row did not match the
fixture's OpenAI served component. A new coherent fixture definition fixes that identity; no retained
pin was relabeled. Run-16 then failed preparation because the scripted fixture lacked the matching
synthetic Anthropic credential. Run-17 reached producer and independent verifier cognition but kept
the report held; diagnostic runs 18/19 preserve that failure and expose the exact cause. KS omitted
the task audience from evaluation context, and MC defaulted it to `official` instead of the actual
`internal` audience. The native decision correctly held official scientific use for missing authority
and challenge evidence. MC `8bf10f85` and KS `187e7f6` carry the exact task audience and wait if it
is absent or invalid; official audiences retain their policy requirements. KS `4a18570` integrates
the local diagnostic/correction fixture commands. Failed configs,
transcripts, exact draft bodies, native decisions and digest checks are retained for all attempts.
Biotech run-20 passes (48.90s, exit 0): source `538e1415-4a60-5e9d-8b4a-7285ac4fb615`, receiver
`598476b2-a09a-543e-83b6-2cacd16a8141`. Both canonical roots have scoped durable completed results.
Native use preserves `audience=internal` with `purpose=official`, and admits the exact scientific
report. The receiver reads the exact 405-byte body and 1,360-byte ledger, accepts its own summary,
and creates no adoption. Actual Biotech `producer.default` is Anthropic `claude-sonnet-5-5`; its
new served fixture ref `model.overnight.biotech.producer.default@1` has digest
`sha256:9a3cb7e4ea685987ff10d30c536ecdc19c18c034c8127498a20ad43ddeff32a6`.
Invocation remains scripted. Complete configurations, four sealed operation bindings, scientific
qualifiers, tenant/binding, native decision records, lineage and 422 combined transcript entries
are independently checked in the private run-20 readable proof. No native graph write is claimed.

AI Engineer run-21/revocation passes (42.49s, exit 0) after that repair: a genuine source correction
demotes the source head and produces `LINK_OUTPUT_REVOKED`/`ACCESS_REVOKED`, a refused delivery
receipt and zero receiver cognition/output. The failed receiver is the expected business outcome;
its canonical result and explicit materialization/output absence are retained. Readable checks
cover exact source bodies and all 211 combined transcript entries. Earlier run-8 remains historical
proof on its original pins; no failed run was relabeled.

Final integration verification passes: 97 fixture/manifest checks, authoritative mypy over 1,030
source files, and the post-commit real PostgreSQL chain-release/rollback/role/autostart, Temporal
duplicate-start and 1.11.0 fresh/upgrade security regression (10 checks, 31.08s). Protocol/host builds,
required-audience and actual-host tests, evaluator tests/parity and package typechecks pass. The
existing evaluator-output parity digest is unchanged; only its context gains the actual audience.
Common component 1.11.0 runtime fingerprint is
`sha256:de10791b71f556e0a8761a3e6c298108452a96c2ae66ad31fb33b45dee9efd95`.
Each run retains its actual source, schema, policy, model and tool pins rather than inheriting the
final commit identity. Deployment must pair the fixed MC and KS context contract; an older KS
response without audience now waits instead of inventing it. Fresh/upgrade proof remains local.

Next action: use the private INDEX to review Stage18, Goal4/6/8/9, linked2/3/4/5/9/11/12/13/14,
Biotech20 and revocation21; then execute the applicable W1 qualification packet on coordinated
builds and explicitly identified targets. W1/W2 release, real-model semantic qualification,
dedicated EO/Swarm, native Biotech ingestion, remote installs, push and W5/stress are not claimed.
No W1/W2 or broader sprint gate is released. Actual model spend remains USD 0: runtime cognition and
judgment are scripted over real local services. Fresh verified loopback PostgreSQL/Supabase targets
were installed; existing databases were not wiped. Isolated workflow databases remain retained.

Start [SESSION-OVERNIGHT-WORKFLOWS-2026-10-29](../sessions/SESSION-OVERNIGHT-WORKFLOWS-2026-10-29.md).
Owner now prioritizes functional Deep Agents workflows, more repair latitude and small representative
fixtures. Sequence: shared service prerequisite → StageGraph implementation/fixture → GoalDirected
implementation/fixture → same-app linked workflows implementation/fixture. Run a fixture after each
implementation pass; do not defer all runtime proof to the end. Dedicated EO may defer (it shares
GoalDirected machinery, not StageGraph); nested bodies/Swarm/native ingestion are not prerequisites.

- Team: GPT 6 Astra lead and Astra agents for difficult runtime/integration/review; GPT 6.1 Sol for
  smaller work and context gathering, including delegation from Astra subagents. Four live agents
  maximum including lead; one writer per shared module and one heavy build/DB/Temporal job at a time.
- Required owner-visible evidence (OC-D209): a session INDEX linking each attempted fixture's
  effective configuration, observed materialization, complete readable workflow transcript and
  actual output bodies. Preserve JSON/JSONL receipts alongside Markdown, collect failed runs too,
  redact credentials and mark missing/truncated bodies. The overnight packet defines the file tree
  and exporter routes; pytest success alone does not satisfy this deliverable.
- More repair room: six targeted fix/rerun cycles before a lead reassessment, then continue with
  evidence-backed revised strategy. This is an engineering default rather than an owner-set cap.
  Three unchanged failures trigger diagnosis, not a repeated blind rerun or automatic abandonment.
- Owner reports unreleased/no users and wiped databases. Prioritize clean implementation over
  speculative compatibility; still verify actual targets and preserve ignored evidence/source.
  Routine local implementation, contract-conforming adapters, fixture installs, review and commits
  proceed without repeated approvals. The owner authorized up to USD 10 per model fixture;
  remote operations and push remain separate.
- At handoff preparation, Sol's read-only audit found the linked-input builder refused `LINK_INPUT_UNSUPPORTED`
  (WI-16/OVE-179), with existing chain release/relay/adoption code to extend. This is implementation
  work under accepted contracts; it is now implemented and exercised as recorded above.
  Exact source/test routes and ordinary-runtime proof requirements are in the overnight instructions.
- Historical handoff preparation: no new runtime execution or workflow qualification occurred in that
  instruction-writing turn. Code baseline remains MC `5188747d`, KS `7fd88d06` before these docs.
  Existing W1/W2 and live/full-recovery proof gaps remain until actual evidence closes them.

## Historical service-specific fixture setup (2026-10-29)

The preparation direction was to create guided, service-specific partial fixtures: sandbox discovery
and KS skills, report-only context and optional entity navigation, then test search→capture→report
in bounded steps. The then-next proof was discovery/capture custody and its exact K01 fragment
bridge, ending at MC submission for Phase 0; run-5 above now closes it. The [retained setup instructions](../sessions/SESSION-CODEX-RESUME-2026-10-29.md)
contain preparation details; the overnight assignment governs the broader workflow sequence.

- Added `scripts/report_source_sandbox.py` and `tests/fixtures/report-source-foundation/partial-fixture.json`.
  It reuses the verified AI Engineer context; canonical schemas and skill sources are unchanged.
  Six skill bundles contain selected shared KS contracts, task cards and two optional entity cards.
  Tavily/Firecrawl skills are fixture-authored procedure adapters, not upstream vendor distributions.
  The missing KS skill `name` is added only in the packaged copy and recorded in provenance.
- Every sandbox file has a byte digest; canonical skill sources and transformations are recorded.
  Fresh output, exact inventory and optional expected-manifest checks reject drift and extra files.
  All runtime references mount below `/skills/`; the full schema/evidence tree is not injected.
- The guiding task, schema route and budgets are supplied. Answers, selected quotes, support
  verdicts and prose are not. Both provider skills are available; tool admission is separate.
  Managed KS discovery and direct-provider/self-reported import are distinct selectable routes.
- Preparation verified at `.scratch/sprint-oc/source-capture-setup-2026-10-29/sandbox-2`:
  176,819 bytes, manifest `sha256:c2c9a15253d6ce63cc22c26f0a61eabb580f7382c2b4a9a0b1976c2b0ef4e0ee`.
  Runtime test uses the real Deep Agents parser and StateBackend to discover six skills and read
  their complete instructions plus START_HERE, SCHEMA_ROUTE and the report contract. No provider
  call, storage installation, schema migration or search/capture integration is claimed by setup.
- Validation: two unit checks (determinism/fresh output/pinned digest, changed/extra-file refusal)
  and the actual Deep Agents loading/read check passed together. Scoped Ruff passed; independent
  review cleared setup and the handoff. Existing issue coverage remains the foundation work
  packages above; Linear sync remains queued, with no issue-completion claim.
- Phase 0 input: run the service-only packet, including disposable local storage if needed, with
  scripted provider/model behavior first. The overnight assignment authorizes routine missing
  adapters within accepted contracts; genuinely unsettled authority needs a concrete decision.
  Paid calls, remote operations and push remain separate; W1/W2 and native proof unchanged.

## Foundation implementation checkpoint (2026-10-29)

The remaining foundation outcome is admitted discovery/acquisition plus full workflow recovery
with durable payload custody and independently authenticated evaluators. Current work closes
submission usability, canonical context delivery and a joined MC→real KS→exact Deep Agents
consumer repair fixture, including bounded receiver redelivery. The detour is not fully qualified;
see the [proof guide](../../../../REPORT_SOURCE_FOUNDATION.md) for exact boundaries and commands.

- Baselines: MC `33e6b355`, KS `9ba70c8`, AIDB `74fd2c3`, BKS `8e8d3d1`, sole primary
  `sprint-oc` checkouts. AIDB/BKS sources and immutable published releases remain unchanged.
- Implemented: submit-output v2 structured feedback, pinned own-position inspection, progressive/
  final submission and expected-head checking serialized with promotion. Replay precedes the head
  check. Additive knowledge-tools 1.1.0 preserves the original seed and v1 surface.
- Integrated locally: MC `0fd52b28` contains the submission slice and public predecessor receipt
  normalization; KS `998eaae8` validates the predecessor's exact digest/version before successor
  writes and adds both-app real HTTP/PG repair/restart tests. Repository hooks passed; no push.
- Integrated locally: MC `d2fc6b8d` adds context profiles/materialization and the joined/reconstructed
  receiver tests; KS `7fd88d06` adds their real-service fixture host. Independent reviews cleared
  the changes; both repositories' commit hooks passed. All work remains on primary `sprint-oc`.
- Implemented: canonical AIDB/BKS context profiles, KS contract dependency closure, omissions,
  source/file/manifest digests and a 196,608-byte cap. AI Engineer context is 118,882 bytes;
  Biotech is 188,370 bytes. Raw sources are preserved; prompt bytes explicitly normalize LF.
- Implemented: distinct GoalDirected repair / StageGraph transfer renderer and serial proof runner
  with fresh outputs, exact exit/timeout evidence and no paid launch. Native derive/apply excluded.
- Tested: deterministic double materialization; full context reads through actual Deep Agents;
  held first report→receipt-bound successor→KS admission→selected exact consumer bytes for both
  applications. PostgreSQL transfer/journal/lineage/saver reconstruction returns the completed
  result without extra model calls or checkpoint/lineage growth. Staging/result custody remains
  in memory; this is not process-crash recovery or a Temporal mission. Judgment/census and
  promotion are test-controlled; real evaluator HTTP identity is not qualified.
- Tested separately: KS exact package/body readback and registration replay after executor restart;
  unknown/wrong-digest/wrong-version predecessors refuse before a valid successor registers.
- Review repairs: legacy tool description, public predecessor shape and exact predecessor guard,
  repair instruction revision/stop conflict, actual returned package/body verification, duplicated
  auditor fixture entry, and Windows saver/child-process harness compatibility. A stale protocol
  build initially prevented host startup; rebuilding protocol before host resolved it.
- Targeted source mypy (production modules), source-mapped TypeScript, Ruff and hooks passed.
  Optional mypy over the joined test helper crashed internally in `zipimport.pyi` (mypy 1.20.2),
  so that check is not claimed passed.
- Final serial matrix passed all 11 steps at MC `d2fc6b8d` plus the reviewed renderer/runner diff
  and KS `7fd88d06`: both context preparations, four manifest renders, 53 focused units, four
  scripted Deep Agents checks, eight PostgreSQL output-contract checks, both joined/replay cases,
  and both standalone KS restart cases. Exit 0; logs, source pins and unrun qualification gates
  are in `.scratch/sprint-oc/foundation-2026-10-29/combined-2/`. MC documentation checks passed
  7/7; KS agent-docs check passed (431 selected inputs); catalog validation passed (193 definitions).
- Discovery requires configured artifact custody and providers; do not substitute a fake and call
  it live. The proof guide records a bounded proposed paid packet. No paid call, remote operation,
  push or W1/W2 gate release occurred. Native proof remains queued after this detour.
- Remaining local prerequisites: no artifact-storage service was running in the inspected Docker
  inventory; only the verified loopback PostgreSQL target was used. Admitted discovery/capture
  bindings and a concrete artifact-storage target still need integration. The inherited Biotech
  replay has one label, so the proposed two-label case remains unmet. Full durable payload/process
  recovery and evaluator identity must be proved before calling the foundation complete.
- Existing issue coverage: WI-01/OVE-163, WI-02/OVE-164, WI-03/OVE-165, WI-06/OVE-169,
  WI-08/OVE-171. Linear unavailable; sync queue only, no completion update claimed.

## Next-session foundation detour (2026-10-29)

### Outcome and owner provenance

The nearest unmet outcome is a Deep Agents producer that can discover its output contract,
register an evidence-backed report, understand submission/refusal state, repair it through
independent verification, and deliver the exact accepted revision to a consumer. Complete this
foundational path without requiring full domain schema selection or native entity/graph ingestion.
Common contracts remain provider-neutral; Deep Agents receives them through its adapter.

Owner: “setting that up completely is the next step”; “I want the output submission tool and how
it works enhanced and worked on”; “a bit of a detour and then a little bit of progression to the
next session we already had planned.” The owner requested a GPT-6.1 Sol subagent to gather context
and construct this next session. This preparation changes documentation only. The following work
packages are the concrete recommended implementation scope, not claims of implemented behavior or
owner selection of every API detail. Necessary local work toward that requested outcome should
proceed without re-requesting the same scope; materially different contract choices need a concrete
decision. Paid model/search calls, remote operations, push and unrelated cleanup remain separate.

### Source baseline and bounded retrieval

Read applicable workspace/platform/repository/scoped guides, live Git status/HEAD/worktrees, this
section and the session instruction. Keep `sprint-oc` primaries and existing dirty/ignored work.
Search named source/test directories; do not recursively load recovery branches, outputs, receipts,
dependencies, private notes or full schema IR. Historical recovery queues below are provenance.
Resolve existing OVE-162 child issue coverage before implementation; do not invent new issue IDs
or mark an issue qualified from this planning document. Use the existing local proof environments
only after checking the data-plane guide and disposable target identity.

| Concern | Verified source route | Existing behavior / remaining work |
| --- | --- | --- |
| Submission contract | MC `src/mission_control/domain/outputs/contracts.py`, `application/outputs/submission_service.py` | `SubmitOutput@2` has progressive/final mode, expected head and derivation references; `SubmissionAck@1` carries findings and typed recovery metadata. Recorded submission is not promotion/fulfillment. |
| Agent surface | MC `src/mission_control/application/knowledge/toolset.py`, `adapters/deep_agents/knowledge_tools.py` | `SubmitArgs` omits those optional contract fields; `_submit_named` uses default final mode, drops successful findings, and `_named_refusal` reduces errors to code/message. Full-key refusal discovery already exists; do not recreate it. |
| Output inspection | MC `application/outputs/inspection.py`, `interfaces/http/output_inspection.py` | Existing read-only promises/heads/fulfillment/assessment/transfer views can inform a narrowly scoped agent projection; operator run-wide access must not be inherited by the agent. |
| AI Engineer subset | AIDB `scripts/schema-workspace/cli.mjs`, `scripts/schema-workspace/lib/commands/materialize.mjs`, `scripts/schema-workspace/lib/selection.mjs`, `workspace-scopes/` | Scope-driven tree/JSON materialization already exists. It filters relations/functions/domains/tasks/queries, records omissions and uses dependency stubs; current selection retains all vocabularies. |
| Shared subset adapter | KS `packages/knowledge-db/src/schema-workspace/materialize.ts` | Reuse authoritative CLI/prebuilt/in-process selection routes; identify which route and version the fixture actually uses. |
| Biotech subset | BKS `packages/schema-workspace/src/slice.ts`, `packages/schema-workspace/src/schema-contracts.ts`, `workspace/START_HERE.md` | Budgeted `bks-schema-slice.v2` and companion advisory `biotech-schema-context.v1` are different artifacts. Preserve required closure/rules, omissions and compileability flags. Neither grants write authority. |
| Report and evidence | KS `catalog/research/report-kinds/evidence_report.json`, `packages/research-core/src/records/{report,fragment}.ts`, `packages/research-core/src/ports/report.ts` | Shared engineering/scientific report kind and immutable source fragments exist. Use operational KS records, not a new domain report implementation. |
| Exact read | KS `packages/knowledge-operation-protocol/src/selected-read.ts`; MC `application/context/materialization.py` | Exact package/reference/digest semantics exist; prove receiver bytes and use authority. Nested/linked workflow transfer remains unsupported in MC `domain/context/transfer_builders.py`. |

Paths in this table are repository-relative; MC application/adapters paths share
`src/mission_control/`. AIDB is `aiengineer/ai-engineer-db-contract`; BKS is
`biotech/biotech-knowledge-services`; KS is `platform/knowledge-services`.

### Work package A: make submission usable without weakening authority

1. Trace registration→submission→assessment→promotion→fulfillment→transfer through the existing
   application services. Give the agent a concise contract and an example using a real registration
   receipt. Explain explicitly that a final submission is not completion or verified acceptance.
2. Preserve safe structured acknowledgement findings and refusal fields: field pointer, retry state,
   recovery owner, available actions and correlation where present. Distinguish recorded draft,
   pending assessment/use, accepted revision, blocked/rejected and fulfilled states from actual
   persisted facts. Do not rename canonical `accepted` semantics silently or fabricate a state.
3. Provide invocation-scoped discovery of pinned obligations, permitted forms/schema pins and
   useful current revision/status. Reuse the current prompt/inspection projection where possible;
   add a bounded read tool only if needed. Never expose other runs, tenants, positions or private
   evaluator data. Make every advertised recovery action actually reachable by its stated owner.
4. Expose progressive/final and expected-head behavior where supported by the accepted contract;
   verify defaults/backward compatibility and the atomic stale-head check. Inspect derivation
   authority before projecting `derivation_refs`; exposing arbitrary producer lineage is not a
   requirement. Keep attribution, digests where host-owned, tool-call idempotency and authority
   host-bound. Preserve the current explicit refusal of mixed/report-collection submissions.
5. Update descriptions/examples, capability catalog versions/pins and affected fixtures together
   if the public tool schema changes. Do not silently mutate an immutable admitted definition.
   Keep logic in common deep modules and provider wrappers thin. Registration and verification
   remain separate KS operations, even when presented as one coherent agent workflow.

Acceptance: through the real Deep Agents tool binding, prove actionable schema/obligation errors,
successful repair, same-call replay without a new revision, changed-payload replay refusal,
stale-head protection, finalization fence and actor/position isolation. Prove acknowledgement does
not fulfill a required promise. Existing routes include `tests/unit/knowledge/test_toolset_named_promises.py`,
`test_w1_tool_boundary.py`, `test_knowledge_tools.py`, `tests/unit/outputs/`, and saved-settlement
PostgreSQL/Temporal tests; add focused regressions for changed behavior, not duplicate coverage.

### Work package B: materialize the smallest truthful report/source workspace

Create reproducible, versioned fixture profiles over canonical sources, not manually edited copies
of generated workspace/schema files and not a forked database schema. Keep shared report/fragment/
assertion/support contracts distinct from domain navigation cards. Include task scope, audience/use,
report kind, qualifier profile, source authority, provenance and exact dependency references.
Record source fingerprint, selection, digests, required dependency closure/stubs and omissions.
Measure actual context size; a token estimate or budget is not proof that required contracts fit.

From AIDB, use `node scripts/schema-workspace/cli.mjs materialize --scope <scope-file> --out <fresh-dir> --format tree`
(or `json-bundle`). Inspect existing `navigate-report` and `build-evidence-packet` task cards;
`register-report`/`publish-report` describe native routes and must not imply those writes are needed.
Check retained vocabularies and broad task dependencies before claiming a small projection.

From BKS, after its normal build, use
`node packages/schema-workspace/dist/cli.js slice --tasks trace-answer-to-source --purpose read --max-tokens 12000 --out <fresh-dir>`.
The task is a starting navigation profile, not the complete shared KS contract bundle. Inspect
`claim-to-evidence-report` only for relevant semantics: it is a native write route, not evidence
of foundation-only runtime support. Preserve canonical pins and label read-only context as such.

Acceptance: both domain variants produce bounded, deterministic, digest-verifiable materializations;
all fixture-needed definitions resolve and omissions are explicit. No whole-schema prompt, missing
reference silently ignored, domain migrations, entity/graph writes or schema optimization required.
The actual runtime must receive and read the selected bundle; generating files alone is insufficient.

### Work package C: qualify the report/source foundation in bounded layers

Use a distinct fixture identity (for example `report-source-foundation`) and fresh output directory.
Reuse existing W1 report and W2 producer-consumer manifests, drivers and verification composition;
do not overwrite their qualification criteria. Start AI Engineer, then run the same shape with
Biotech scientific qualifiers and domain guidance. Proposed bounded tasks: report what two model
sources say about a named technical property; report what two product labels say about named
ingredients, without inferring clinical efficacy. Freeze the chosen questions and acceptance data.

- First prove registration, independent assessment and exact transfer with captured replay sources
  against real local services. Keep the producer responsible for assertions/support sets/body;
  the host owns scope/pins/digests, and separate qualified actors own judgment/audit/use decisions.
- Then wire admitted search/acquisition skills/tools to source capture/version, custody and exact
  evidence fragments. Budget discovery (initial target: three queries, three captured sources,
  two to four claims, at most three repair iterations). URLs or search snippets alone are not
  durable evidence. Inspect existing KS `knowledge_source_discover` contracts and admitted provider
  wiring before adding another search surface. Keep selected/omitted results and uncertainty;
  a failed search provider cannot establish absence of evidence. A scripted/frozen source run
  does not qualify live search or model behavior.
- Exercise an unsupported claim, independent refusal/feedback, repair to a successor report and
  acceptance under the applicable policy. Keep a persistent failure branch visibly unmet. Reuse
  existing GoalDirected iteration and separate StageGraph producer-consumer paths; do not assume
  nested GoalDirected-in-StageGraph composition or arbitrary workflow linking works.
- Deliver only the selected accepted revision to the consumer. Capture plan/selection/use/read
  receipts and actual backend readback; reject wrong digests, stale/unaccepted substitutions and
  unauthorized reads. Restart/redelivery must preserve the plan and avoid duplicate cognition or
  registration side effects. Verify idempotency at the actual seam, not just a mock assertion.
- Keep native derive/apply out of this fixture's admitted capability set. Verify the operational
  report runtime is wired without needing a native write. Resolve registration/evidence/use-policy
  defects needed here; mandatory human-review escalation and native ingestion remain separately
  tracked. Do not manufacture a review-required condition or waive a real policy requirement.

Acceptance evidence distinguishes pure/doubled tests, real local service integration, scripted
Deep Agents runtime, and live paid qualification. Maintain exact version/source/tool/model/skill/
policy/schema pins, app/tenant/run identities, assertions, receipts, cost and pass/fail/blocked/unrun
results in a compact matrix. Keep private bytes/logs ignored. An offline-complete session leaves a
ready bounded live-run packet with explicit unmet paid/external prerequisites; it never calls a
scripted run a live pass. Do not weaken verification or existing W1/W2 gates to make this fixture pass.

### Completion and return to the earlier sprint path

The detour is locally complete when the enhanced tool, reproducible domain subsets, runnable
foundation fixtures and meaningful local integration/restart checks are reviewed and integrated,
with remaining live qualification explicitly recorded. Update this board and the relevant code
knowledge/operator docs; run owner-specific checks. Use one heavy build/database/test job at a time.
This preparation used one GPT-6.1 Sol research subagent; prior permission for up to two GPT-6 Astra
helpers remains available for bounded implementation/review. Do not create separate user chats.
The Sol handoff review confirmed schema/KS scope and acceptance, and corrected abbreviated source
paths. This is review of the session instructions, not runtime implementation or fixture evidence.

Then resume the retained approved scope below: real HTTP review/successor resolution where required,
native application/readback and consumer proof. The detour may close shared report/transfer defects
but does not release W1/W2, qualify Biotech native mapping, integrate Swarm/EO, or implement linked/
nested workflow transfer. Report the exact remaining proof toward the owner's nearest goal.

## Approved next-session scope (2026-10-29)

**Queued after the foundation detour above.** This approval remains valid; its original entry task
is no longer the immediate next action. Preserve its deferred experiments and qualification gaps.

Owner: “I approve the next recommendation but I need to go into a new chat.” The approved
recommendation was **complete service-level report→review→native application→consumer proof**.
Continue the necessary local implementation, focused testing, independent review and verified
local integration/commits within that outcome; do not ask the owner to approve the same work again.
This is not authorization for paid model calls, remote installation/migrations, push, cleanup or
unrelated Swarm/EO/provider expansion. Propose a concrete budget/target packet before paid qualification.

The nearest goal remains complete workflow and agent configuration with Deep Agents primary,
provider-neutral common contracts and provider adaptation encapsulated in deep modules. Report
what each change closes and the next unmet proof; distinguish implementation, tests, integration
and qualification. Up to two GPT-6 Astra subagents are permitted; use bounded disjoint ownership
and independent cross-review, with one heavy test/build/database job at a time.

1. Read workspace/platform/owner AGENTS, this control board and the controlled session instruction.
   Inspect live HEADs, status and registered worktrees. MC runtime baseline is
   `f3274e77c08becb883060847c85b129b26ea793d`; KS is
   `9ba70c8a894675ed3e6bbdd8752d8ae04336b9e7`. A later MC documentation commit records this handoff.
   Both primaries were clean before the handoff edit. Reuse them on `sprint-oc`; preserve scratch.
2. Start at KS `.scratch/sprint-oc/b4c-complex-fixtures-2026-10-29/deferred.json`, its four HTTP
   logs and `deferred-postgres.integration.test.ts`. This excluded experiment never reached the
   review path: elevated risk alone did not yield `review_required`. Inspect actual authority/use
   policy wiring and existing qualified review fixtures before changing it. Missing authority
   catalog/default use classification is a hypothesis to verify, not an established diagnosis.
   Source routes: `packages/host/src/knowledge-operation/{backends,assessment}.ts`,
   `packages/application/src/research/{review,judgment.test,sv07.test}.ts`, and
   `apps/verification-executor/src/knowledge-operation/postgres.integration.test.ts`.
   Prove authenticated HTTP review→successor resolution→restart with an independently qualified
   reviewer and exact scope/digests; retain refused/stale cases. Do not fabricate a successful review.
3. Connect that real service behavior to the ordinary multi-iteration GoalDirected fixture:
   registered report→independent assessment/seal/use/review→accepted exact report in the next
   invocation→explicit native effect selection→applied receipt/readback→final fulfillment.
   Then exercise the W2 producer→consumer selected revision and actual received/read bytes.
   Preserve required-output gating, independent evaluator context, stable effect identity and
   restart/no-duplicate cognition or write. Begin with AI Engineer; cover Biotech operational
   reports separately. Investigate Biotech native mapping/applicability explicitly; do not invent
   domain mapping semantics or count `pending_dispatch` as committed graph ingestion.
4. Use `scripts/sprint_oc_w1_driver.py` and retained W1/W2 manifests. Native fixtures allow three
   iterations; driver evidence remains `qualified:false`. W1 uses persisted `/evidence` verification
   chronology, because these manifests do not have schema-slot completion-validation records.
   Stage templates carry receiver bounds; the family adds authored bindings at admission.
5. Read the data-plane guide before DB work. Existing guarded local fixtures are `sprint-v-pg17`
   on loopback port 55433 and `supabase_db_disposable-w1fixn-aidb` on 54922; verify identity first.
   Restrict Vitest discovery to exact primary files, excluding scratch copies. Use the primary
   Python environment explicitly for candidate tests. Stop after two unsuccessful repair cycles,
   preserve the failure and narrow the scope. Never mask failed or timed-out commands.

Completed baseline: 194 primary focused tests, 11 runtime/persistence tests and two KS native
tests passed; Ruff/format, seven-module mypy, commit hooks and documentation checks passed.
Do not sum overlapping candidate counts. MC B4c `integration/verification.json`, both owners' commit
records, review files and named logs hold the evidence. Real HTTP review, full service-level chronology,
Biotech native mapping and paid W1/W2 qualification remain open. W3–W5 and Swarm/EO are later work.

## Delivery orientation (owner steering, 2026-10-29)

The owner's nearest goal is completing workflow and agent configuration logic as fully as possible,
focusing nearly exclusively on Deep Agents through deep modules that encapsulate provider
extension/adaptation. All agent reports must lead with remaining distance to that goal: the nearest
unmet checkpoint, the gap closed by the current change, and the next blocker or required proof.
Keep precise evidence and distinguish implemented, tested, integrated and qualified status;
do not invent completion percentages. This reporting/prioritization directive is persisted in the
BellLabs-wide and global Codex agent instructions, with Claude guidance pointing to the same directive. W1 is the nearest qualification checkpoint;
verified integration of the approved native-write batch, W1 regressions/harness and both-application real acceptance are
still required. Existing per-batch approvals remain in force.

The destination is complex workflows executed FOR REAL in both AI Engineer and Biotech, with exact
output contracts, context transfer, acceptance and native-effect settlement. Deep Agents is the
qualification focus; common host/domain/port modules must remain provider-neutral and other providers
remain supported through adapters. Provider-specific qualification is not proof of every provider.

Cleanup and documentation prepare this path; they do not replace it. Preserve the five unfinished
source slices and unique runtime evidence through their recovery refs, bundles and verified archives.
OC-D207 physical checkout retirement is complete; the source homes remain available for review.
W1 remains unreleased: recover paired MC/KS native write and W1 harness/D27–D30 regressions; retain
Biotech's explicit native mapping/applicability blocker. Then prepare the separately approved real
qualification proposal. W2–W4, linked/nested workflow coverage, W5/OVE-186 and stress checkpoints
remain required under current approval/budget rules; no paid run or remote installation is authorized
by this orientation statement. Tracker sync queue: OVE-177/178/186; no update/completion claimed.

## First cleanup tranche completed (OC-D206)

Removed MC `.claude/worktrees/agent-a2c75fa62f434123b` with ordinary `git worktree remove` (exit 0).
Preserved branch `sprint-oc-r7` at `9dd8251403f67481741e825d881bbe1420c9200f`, already an ancestor of
sprint-oc. Exact path/registration/ownership/HEAD/branch/clean state/ancestry/locks and source stability
were checked before removal. No force, branch deletion, live DB/volume or unfinished-source changes.

Recovery at `.scratch/sprint-oc/recovery-checkpoint-2026-10-29/cleanup-r7/`: complete Git bundle,
398,000,819-byte ZIP, manifest, restricted user+SYSTEM access, RESTORE.md and retained test extraction.
31,470 files (1,034,748,816 bytes) were hash-verified against archive/source/restoration; all 5,134
directories match. Exclusive access had zero failures. Independent reviewer approved recovery and
operational quiescence; partial process visibility was covered by exclusive-access and stability checks.
ZIP SHA-256: e740a39b852e894e84c63caf060369189f0022012925cbdb75229c5c8e89a124.
Post-removal: path/registration absent, branch and archive retained. Total worktrees 58 (MC 41,
KS 8, AIDB 4, BKS 5). The five unfinished checkouts match prior HEAD/status and archived source hashes;
At that tranche, 49 other nonprimary candidates and five unfinished checkouts remained. The tranche
is complete; the later OC-D207 authorization below governs their full recoverable consolidation.

## Full consolidation and W1 source recovery (OC-D207)

The owner authorized consolidation of all 58 registered checkouts into the four canonical primaries.
Forty-nine candidates have clean committed heads already reachable from their owner sprint branch;
five unfinished slices have explicit preserved source homes, without a runtime integration claim.
The operation retains branches and Git bundles, archives ignored objects through same-volume moves,
and verifies object identities and restoration roundtrips. Individual ignored files are hashed;
dependency/cache directories use object identity and roundtrip proof rather than full content hashes.
Junction custody preserves link objects without traversing primary dependency targets. No force,
branch deletion, prune, live database operation or runtime release is part of this cleanup.

**Verified complete, 2026-10-29 14:49 UTC:** ordinary `git worktree remove` completed with exit 0.
Final verification found exactly four primary registrations, all on `sprint-oc`, and all 54 original
nonprimary checkout paths absent. All 54 branch homes and the original recovery refs remain.
The 54 custody manifests retain **6,254 ignored objects, including 11 reparse/link objects**; final
existence checks passed. Four Git bundle hashes and five dirty-source ZIP hashes passed verification.
Companion KS/AIDB/BKS primaries are clean. MC retains only the reviewed W1 source recovery and these
documentation changes. Evidence: MC
`.scratch/sprint-oc/worktree-consolidation-2026-10-29/final-verification.json`, per-checkout manifests
and movement journals. This completes checkout consolidation, not native/Swarm/EO integration or
runtime qualification.

The W1 source batch consists of `sprint_oc_w1_bindings.py`, `sprint_oc_w1_driver.py`,
`sprint_oc_w1_pack.mjs`, five `tests/fixtures/manifests/sprint-oc-w1/` fixtures and
[W1-EVIDENCE](../../../provider-consolidation-2026-10/sprint-oc/release/W1-EVIDENCE.md). Seven files match `sprint-oc-w1@a5fd5286` byte-for-byte;
the pack builder now resolves the canonical sibling KS checkout, and the evidence page has a dated
source-recovery note. Offline AST/Ruff checks passed for two Python scripts, JavaScript syntax passed,
and all five YAML files parsed. Independent source review passed and reproduced those checks. No runner, provider or database
execution occurred; native repairs and actual both-application W1 acceptance remain required.

## Recovery execution evidence (OC-D206)

- B1a: default retrieval adds only three current entrypoints; compressed index includes sprint-oc;
  excluded directories are pruned before traversal. Three questions find current status, app ownership
  and exact transfer authority. Two focused tests pass; independent Sol review approved; integrated in `9970cbd8`.
  Documentation checks: 7 passed. Swarm/EO terminology reconciled without reducing behavioral proof obligations.
- B1b: seven ignored run_*.sh wrappers now preserve the first failing command status and timeout status
  through diagnostic output. Nine syntax checks and 68 controlled cases pass; independent reviewer
  reproduced five key cases. Real pytest/database work was not run by these fixtures. Backups, patch,
  before/after hashes and checks: `.scratch/sprint-oc/recovery-checkpoint-2026-10-29/wrappers/`.
- Historical wrapper logs are not retroactively validated. Actual W1 tests must run through the repaired
  wrappers; no qualification/release status changes follow from these checks.

## W1 re-entry: next implementation batch

B3 uses paired native-write recovery from MC `sprint-oc-w1fix-n@5d0923c8` and
KS `sprint-oc-w1fix-n@e3c75b97`, using their original refs and verified source snapshots above.
Do not rely on their former checkout paths or merge the recovery commits wholesale. Exclude the
98 preserved KS generated contract changes from native integration. Scope: stale-plan
preview/redecision; refusal isolated per decision; already-applied recovery; authoritative run
identity; crash between decide and record; exposed effect receipt; cross-language preview/admission
parity. Those stale-selection and unguarded-settlement defects were in the recovered source;
the approved pair and B3-R repair are now applied in primary, with focused integrated verification passed. Use audit §3.1 and existing tests, not a fresh rewrite or a new
provider-specific execution path. Swarm `sprint-oc-wi14@6c558096` and EO
`sprint-oc-wi15@0c14071a` remain unreviewed recovery homes, not qualified runtime integrations.

Then adapt the retained W1 harness, verify D27–D30 and real local persistence/Temporal interactions,
and resolve Biotech native-intent applicability explicitly. Keep W1 unreleased until the actual
both-application acceptance criteria pass. Swarm/EO runtime consolidation and later complex-workflow
qualification remain visible parallel dependencies, not reasons to restart W0.

### B3 applied disposition (2026-10-29; focused verification passed after B3-R)

This implements the next native-write gaps toward Deep Agents workflow/agent configuration,
with focused integrated restart proof after B3-R; it does not close W1. Integration bases are MC `15966597` and KS `22b47d2` on `sprint-oc`;
AIDB `74fd2c3` and BKS `8e8d3d1` are unchanged. No new worktrees were created. Candidates and local
proofs are in each owner's `.scratch/sprint-oc/b3-native-2026-10-29/`; MC's `BATCH.md` is the current
review packet, not a competing handoff. Reporting directives were saved directly as authorized.

- MC: 22-file patch `be93afb4a1e7c0695f7a27147f2aed9c9d5b41baa836ceb224d9d650a3248336`.
- KS: 28-file patch `00ace1de491a3c70b480330fb5e6850491670c00c2b1d5b60c3e3313ffeeec0d`.
- Behavior: fresh synchronous preview/credentials, authoritative stored run identity, bounded
  changed-plan redecision, deterministic successor intents only after durable fenced rejection,
  per-subject typed refusals, receipt-first recovery of terminal/inflight effects and explicit
  effect-receipt submission. No phantom review wait for revoked/stale/expired authority.
- Passed on isolated candidates: 113 paired MC unit tests, two real local PG/Temporal checks
  (KS doubled for Temporal), targeted eight-module mypy and changed-Python Ruff/AST; 56 KS tests,
  targeted transitive TypeScript check, two real guarded local AIDB tests (preview/apply with
  distinct keys; preserved rejected ledger then successor apply/duplicate receipt), KS doc check.
  Five other AIDB tests were deselected, not passed. Forward/reverse/roundtrip patch checks passed.
- Integrated checks: 141 MC units, changed-Python Ruff, targeted mypy (14 modules,
  follow-imports=silent), seven MC documentation gates, 56 KS tests, targeted transitive TypeScript,
  one real local MC PostgreSQL test and two guarded local AIDB tests passed (five AIDB tests
  deselected). Temporal restart failed at the exact-pass-count assertion: an extra waiting pass;
  completion, two scheduled activities and one cognition were asserted before failure, but later
  exactly-once effect assertions were not reached. KS documentation check also failed: one test
  input hash is stale in two provenance entries. Earlier candidate checks do not supersede these
  integrated failures. Logs are preserved in each owner's local `integration/` directory.
- Independent Sol review found three blocking defects on the first candidate; all were repaired
  and source re-review approved with no remaining actionable findings. Reviewer inspected evidence
  but did not rerun tests. Exact logs and initial failed checks remain in the local packet.
- Unrun/unresolved: full repository gates, B4 explicit saved-receipt selection for
  `root.native_receipt` and tool/schema/seed pins, same-digest epoch-only authoritative
  requalification (typed refusal), Biotech native mapping/applicability, actual W1 runs and release.
  0069 remains a future-release candidate (renumbered `scripts/release_200/0072_native_plan_decisions.sql`
  on 2026-11-01, OVE-206: released 1.11.0 took key 0069; still unregistered). No paid calls, remote installs, pushes or tracker updates.
- Owner approval: “Approved. Continue”, for the exact pair above. Preflight verified unchanged bases,
  no target conflicts and patch hashes; KS then MC were applied and all 50 paths matched approved
  candidate content. See `integration/approval-and-preflight.json` and `integration/applied.json`.
  Initial check failures held B4 until the separately approved B3-R repair below passed in primary.
  Preserve the reporting-document edits. Rollback before release installation uses reverse patches after
  drift checks; preserve native receipts and installed migration history. Do not run with only half
  the pair installed. No push, installation or W1 release is authorized by this batch.

### B3-R integrated repair (2026-10-29; approved and focused checks passed)

Two files only: MC native restart test patch
`34dcea0d2b768239879cc972c07efe6150cf640d877efb2d016e1e6c7adc239e` and KS provenance patch
`e7a9979e57eaf91e7ae203f4237f23ba774d0683bb1fa97922abd3fff9951c18`. No runtime change.
The test records all waiting observations before approval, then requires exactly one settled pass,
one cognition and one native apply. A normal local restart and an evidence-only 3.5-second stall
exceeding the two-second heartbeat both pass; the latter reproduces two waiting observations and
the late-completion warning from the original failure. Replay and durable settlement pass in both.
Native stores, KS and apply remain doubled; this is not real-provider W1 acceptance. KS candidate
documentation check passes after regenerating two hashes for one approved test. Forward/reverse
roundtrips pass. Exact files/manifests, independent review and logs are in the repair packet above.
Owner approved with “Approved”. Both exact patches were applied after base/file/hash and active-writer
checks. Primary Temporal restart passed (one cognition, one apply, one decision, durable settlement
and replay); KS documentation check passes. Evidence: repair `integration/applied.json`,
`integration/pytest-native-restart-repair.log` and KS `integrated-docs.log`. Original failed evidence
and approved patches are preserved. Independent source review reported no actionable findings.

KS source is committed locally as `30171b221d85620cc0facc98ad30d39990115f21`. MC's first commit
attempt was stopped by its formatter hook (one multiline refusal call; other hooks passed).
The formatter suggestion was preserved and included in separately approved B4a; primary formatting
now passes. Local MC commit evidence is recorded in B4a `integration/`; no push occurred.

### B4a integrated disposition: durable receipt evidence (approved)

B4 tracing found that B3 exposes `native_effects` in the lane's `SettlementOutcome.detail`, but
`InvocationSettlement.advanced` drops the detail before PostgreSQL persistence. The saved result
remains durable; its native receipt metadata is not yet available through durable evidence. Prior
lane serialization tests do not prove this boundary. Prepare this narrow repair first, with real
local PostgreSQL re-read and Temporal restart checks; no output auto-submission or new operator
mutation API. Exact current candidate context is in the B4a local `PLAN.md`.

Primary baseline: 45 tests passed for D27 verifier separation, D28/D29 outputs, D30 evaluator
configuration, knowledge manifest/served components and catalog seeds. W1 remains unreleased.
Still required: explicit producer receipt selection, native fixture sequencing after accepted
report transfer, justified tool/schema/catalog alignment, remaining local harness and actual
both-application acceptance. Biotech native mapping remains explicitly unsupported.

Prepared patch SHA-256 `066a269f934ee7473f445d9020025e405cd2fef2eb00ce53515c1bef0e45c7fb`:
seven MC files, including the mechanical formatter fix noted above. The candidate persists only
bounded native effect reference metadata, exposes it through existing operation evidence, retains
prior references when a fenced pass skips collection, and accepts canonical protocol IDs. No
automatic output submission or native authority is added. Exact baseline file hashes and rollback
are in local `manifest.json` and `BATCH.md`.

Passed on the isolated candidate: 39 focused units; five real local PostgreSQL/Temporal checks,
including fresh-pool readback and restarted operation evidence; three-module targeted mypy;
seven-file Ruff lint/format; forward/reverse normalized roundtrip. First review caught overly narrow
ID/count constraints and cancellation clearing evidence; corrected and rechecked. The initial
Temporal test helper failure and fail-first tests are preserved. Independent review is in local
`review.md`; native service/apply remain doubled in Temporal. No W1 qualification claim.

No SQL migration is needed for the existing JSON record. Old rows load with an empty default,
but older runtime readers reject the new field: source rollback is straightforward only before
upgraded records are written. No downgrade/mixed-worker rollout is qualified; retain records and
plan deployment separately. No remote operation, paid execution, cleanup or push occurred.

Owner approved with “Yes approved.”. Preflight verified HEAD `15966597`, seven target hashes,
patch hash and no active matching test writers; both primary owners retain their sole checkouts.
All seven applied paths match the reviewed candidate. Primary validation: 39 focused units,
five real local PostgreSQL/Temporal checks, seven-file Ruff lint/format passed. Logs and original
file backups are in local `integration/`. Native/apply doubles remain in the Temporal proof.

Local MC commit `ecdba0452e0c4753d80ff9001baabd32ade1f366` contains the approved B3/B3-R/B4a
source and reporting updates; all applicable commit hooks passed. KS remains `30171b2`. No push.

### B4b preparation record: explicit receipt selection and reviewed native admission

The producer still cannot select a native effect while its plan awaits review: the tool response
exposes the decision but no exact effect key. Canonical submission already accepts an effect key
without a receipt reference; fulfillment still requires a same-run APPLIED journal receipt. Prepare
one shared key calculation for read-only lookup/apply/replay and expose the key in the pending-review
answer. Lookup must not create a journal row, credential, admission or effect. Prove an explicit
ordinary `submit_output` act before finalization, then review and saved settlement without repeated
cognition or submission. No automatic submission or stale-successor key remapping.

Keep fixture sequencing separate until proven: raising the native fixture's GoalDirected iteration
limit alone may not reach its second iteration, because the first independent verifier nominates
the still-missing native receipt among required subjects. A StageGraph replacement changes the
owner's W1 qualification scope and is not an authorized substitute. Preserve immutable catalog
seeds; validate current launch bindings before proposing any successor version. Biotech native
mapping remains unsupported. Exact B4b preparation scope is in its local `PLAN.md`.

B4b review found a concrete existing authority gap: real KS review supersedes the original decision,
but MC resolves the admitted successor and then sends the original ID to native apply. The KS guard
correctly holds that predecessor as `STALE_DECISION`. Prior same-ID pending-toggle doubles do not
prove this transition. The candidate therefore also separates immutable logical effect identity
from fresh successor admission before the first dispatch: exact root/chain/scope/report/subject/use/
audience/run checks; unchanged plan/origin/bound/normalized digests; actual KS exact-use admission;
and recovery of any existing journal before changing payload-local authority. Rejected roots are
not recycled, and changed-plan successors never silently retarget submitted candidates. Composed
recovery also needs the same configured capability pin as lookup/apply. All B4b source remains
isolated pending exact review/approval; primary B4a remains the verified baseline.

Exact patches awaiting approval: MC 10 paths, SHA-256
`ba5050d8a9be839f92a46314df225378bda5d0655522a1e4559cc67a6974ee03`, base `ecdba045`;
KS two paths (test and generated provenance only), SHA-256
`66fe4774aaf22729f2c71f73d222d528c0c55f76fcf89c14931c044c6a95ab55`, base `30171b2`.
Manifests and forward/reverse normalized roundtrip proof are in each owner's local B4b folder.

Passed on frozen candidates: 121 MC units; six real local PG/Temporal checks; two real KS tests
(six deselected); five-module targeted mypy, transitive targeted TypeScript, lint/format, KS docs;
offline W1 launch bindings for both apps match current served components with seed bytes unchanged.
Independent exact-pair review approved with no remaining actionable findings. MC restart proof
asserts actual runtime/saved-row/journal/candidate origin identity, one cognition, one explicit
submission and one apply. An earlier independent-coordinate fixture result is retained only as
plumbing evidence, superseded by that corrected proof. KS final exact rerun followed fixture type
guards and passed; earlier dependency/typecheck failures remain preserved.

Proof limits: the KS native seam uses real qualified SQL review records and real K01/native
execution; full HTTP review/resolve transport is not exercised. MC accepted-report/read-scope and
review transport remain doubles. W1 topology/GoalDirected chronology, epoch requalification and
Biotech native mapping remain unqualified. At this preparation checkpoint B4b source was not yet
applied; the integrated B4b/B4c disposition below supersedes that state. No migration or published
seed change, push, remote installation, paid run or cleanup was included.

### Larger B4b/B4c batch: multi-iteration and producer→consumer fixtures

Owner steering on 2026-10-29: “I am approving more iterations and a more complex fixture now.
That's fine.” The larger local batch includes the reviewed B4b receipt/admission prerequisite and
the bounded fixture expansion; it does not authorize paid/remote qualification or remove approval
requirements for unrelated batches. Two GPT-6 Astra subagents implemented disjoint slices and
independently cross-reviewed them. This section supersedes B4b's awaiting-approval state above.

Exact local source changes: MC 19 paths, SHA-256
`3e5d3a7bbba49c57786a7d3e72ddd2bac9f62c85e74805f2183a77f0f755da2b`; KS the unchanged two-path
B4b patch `66fe4774aaf22729f2c71f73d222d528c0c55f76fcf89c14931c044c6a95ab55`.
The originals, file hashes, owner quote, forward/reverse proof and application records are in each
owner's `.scratch/sprint-oc/b4c-complex-fixtures-2026-10-29/`. Existing status-document edits were preserved.

GoalDirected independent assessment now nominates criterion evidence instead of every declared
output. Nominated subjects remain mandatory; an empty selection uses the existing isolated
evaluator path. All required promises still gate final completion. Native fixtures allow three
iterations: report first, exact accepted-report native use next, and one bounded repair. Producers
explicitly submit pending effect keys. Two-stage W2 fixtures declare producer and consumer pins;
the driver validates current fulfillment, accepted heads and actual persisted GoalDirected
verification chronology, and checks W2 selected revision/delivery receipts. It always reports
`qualified: false`; these engineering checks are not model or application qualification.

Candidate validation: 48 focused tests; 11 real local PostgreSQL/Temporal/Deep Agents runtime
regressions using scripted models; Ruff and targeted mypy. Cross-review found and repaired the
empty-subject edge case and an incorrect reliance on schema-only completion evidence. Primary
unit/authoring checks: 194 passed. Primary runtime/persistence selection: 11 passed; exact primary
KS native selection: two passed, six deselected. Both W2 application manifests compiled and resolved
through actual launch and stage-input composition with fixture served components. Primary Ruff,
formatting, seven-module mypy, MC documentation (seven checks) and KS documentation (431 selected
inputs) passed. Preserved Windows line endings require the `cr-at-eol` whitespace check. A first KS
runner accidentally discovered scratch copies; its failed log is retained and the exact primary-only
rerun passed. Neither corrected harness discovery nor scripted runtime checks establish live qualification.

The proposed new KS HTTP review/resolve proof is **deferred and excluded**: after bounded fixture
repairs, its setup still did not create a review-held decision. The failed logs and source remain
in KS `deferred.json` and `deferred-postgres.integration.test.ts`. Source-only review did not make
that test pass. Existing real native tests use qualified SQL review records, not HTTP review.

W1/W2 remain unreleased/unqualified. Remaining proofs: actual service-level GoalDirected chronology,
HTTP review/resolve with authoritative policy, live receiving bytes/native readback, and Biotech
native mapping/applicability. Swarm/EO runtime integration and later W3–W5 remain separate.
