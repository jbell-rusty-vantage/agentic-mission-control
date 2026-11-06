---
type: Session Instruction
title: "Tracing Stage 2: real fixtures on a 10 USD cognition budget"
description: "Handoff from Stage 1 (sprint/tracing-stage-1, WP-TR-1..5 committed, zero spend): the live fixture plan, the models the owner names, the budget split, the F-T3-1 fix as the first item, and what Stage 1 left for Stage 2 and Stage 3 to carry."
tags: [mission-control, providers, consolidation, deep-agents, tracing, stage-2, handoff]
status: archived
archived: 2026-10-23
archived_from: providers/deep_agents/SESSION-STAGE-2.md
archived_reason: "Tracing Stage 2 done"
---

> **Archived 2026-10-23** (Tracing Stage 2 done). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Tracing Stage 2: real fixtures, 10 USD

Run under [PROCESS.md](../../../provider-consolidation-2026-10/PROCESS.md) against [TRACING-PROPOSAL.md](../proposals/TRACING-PROPOSAL.md)
§C.2, on the branch `sprint/tracing-stage-1` as Stage 1 left it (head `720545a4`: the six
work-package commits from `main` at `63ca7777` ending at `8a71b6b1`, then two documentation
commits `485a7ba8` and `720545a4`; not pushed, not merged; the working tree holds the
uncommitted documents named in §0 below). Read the ledger's
[Stage 1 finish](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md#stage-1-finish-2026-10-22-the-parts-to-read-the-sequence-the-owners-commands)
first, then the WP-TR-1..5 entries' honest lists: every item below that says "Stage 1 found"
points there.

## 0. Session facts and owner decisions (2026-10-22)

**The mission of this session:** run every fixture of §2, §4 and §4c against a real model,
write the output files of §4a for each, and when a fixture exposes a flaw or an error, fix it
in this stage, prove the fix, and document the fix (ledger row, finding id, commit). Stop at
the budget ceiling. End with §8. No question in this document is open; the owner answered them
all on 2026-10-22, below.

**Owner decisions (2026-10-22, final):**

- **Models:** GPT-6 Sol as the parent, GPT-6 Luna as the subagent, the turn 3 precedent.
  Reservations carry over from the live drill (1 935 tokens for one parent turn and one child
  answer). Record both model profile digests in the ledger with every run.
- **Fix scope:** tracing and lifecycle control flaws are fixed in this stage as the main goal
  (capture, transcript, points, fork, saver, settlement, cancel, budget, retry bounding). Flaws
  outside that scope **may** also be fixed when they come up and are quite clear, but that is
  not the goal; a clear, bounded fix is taken and recorded as a finding with the reference to
  the specification section it anticipates; an unclear or wide one is parked in §4b. Nothing
  about output contracts, transfer policy or middleware adoption is designed here.
- **Dependency pin:** `deepagents==0.7.5` stays for this stage; streaming is enabled in the
  live lane profile so the retention proof sees delta frames. The version bump waits for the
  contracts session (specification OC-D17).
- **Commits:** on `sprint/tracing-stage-1`, no push, no merge. First commit: the three
  documents named below plus this handoff. Then one commit per fixture: its fix (if any), its
  ledger row, its finding ids. Stage 3 reviews those commits one by one.
- **Budget ceiling:** 12 USD (raised from 10 for §4c); the split is §5; spend recorded after
  every run before the next starts.
- **F-T3-1 fix shape:** a non-parsing executor payload becomes a typed executor observation
  `disposition: failed, reason: output_unparseable`, settled and not retried, with bounded
  retries on the activity (specification §3.6), so the contracts session does not redo it.
- **Reading:** the owner reads every fixture's `transcript.md` in full before Stage 3 starts;
  the session's final message lists the files per fixture.

- **Model for this stage:** Opus 5.5 (the owner's Fable 5.1 budget is spent until Friday
  2026-10-24). Follow PROCESS.md as written; nothing in this stage needs the larger model.
- **Uncommitted on the working tree, written 2026-10-22, to commit as "docs: output contracts
  specification, audit, coordinator surface proposal" before the first fixture run:**
  `SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md` (now the specification with decisions
  OC-D1..D18), `AUDIT-OUTPUT-TRANSFER-2026-10-22.md` (the read-only audit it rests on),
  `docs/specs/coordinator-surface-2026-10/PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md`, and the
  root `AGENTS.md` docs index regenerated for them. None of the three changes this stage's scope.
- **Scope guard:** this stage proves tracing, observability and the lifecycle reads and
  controls. It builds **no** output contract, transfer policy, K04, K05 or middleware. The one
  kernel fix allowed is F-T3-1 (§2), and its shape must match the specification's §3.6 (a
  typed executor observation `disposition: failed, reason: output_unparseable`, settled, not
  retried) so the contracts session does not redo it.
- **The parking lot (§4b)** is where every observation about outputs and transfer goes. Do
  not act on them here.

The owner's framing to keep in view while reading transcripts: there is conventional knowledge
work and there is codebase work; Deep Agents is the knowledge-work lane in practice, and
codebase work on it is allowed but not assumed (TRACING-PROPOSAL P10 consideration). The
specification models the two as distinct output families.

## 1. What Stage 2 is for

The same assertions the FX-TR fixtures make, read through the public API, against a real
provider on T2 (real model, local worker, the production offline stack otherwise), plus
`replay --dry-run` at a real tool-calling step and `--full` on a real tool result above the
cap. Whatever a real model exposes that the scripted model never emitted (parsing, timing,
cost, provider frames, prompt-caching tails) is fixed in this stage and recorded as findings.
Spend stays under 10 USD in total; every run records its id, manifest digest, worker commit,
receipt digests and spend in the ledger before the next run starts.

## 2. First item: F-T3-1

F-T3-1 (`CHANGES.md`, turn 3): a Goal Directed executor whose final message does not parse
as `GoalNamedExecutorObservation` makes `reconcile_operation` retry without bound. Fix it
before any Goal Directed live run: a retry classifier case that settles the operation
`failed` with a typed reason (and surfaces it on `run inspect`), or a structured output bound
on the executor before the run. Prove the fix on T0 first (a scripted executor whose final
message is prose), then on the live Goal Loop below. The Stage Graph fixtures have no such
blocker.

## 3. The models the owner names

Stage 1 named none (every proof was T0, scripted cognition, zero spend). **Confirmed by the
owner on 2026-10-22 (§0): GPT-6 Sol as the parent and GPT-6 Luna as the subagent.** Do not ask
again; record the model profile digests in the ledger with every run. Reservations are sized
from the turn 3 live drill (1 935 tokens for one parent turn and one child answer).

## 4. The live fixture plan (in order)

1. **Stage Graph, the §1 mission scaled to the budget** (`S1 -> S2 -> {S3, S4}`, one cycle
   on S2, one sync subagent, one inject mid-turn): FX-TR-STEP, FX-TR-SUB, FX-TR-HOOK and
   FX-TR-STEP on the projection through the API; `run replay RUN --point ID --dry-run` at the
   real tool-calling step (`exact: true` against the recorded `batch_digest`); `run transcript
   --by step --point ID --full` on a real tool result above 8 KiB.
2. **The fork from S2 cycle 2** with an injected message (`run fork RUN --at stage:S2,cycle:2
   --point ID --inject msg.json`) and the derived run to completion: FX-TR-FORK-CYCLE's
   assertions, plus the first `model_request` of the derived `S2@c2` listing the copied ids
   and the marker, then the packet turn (Stage 1 found: the packet turn follows the injected
   message; §P5.3's "last human message" is of the seeded state).
3. **A three-iteration Goal Loop and its fork at iteration 2** (after F-T3-1): FX-TR-FORK-GD's
   assertions; the derived run's iteration 1 by reference, iteration 2's executor on the seeded
   thread with the marker, the verifier fresh.
4. **FX-TR-RETAIN with a streaming model**: Stage 1's scripted model emitted no delta frames,
   so the "deltas deleted and read `expired`" half ran against an empty class; a real streaming
   run proves it.
5. **FX-TR-REMOTE stays T0** (the proxy fixture, `tests/fixtures/tcp_proxy.py`); no live run.

## 4a. The owner wants to read the outputs: transcript and mission files per fixture

The owner's instruction (2026-10-22): *"I need to see output files in the next session
showing me the full transcript produced. I want to read it in full."* and *"I want to see
outputs of the transcript and the mission during these fixtures."* So every fixture run of
this stage, live or T0, writes its outputs to files the owner reads directly, under
`.scratch/tracing-stage-2/<fixture>/<run id>/` (kept out of commits like every runtime
receipt), and the ledger entry names each file:

- `transcript.jsonl`: the full `mc.transcript_entry.v2` transcript of the run
  (`missionctl run transcript RUN --format jsonl --limit 5000 --full`), every entry, promoted
  bodies resolved, nothing excerpted; and `transcript.md`, the same transcript rendered
  (`--format md`) for reading end to end.
- `transcript-by-step.jsonl` and `transcript-by-stage.jsonl` (or `--by iteration` for a
  Goal Loop): the grouped views, so the owner can see one step's model request, its tool
  results and its lifecycle facts together, and one stage's `released_by`, `continues_from`,
  decision and completion row together.
- `mission.json`: the mission as the owner sees it: the manifest the run was compiled from,
  the compile and admission receipts, `run inspect` at completion (units, budget, effects,
  `points_incomplete`), the points index (`run points RUN --limit 5000`), and for a fork the
  fork receipt beside the derived run's own files.
- `outputs/`: every output the units produced as the dependent stage received it (the
  workspace candidates and governed artifacts named by the result points, downloaded with
  `run artifact`), so the owner can judge what was transferred against what was produced.
- `replay-<point>.json` for the replay dry-run at the tool-calling step, and
  `state-as-of-<point>.json` for the seed point of each fork.

The session's final message lists these files per fixture, and the owner reads the transcript
in full before Stage 3 starts: whether it is coherent and useful (one reads a step and knows
what the model saw, what it answered, what it called and what came back; one reads a stage and
knows who released it and what it handed on) is an owner judgement this stage must make
possible, not assert.

## 4b. Parking lot: observations for the output contracts and transfer session

While reading each fixture's `transcript.md`, `mission.json` and `outputs/`, record here (dated,
tagged by fixture) what the transcripts show about the five audit facts the specification rests
on, so the contracts session starts from live evidence instead of the scripted model:

- **Submission as it happened:** which files the real model wrote under the writable slot,
  whether its final JSON carried an `output_refs` key, and whether that key replaced the
  registered refs (`AUDIT-OUTPUT-TRANSFER-2026-10-22.md` §A4, §D4). Note any prose-only final
  message.
- **What S3 received from S2:** the `.mission/context.md` and `.mission/inputs.json` of the
  dependent stage as `state-as-of` shows them; whether the most important output arrived whole,
  summarized or as a pointer; whether the agent tried to run a fetch command that does not exist
  (§D5).
- **What S2 cycle 2 received from cycle 1:** confirm it was only the new objective (§D8), and
  what the real model did without its prior results.
- **Goal iteration 2:** what the handoff listed versus what iteration 1 actually produced;
  whether verifier findings were missed (§D9).
- **Fork inject:** whether the injected message read as an instruction or as data to the model.
- **Anything the owner, reading in full, found incoherent** in a step or a stage group: this is
  the usability judgement §4a asks for, and the specification's instruction segment (§4.6) is
  where it will be fixed.

Each entry: fixture, run id, point id, one sentence, and the file and line in the transcript.
No build items; the specification's §8 decisions absorb them.

### Entries (filled 2026-10-22 from the Stage 2 transcripts)

Paths are under `.scratch/tracing-stage-2/`; "line" is the line of that run's `transcript.md`.

**Submission as it happened**

1. *f-t3-1-live*, run `9f77dba6-f421-53c3-a97f-31ffcd840812`, executor result point
   `75d3161b-c556-51fd-8f91-537b1d3bf8e7`: with no structured-output binding, Sol wrote
   `/goal/1/executor/work/note.md` (a registered workspace candidate) and answered two sentences
   of prose with no `output_refs`; the iteration settled `failed/output_unparseable` (line 174).
2. *stage-graph-live* attempt 1, run `85a2a071-eae8-531b-b550-9ad229d366f7`, S1 result point
   `99f6653d-010a-5efc-8ffe-08f66d5ad24a`: the fixture asked for a final JSON with
   `"output_refs": []`; the Stage Graph merged it over the result, the attempt's registered refs
   were erased, S1 had no output and the run terminalized `failed` (lines 301, 358). AUDIT §A4/§D4
   confirmed live: the model's key replaces the registered refs (OC-D4).
3. *stage-graph-live*, run `cfc84d11-6ad6-557d-8e35-a19dc3d04403` (and the fork source
   `455c660c-…`): without an `output_refs` key every stage wrote exactly its instructed file under
   `/workspace/output` (ten candidates, `outputs/custody/`) and the result points name only the
   registered `workspace-candidates://…`; no prose-only final message on the Stage Graph.
4. *goal-loop-live*, run `21449cb9-b227-5eea-a944-0d5664aadb84`, verifier input point
   `89839495-d86d-51b9-8af8-91ff3cd16d95`: every executor answered `output_refs:
   ['/goal/N/executor/work/note.md']`, a path in its own workspace; the verifier's packet lists it
   as `executor_outputs | reference | read_file /goal/1/executor/work/note.md | 0 bytes |
   unresolved executor output of iteration 1` (line 351), it cannot read it, the registered
   candidate never reaches it, and it rejected all three iterations ("Provide the iteration-3 note
   in the verifier's readable inputs", line 2060): both Goal runs ended `failed` for this alone.

**What S3 received from S2**

5. *stage-graph-live*, run `cfc84d11-…`, S3@c0 input point `7f172635-5bae-52ec-940e-c9f92f8f77b5`:
   S3 received S2@c0's brief **whole and inline** (`S2-input`, `accepted_output`, 1 355 bytes,
   `untrusted_content`, line 797); S3@c0 and S4@c0 then ran on a brief the cycles later replaced.
   The packet header says "fetch references with the listed command" and lists none; the model
   tried no fetch (§D5: no attempt observed, the instruction is still wrong).

**What S2 cycle 2 received from cycle 1**

6. *stage-graph-live*, run `cfc84d11-…`, S2@c1 input point `08c01450-185e-58e4-86ac-eaa6cf40824f`:
   only the new objective ("Brief cycle 1: Clarify how WAL-before-data ordering and surviving
   commit records combine to make recovery durable.", line 1528) and S1's facts again; its own
   cycle-0 brief is in neither the packet nor the inputs (§D8 confirmed). The model rewrote the
   brief from S1's facts rather than revising its draft; the same at S2@c2.

**Goal iteration 2**

7. *goal-loop-live*, run `21449cb9-…`, iteration-2 executor input point
   `3a2a23b5-15d1-5183-8f92-08ca53a37cb7` (the fork's seed): the executor wrote no handoff at any
   iteration, and the iteration-2 packet holds only the operating contract, the objective and the
   workspace map (line 642): no verifier findings (§D9 confirmed), no prior note. The operating
   contract says "finish with your typed executor observation and handoff" and nothing says what a
   handoff must hold.

**Fork inject**

8. *fork-s2-c2-live*, derived run `7ae62697-9bcb-5f9a-a065-6f7d32f1467e`, S2@c2 input point
   `ce0ada27-8a73-5eed-a602-f65d2bba4f13`: the model saw the copied cycle-2 conversation, then the
   injected operator instruction (line 195), then the full stage prompt again (the packet turn
   follows the injected message); it read the injection as an **instruction**: the derived brief
   has a "`synchronous_commit = off` trade-off" paragraph and the fresh S3 and S4 carried it on.
9. *goal-loop-live*, derived run `3dea6a17-2ca0-5276-ae8e-9a3aa3c741ad`, iteration-2 executor input
   point `197e73af-e684-54b8-964a-f0174e2b9954`: the injected message is the last human message
   (line 174); the iteration 2 and 3 notes are rewritten for the on-call reader it asked for
   (read as an instruction).
10. *stage-graph-live* `cfc84d11-…` (line 186) and the fork source `455c660c-…` (line 223): the
    operator note injected mid-turn into S1 reached the replacement turn as a user message.

**Incoherent or hard to read (the owner's judgement to confirm)**

11. Every run: kernel hook ports write a `hook_invoked`/`hook_result` pair per port per tool call:
    160 of the 257 entries of the T0 Goal Loop, 86 of 165 in the live F-T3-1 run; the step a
    reader cares about is buried between them.
12. Every Responses API message carries an `encrypted_content` reasoning block of 1-2 KB in
    `transcript.jsonl` (the Markdown hides it since 6.5).
13. The executor's operating contract asks for a "typed executor observation and handoff" with no
    schema in sight when no structured output is bound (f-t3-1-live, line 97).

## 4c. Lifecycle-control proofs added 2026-10-22 (owner decision: in scope)

Five proofs that stay inside tracing and lifecycle control, reuse the runs of §4 where they can,
and fail early on claims the system makes. They run in this order, after §4 item 1 and before
§4 item 3 unless noted. Each is a fixture with a ledger row, output files per §4a, and a fix in
this stage if it fails.

| Id | Proof | Run | Asserts |
| --- | --- | --- | --- |
| **FX-TR-BUDGET** | the budget cap is a lifecycle outcome on a real model | one short Stage Graph (two stages) with `tokens.total` reserved below what the real model will spend on S1 | S1 settles with the typed budget outcome (not a provider error, not a retry loop); the result point's `budget_snapshot` shows the exhausted dimension; `run inspect` shows the budget state; S2 is not admitted; recorded spend stops at the cap |
| **FX-TR-CANCEL-LIVE** | `cancel --urgency immediate` fences a real model turn | one short Stage Graph (one stage, scripted delay not available: use a long instruction) | the stop fence refuses the next tool call; the unit settles `cancelled` (not `completed`, the Stage 1 observation of WP-TR-2); the transcript shows the fence frame after the last admitted tool call; no further `model_request` after the cancel is accepted. If the unit still completes, the fix lands in this stage |
| **FX-TR-STREAM** | the Socket.IO stream equals the transcript | subscribe during §4 item 1; zero spend | every `provider_frame` and lifecycle event received carries `unit_key` and `point_ref`; the ordered event sequence per point equals the projected transcript's entries for that point; a client resuming with `after_point_ref` from the midpoint receives exactly the remainder; no event is received for a frame absent from the transcript and vice versa (deltas excepted, listed) |
| **FX-TR-RECONCILE-LIVE** | the reconciler is idempotent on real data | `run points --reconcile` on the completed §4 item 1 run; zero spend | the response reports zero points and zero ranges written; `written_by` unchanged on every point; the transcript digest before and after is equal |
| **FX-TR-DISCONNECT** | a provider disconnect mid-stream settles typed | the TCP proxy fixture (`tests/fixtures/tcp_proxy.py`) in front of the provider endpoint, one connection cut during a model turn of a one-stage run; runs last | the activity settles a typed provider outcome (named in the ledger: today there is no retry classifier, so record what actually happens); the partial frames of the cut turn survive with their point; retries are bounded; the run reaches a terminal state; spend recorded for the partial turn |

Output files for each follow §4a under `.scratch/tracing-stage-2/<fixture>/<run id>/`.

## 5. Budget split (under 12 USD, ceiling raised 2026-10-22 for §4c)

| Item | Runs | Reserve | Notes |
| --- | --- | --- | --- |
| F-T3-1 proof on the live Goal Loop (§2) | 1 short Goal Loop | 1.0 USD | one iteration is enough to prove the failed settlement |
| Stage Graph live mission (§4 item 1) | 1 run | 2.5 USD | four stages, one cycle, one subagent, one inject; FX-TR-STREAM and FX-TR-RECONCILE-LIVE ride on it |
| Fork from S2 cycle 2 (§4 item 2) | 1 derived run | 1.5 USD | S1 by reference, S2 cycle 2 from the seed, S3 and S4 fresh |
| Goal Loop, three iterations (§4 item 3) | 1 run + 1 derived | 2.5 USD | iteration 1 by reference in the derived run |
| Retention with streaming (§4 item 4) | reuse item 1's run | 0 USD | the expiry runs on the maintenance queue |
| FX-TR-BUDGET (§4c) | 1 short run | 0.4 USD | the cap itself bounds the spend |
| FX-TR-CANCEL-LIVE (§4c) | 1 short run | 0.4 USD | cancel early in the turn |
| FX-TR-DISCONNECT (§4c) | 1 short run | 0.5 USD | partial turn plus one bounded retry |
| Reserve for a re-run after a fix | | 2.0 USD | never more than one re-run per item |
| **Total** | | **10.8 USD** | stop at 12; record the spend after every run |

Use `TRACING_CEILINGS`-sized reservations (`tests/fixtures/rrm009_production_stack.py`) as the
starting point and lower `tokens.total` per unit to the live drill's measurement before the
first run.

## 6. What Stage 1 found that Stage 2 must carry (from the ledger's honest lists)

- Goal Directed reuse compatibility compares the Context Packet segment and the read mounts
  by shape (WP-TR-4): a live Goal Loop fork proves the reused verifier still verifies the
  reused executor's real output.
- A fail-closed reuse stalls a Goal Directed run (WP-TR-4): if a live derived run settles a
  unit `failed/incompatible_restore`, the family records nothing more. Stage 3 owns the fix;
  Stage 2 should not launch a Goal Directed fork whose source was patched.
- The derived Goal Directed launch carries its own templates (WP-TR-4): a manifest-driven
  launch of a Goal Directed fork needs the launch author to read `derived_goal_revision_id` and
  `start_position` from the receipt; Stage 2 launches through the fixture's `goal_input`.
- The API's maintenance queue is `<base task queue>-maintenance` (WP-TR-5): a deployment
  whose API and worker settings disagree on the base queue stalls every seeded fork. Check both
  settings before the live runs.
- The points walk budget is 5 000 ms by default (`MISSION_CONTROL_POINTS_WALK_BUDGET_MS`): a
  real saver on a slow link may mark `points_incomplete`; `run points --reconcile` completes it.
- A run still completes after `cancel --urgency immediate` (WP-TR-2, observed); `state-as-of`
  with the saver closed now answers 503 (WP-TR-5), the closed-saver read of WP-TR-2 is covered.
- asyncpg `executemany` stalled on the Windows selector loop (WP-TR-3); every bulk write of
  the sprint is set-based now. Watch any new bulk writer.

## 7. Non-goals

The review, simplification, test-gap and documentation pass (Stage 3); output contracts,
K04, K05, K11, the `progress_note` tool, pruning (TR-D17), the Agent Server's move to the
Postgres edition and the child-state read through its API; the fold-backwards optimization of
the points walk (P6.1). No push, no merge, no deployment. The specification in
`SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md` and the coordinator-surface proposal are
read for context only; their decisions are the owner's to take after Stage 3.

## 8. End with

The ledger entry (one row per change, finished part, proof, spend per run, checks run, the
honest list, every fix with its finding id and commit); the describe matrix changes Stage 2
proved; the §4b parking lot filled from the transcripts; the handoff `SESSION-STAGE-3.md`
(the adversarial review scope from §C.3, the findings of Stage 2 in priority order, the list
of per-fixture commits to review); and a final message that lists, per fixture, the output
files of §4a and §4c with their paths, the spend, and what failed and was fixed.
