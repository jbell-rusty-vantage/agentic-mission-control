---
type: Session Instruction
title: "The sprint sequence from tracing Stage 3 to the finished Deep Agents support: three interview sittings, twelve sprints, two live proofs, and the first session instruction"
description: "Written 2026-10-23 at the owner's request ('set me up for the sprints to come: sequence, information, interviews, details'). Orders the work that finishes output obligations, context transfer, mission state storage, observability, tracing, the Transcript and its retrieval, in light of the 2026-10-23 architecture call (four states, the domain output family, the service map). Gives the recommended sequence with the alternative it displaces, one card per sprint (goal in the owner's words, inputs, decisions it rests on, builds, proves, non-goals, size, spend), the three interview sittings with their rounds (the existing R0-R9, HR0-HR9 and the new RA, RD, RS, RP), the reading list per sitting, and the ready-to-paste instruction for the first session, which is interview sitting I."
tags: [mission-control, providers, consolidation, deep-agents, planning, sequence, interview, obligations, transfer, tracing, provenance, P1]
status: archived
archived: 2026-11-02
archived_from: SPRINT-SEQUENCE-2026-10-23.md
archived_reason: "retired: sitting I cards A-I superseded by Sprint OC and the Agentic SDLC program"
---

> **Archived 2026-11-02** (retired: sitting I cards A-I superseded by Sprint OC and the Agentic SDLC program). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# The sprint sequence

**Owner amendment, 2026-10-24 (SV-D6..12).** [Sprint V](../sessions/SPRINT-V-PLAN.md) now completes verification,
reports, schema refactors and both knowledge-service bindings, AI Engineer then Biotech in the same
sprint. All existing data/history is disposable. Real research, ingestion, retrieval and retrieval
experiments wait for all four workflow systems, output contracts/context transfer and full Deep Agents
qualification. Earlier live-experiment ordering below is superseded by this gate; bounded disposable
engineering fixtures can prove the foundations before it. This is planning direction, not completion.

**Status.** Planning document, 2026-10-23. It orders; it decides nothing. The owner interview
([OWNER-INTERVIEW-2026-10-22.md](../interview-instructions/OWNER-INTERVIEW-2026-10-22.md), rounds R0-R9) remains the
instrument; this document splits it into three sittings so building can start after the first,
adds the rounds the 2026-10-23 call opened, and gives every sprint a card. Every session follows
[PROCESS.md](../../../provider-consolidation-2026-10/PROCESS.md): orient, audit, cross-reference, plan, **confirm with the owner**, build in
deep modules, prove, document, hand off. Nothing in a card is built before its sitting has
answered the decisions it rests on.

**Inputs this document orders.** The [output-contracts specification](../specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md)
(OC-D1..D26), the [domain-provenance supplement](DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md)
(DP-D1..D14, rounds RA and RD), the [coordinator-surface proposal](../../../coordinator-surface-2026-10/PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md)
(CS-D1..D14), the [human review gates supplement](../../../proposals-2026-10/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md)
(HG-D1..D24, HR0..HR9; still at the platform root, to be moved beside the specification in
sitting I), the [tracing proposal](TRACING-PROPOSAL.md) honest list (P11), the ledger's Stage 2 and
Stage 3 honest lists ([CHANGES.md](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md)), and the program's capability
catalog C01-C16 ([README](../../../provider-consolidation-2026-10/README.md) §3).

## 0. The owner's words (verbatim, 2026-10-23)

> *"We need to finish everything output obligation, context transfer, mission state storage,
> observability, tracing, transcript and retrieval of transcript (much work has been done I'm
> talking about proof and refinement)."*

> *"I haven't yet completely architected knowledge services and yesterday I was mapping out my
> systems' capabilities and end goals (as a service and as a business) and I realized that
> knowledge services is partly or is distinct from: User Services; Content Services (Generative UI
> component services?); Evidence And Report Services (Part of knowledge services?); The application
> api and the product api (literally querying belllabs biotech backend); The user facing ai agent
> skill and infrastructure (what tools does the ai assistant use to answer user's query. This
> depends on application and feature space). I'm just giving you a birds eye view so you
> understand how output contract obligations and mission types and all of that might need to
> evolve."*

> *"Your job is to get me ready for the next sprints that cover mission control workflows + agent
> cognition and context."*

The goal statement these sprints answer to is unchanged: [OWNER-INTERVIEW §0](../interview-instructions/OWNER-INTERVIEW-2026-10-22.md#0-the-goal-verbatim-2026-10-22),
its five properties (customizable cognition, obligations, transfer, long-running control,
comprehensibility).

## 1. The recommended sequence

```text
 I    Interview sitting I   R0, RA, R1, R1b, R3.8                         1 sitting, docs only
 A    Deep Agents upgrade (0.7.30 stack)                                  1 session
 OC-1 Obligations, submission, fulfillment, promotion, release 1.4.5     2 sessions
 II   Interview sitting II  R2, R3, RD, RS                                1 sitting, docs only
 B    Agent configuration language, lane features, model tools, hooks    2 sessions
 OC-2 Transfer policy, materialization, dependency kinds, T6/T7          2 sessions
 OC-3 Cycles and the Goal Loop (K04, K05, K02)                           1-2 sessions
 T2-1 The vision mission, live (reports, PDF, verdict), under 15 USD     1 session
 P    Proof and refinement: tracing, Transcript, state, retention        1-2 sessions
 III  Interview sitting III R5, R6, R7 + HR0..HR9, RP, R8, R9             1-2 sittings
 K    The domain family and the Knowledge Services binding (biotech)    2 sessions
 R    Review Gates and steering (HG-1..HG-5, RV)                         per the supplement
 F    Lifecycle and observability on obligations                         1-2 sessions
 G    Linked workflows on obligations                                    1 session
 H    Parallelism and workers (independent; any time after A)            1-2 sessions
 I    Retrieval surface and the Mission Control skill                    2 sessions
 T2-2 The biotech scenario, live (entities, sources, reports, synthesis) 1 session
```

### 1.1 Why this order

1. **Three sittings instead of one.** The strawman interview ran R0-R9 before any build. The owner
   wants to start the next sprint shortly, and only R0, R1, R1b and the upgrade question gate A
   and OC-1. Sitting II gates B, OC-2 and K; sitting III gates everything that reads obligations.
   Each sitting ends with its decisions folded into the specifications and the next session file
   written in full (OWNER-INTERVIEW §4.5).
2. **OC-1 before B.** The strawman put the agent-configuration language first so that obligations
   attach to its nouns. The owner's stated priority is finishing obligations and transfer, and
   `outputs:` already exists on every node (`domain/authoring/manifest_lowering.py`), so OC-1
   attaches obligations to today's node schema and B lifts them into `agents:` unchanged. The cost
   is one rename in B; the gain is that the critical path starts one sprint earlier. This is R9.1's
   "B folded into C" alternative, taken partly: B stays its own sprint, after OC-1.
3. **P after the first live proof.** Proof and refinement of tracing, the Transcript and the state
   model need a run that exercises obligations and transfer; T2-1 is that run. P then fixes what
   T2-1 shows and closes the tracing honest list that is still open (§3, card P).
4. **K after P and sitting II.** The domain family (DP-D4) is a kernel kind, but its proof needs
   the Knowledge Services binding this repository does not have. K builds the minimal binding
   against biotech's live executor, so it comes after the kernel kinds are proven and after RD and
   RS have said what the services map requires.
5. **H is a parallel track.** Stage parallelism exists in the Stage Graph workflow; H is defaults,
   a worker role and a proof. It can run after A whenever a second session slot exists, and it
   makes every later live proof faster (R6.4).
6. **I last.** The owner said so; the generated workspace must describe what exists.

### 1.2 The alternative this displaces

B before OC-1, as the strawman had it. Choose it if the owner wants the language settled before any
obligation lands; the price is that obligations and `submit_output` arrive two sessions later.
R9.1 asks this.

## 2. The three interview sittings

Each sitting runs under OWNER-INTERVIEW §4.3 and §4.4: context, at most four questions per batch
with the recommendation first, the restated mental model, the record in §8, the drift check
against the five properties. The interviewer builds nothing.

### Sitting I: alignment, state, obligations, transfer points

| Round | Source | Decisions | Gates |
| --- | --- | --- | --- |
| R0 alignment and language | OWNER-INTERVIEW §5 | R0.1-R0.3 | everything |
| **RA architecture and state** (new) | supplement §8 | DP-D1, D2, D3, D12, D13 | OC-1 (two agent-facing acts), P (triggers, as-of read) |
| R1 output obligations and verification | OWNER-INTERVIEW §5, OC §3 | OC-D1..D7, D14, D19..D21, D25, D26 | OC-1 |
| R1b where context transfers happen | OWNER-INTERVIEW §5, OC §4 | OC-D8..D13, D15, D16 | OC-2, OC-3 |
| R3.8 the upgrade first | OWNER-INTERVIEW §5 | sprint A | A |

Reading list for the owner before sitting I (about forty minutes): OC §0-§4 and §8; the
supplement §1, §2, §6 and §8; OWNER-INTERVIEW §0, §3 and the R0, R1, R1b rounds. Outputs: the
decision log rows; OC and the supplement updated; `SESSION-A.md` and `SESSION-OC-1.md` written in
full; the human review gates supplement moved from the platform root to
`providers/deep_agents/` with its relative links corrected.

### Sitting II: subagents, the capability language, domain provenance, the service map

| Round | Source | Decisions | Gates |
| --- | --- | --- | --- |
| R2 subagents | OWNER-INTERVIEW §5, OC §3.7 | OC-D22, D23 | OC-1 (sync part), OC-2 (T6/T7) |
| R3 the capability language and code structure | OWNER-INTERVIEW §5 | R3.1-R3.7, OC-D17, D24 | B |
| **RD domain provenance** (new) | supplement §8 | DP-D4..D11, D14 | K |
| **RS the service map** (new) | §2.1 below | RS.1-RS.6 | K, the obligation templates, the mission types |

### 2.1 RS. The service map (new round, sitting II)

Context: the owner's 2026-10-23 bird's-eye view (§0). Mission Control is one producer among
several services; the question is which of them produce, which consume, and what that means for
obligation kinds, obligation templates and mission types. Strawman, for the owner to correct:

| Service (owner's words) | Relation to Mission Control (strawman) | What it needs from obligations |
| --- | --- | --- |
| User Services | neither producer nor consumer of missions; identity and tenancy arrive through the Application Binding's issuers | nothing in the kernel |
| Content Services (generative UI components) | a **consumer** of `published` deliverables; possibly a producer when a mission generates content | no new kind: content is `document` or `structured_record` with a **template** (OC-D19) and a schema pin; "generative UI" is a consumer-side renderer over `structured_record` |
| Evidence and Report Services | the **producer side is a mission**; the service side is retrieval and verification of what missions published; evidence custody is shared with Knowledge Services (the snapshot's `custodyArtifactDigest`) | `document` with `evidence_backed`, `file_artifact`, `domain_effect` for graph claims; an "evidence report" template; the `verified` and `published` dispositions |
| Application API and product API | **consumers**: they read the application's entity store and Mission Control's `published` deliverables; they never read mission tables directly | the disposition ladder (DP-D11); a stable `artifact://` read; nothing else |
| The user-facing assistant's skills | a **consumer** through the application API; a **requester** when it asks the coordinator to launch a mission; never an inner-mission agent | a mission-type catalog it can name (below) |

Mission types, strawman: a mission type is a manifest template in the catalog (research-and-
ingest, evidence-and-report, content-generation, codebase-change, synthesis-and-audit), each
naming its obligation templates and its review gates. Mission Control does not grow a kind per
service.

Questions:

- **RS.1 (must)** Confirm or correct the producer/consumer table. Which services may launch
  missions, and through which surface (the coordinator skill, the application API, both)?
- **RS.2 (must)** Is "report" one thing or two: a Mission Control `document` deliverable, a graph
  `report` node, or both joined by digest (DP-D14)? Who owns the report schema?
- **RS.3 (must)** Content Services: does any mission produce UI components, and if so is
  `structured_record` with a component schema enough, or is a kind needed? (Recommendation: no
  kind; a template and a schema pin.)
- **RS.4 (must)** Publication: the disposition ladder's `published` step is set by the
  application's gate and recorded by Mission Control; confirm that no service reads mission tables
  directly.
- **RS.5 (can defer)** Mission types as catalog manifest templates; the first five names.
- **RS.6 (can defer)** The assistant as a requester: does it talk to the coordinator skill or to a
  narrower "launch a named mission type" surface? (Parking lot unless it changes K.)

Drift check: RS serves comprehensibility and obligations; anything in it that is a product
decision rather than a Mission Control contract goes to the parking lot with the owner's words.

### Sitting III: linked workflows, parallelism, lifecycle and review gates, proof scope, the surface, the order

| Round | Source | Decisions | Gates |
| --- | --- | --- | --- |
| R5 linked workflows | OWNER-INTERVIEW §5 | R5.1-R5.4 | G |
| R6 parallelism and workers | OWNER-INTERVIEW §5 | R6.1-R6.4 | H |
| R7 lifecycle, tracing and controls on obligations | OWNER-INTERVIEW §5 | R7.1-R7.3 | F |
| HR0..HR9 review gates | the supplement §12 | HG-D1..D24 | R |
| **RP proof and refinement scope** (new) | §2.2 below | RP.1-RP.4 | P (confirms after the fact what P took on; before it if sitting III runs before P) |
| R8 retrieval surface and the skill | OWNER-INTERVIEW §5, CS §7 | CS-D1..D14, R8.1-R8.4 | I |
| R9 the sequence | OWNER-INTERVIEW §5 | R9.1-R9.3 | the rest |

Sitting III may be split in two (R5, R6, R7, HR; then RP, R8, R9). It runs after T2-1 so that R7,
HR and RP speak from a live run with obligations.

### 2.2 RP. Proof and refinement scope (new round)

Context: the owner's "much work has been done, I'm talking about proof and refinement". The
tracing sprint left these open (TR P11; ledger Stage 2 and Stage 3 honest lists; ADR-0055 and
ADR-0057 "known limits"). Card P below takes the first group by default; RP confirms the split.

| Group | Items | Default |
| --- | --- | --- |
| P takes | the degradation writer and pins (TR-D17: tombstones, `restore_level` lowering, pins for live fork seeds); the snapshot trigger set and the sandbox snapshot primitive (K11, DP-D12); `mc.state_as_of.v2` with three facets (DP-D13); a live retention run (`expire` on a projected run, placeholders shown); the describe matrix cells Stage 2 proved, shipped in release 1.4.5 with OC-1's migration; F-S2-11's live re-proof (a provider failure mid-turn keeps usage and points); the `external.openai` budget dimension never charged by this lane; `run transcript` read end to end on the T2-1 run with `--by stage`, `--by step`, `--point`, bodies downloaded | **P** |
| P or F | the effect-admission orphaned fence (a cancel never journaled denies effects forever; `test_stop_fence.py:71` holds the current rule); the generic outbox relay for chains and the projection (clean-code item 1); `family_unit_facts` and `point_frames` out of the adapter and router | **F** unless T2-1 trips them |
| Later | a paid replay (TR-D11 keeps replay a dry run); Cursor Cloud fork restore; forks at an older cycle above 0 (richer snapshot); other lanes' `model_request` observers; the Agent Server's Postgres edition | per provider sprint |

Questions:

- **RP.1 (must)** Confirm the "P takes" group, or move items.
- **RP.2 (must)** Retention: run `expire` live on the T2-1 run's deltas and read the placeholders,
  or prove on T0 only? (Recommendation: live; it costs nothing but time.)
- **RP.3 (can defer)** Replay stays a dry run (TR-D11); confirm.
- **RP.4 (can defer)** The per-run workspace view (`run workspace RUN`, R8.4) in P or in I?
  (Recommendation: I; P proves the reads it would materialize.)

## 3. The sprint cards

Every card is the skeleton of its `SESSION-<SPRINT>.md`, which the sitting that gates it writes
in full. "Rests on" names the decisions that must be answered first; "Proves" names fixtures in
the Stage 2 style (transcript and mission files under `.scratch/<sprint>/<fixture>/<run id>/`).
Spend follows PROCESS §1.3: at most 15 USD per session, models named by the owner.

### A. Deep Agents upgrade

- **Goal (owner's words):** *"Stay up to date on new tools like Deep Agents so that we are
  utilizing the latest features."* The 0.7.30 stack (langchain 1.4.7, langgraph 1.2.16,
  langchain-openai 1.7.2); the DeltaChannel fork and resume fixes the precise fork depends on; the
  0.7.25 permission and symlink fix.
- **Inputs:** [DEEP-AGENTS-SURFACE-2026-10-22.md](../../../provider-consolidation-2026-10/providers/deep_agents/DEEP-AGENTS-SURFACE-2026-10-22.md)
  §1 and "Implications"; OC §5; the ledger's Stage 3 entry (the seed head reading a delta
  channel's pending writes).
- **Rests on:** R3.8; R2.5 provisionally (never attach the stock async middleware;
  `notify_parent=False`).
- **Builds:** the bump (owner executes, `uv` from `platform/mission-control`); the 0.7.30 behaviour
  deltas guarded; describe pins; the recovery and fork suites green; the surface block refreshed.
- **Proves:** FX-DA-POINTS, FX-DA-POINTS-SG, FX-DA-FORK, FX-DA-INJECT and every FX-TR fixture green
  on T0; one T2 fork re-proof (under 1 USD) that the seed head no longer reads pending delta
  writes.
- **Non-goals:** any new middleware selection (that is B).
- **Size and spend:** 1 session; under 2 USD.

### OC-1. Obligations, submission, fulfillment, promotion

- **Goal:** *"Output contract types with enforcement and checking [...] a submission process if one
  is needed; obligation fulfillment as one of the most critical pieces of the system."*
- **Inputs:** OC whole, especially §3 and §6 row OC-1; `AUDIT-OUTPUT-TRANSFER-2026-10-22.md`
  (every `file:line`); the supplement §4 (so the kind set leaves room for `domain_effect`
  without building it); CS §3 and CS-D10 (`run outputs`).
- **Rests on:** OC-D1..D7, D14, D19..D21, D25, D26 (R1); DP-D3 (RA.3); OC-D22 sync part (R2.1, or
  a stated assumption if sitting II has not run).
- **Builds:** `Obligation` and the kinds (`domain/programs/obligations.py`, `mc.obligation.v1`,
  with the family enum including `domain` but no checker yet); manifest superset and lowering on
  today's node schema; `submit_output` and the `output_submitted`, `rejected_submission` frames;
  declared-path collection; `check_fulfillment` and `fulfillment_service`; the
  `obligation_fulfillment` table, artifact promotion with `producer_point_ref` and the immutability
  trigger, the proved describe cells, all in **release 1.4.5** (owner executes); the §3.6 fixes
  (registered refs win first); `run outputs`, `run artifact get`; the in-turn reminder (OC-D21).
- **Proves:** FX-OC-OUTPUT and FX-OC-CUMULATIVE as OC §6 states them; the sync-subagent obligation
  fixture if R2.1 is answered.
- **Non-goals:** transfer (OC-2), cycles (OC-3), `domain_effect` checking (K), the configuration
  language (B).
- **Size and spend:** 2 sessions; T0 only, 0 USD.

### B. Agent configuration language, lane features, model tools, hooks

- **Goal:** *"Resolve the language we use as well as the code structure we choose for the general
  + provider specific agent capabilities and configurations."*
- **Inputs:** OWNER-INTERVIEW R3 (two axes, three layers, the code structure); the surface sheet's
  catalog; PROCESS §2.
- **Rests on:** R3.1-R3.7; OC-D17, OC-D24.
- **Builds:** `mc.agent_configuration.v1`; the lane-feature registry and the first features (todo
  list, context editing and summarization knobs, call limits, filesystem permissions); the
  model-tool registry (OpenAI `web_search`, `file_search`) recorded as `server_tool_call` frames;
  hooks on Deep Agents (lift the `409`); the context schema as identity source and the three
  `mc_*` channels; obligations lifted from `outputs:` on nodes into `agents:` with no semantic
  change; describe rows and receipts generated from the registries.
- **Proves:** FX-B-FEATURES: a manifest selecting the todo list and call limits runs on T0 with the
  receipt naming each; a model tool recorded as a frame on one T2 call (under 1 USD).
- **Non-goals:** dynamic subagents (after OC-2), the generated workspace (I).
- **Size and spend:** 2 sessions; under 2 USD.

### OC-2. Transfer policy, materialization, dependency kinds, subagent transfer

- **Goal:** *"Don't we want precision in context transfer: providing and referencing the most
  important final outputs to the next session but also deeper storage and history."*
- **Inputs:** OC §4; the supplement §4 (domain deliverables as references with subjects, so the
  policy's `source_kind` covers it); OWNER-INTERVIEW R1b and R2 (T6/T7).
- **Rests on:** OC-D8, D9, D15, D16, D18; R2.4; DP-D10 if RD has run.
- **Builds:** `transfer_policy.py` with `HEURISTICS` as data; `materialization_service.py` and the
  backend port; `state.json`, `obligations.json`, `/outputs/<obligation>/`; `mission_fetch` and
  the fetch commands; released-by correction and `release_kind`; lowering of `any`, quorum, the
  classes, named outputs, Provisional Binding, `conditional`; `transferred_from` and
  `transfer_planned`; the subagent views T6 and T7; `run inputs`.
- **Proves:** FX-OC-TRANSFER, FX-OC-ANY, FX-OC-PROVISIONAL (OC §6); FX-OC-SUBVIEW: a sync child
  receives the parent's `state.json` and the listed inputs and nothing else.
- **Non-goals:** cycles and iterations (OC-3), chains (G).
- **Size and spend:** 2 sessions; T0, 0 USD.

### OC-3. Cycles and the Goal Loop

- **Goal:** *"How do stages that have cycles pass across cycles? How do goal directed iterations
  pass all necessary context to the next iteration?"*
- **Inputs:** OC §4.4, §4.5; the Stage 2 transcripts (cycle 1 rewrote from S1; no handoff at any
  iteration).
- **Rests on:** OC-D10..D14.
- **Builds:** the authorable `cycle:` block; K05 deliveries; the progress observation; the governed
  cap with `on_cap`; K04 typed findings; `handoff` as a required obligation with `invariants`;
  iteration deliverables under `/inputs/iterations/<n>/`; K02 seed-from-point rollover; the
  hydrator wired or deleted (OC-D13).
- **Proves:** FX-OC-CYCLE, FX-OC-ITERATION, FX-OC-ROLLOVER (OC §6).
- **Size and spend:** 1-2 sessions; T0, 0 USD.

### T2-1. The vision mission, live

- **Goal:** one mission exercising obligations, transfer, cycles and a verdict, read end to end.
- **The mission:** two `document` reports in S1 and S2 with `evidence_backed`, a `file_artifact`
  PDF in S3 derived from them, a cycling S2, a `verdict` review in S4 (OC §6, the T2 proof).
- **Rests on:** OC-1..OC-3 merged; the owner names the models (Sol and Luna as in Stage 2).
- **Proves:** every fulfillment row, every transfer plan, every point and the Transcript files
  under `.scratch/t2-1/`; spend recorded per call.
- **Spend:** under 15 USD, intent under 5.

### P. Proof and refinement: tracing, Transcript, state, retention

- **Goal:** *"Much work has been done; I'm talking about proof and refinement."*
- **Inputs:** TR P11; ADR-0054..0057 "known limits"; the ledger's Stage 2 and Stage 3 honest lists;
  the supplement §6; the T2-1 files.
- **Rests on:** DP-D12, DP-D13 (RA.4, RA.5); RP.1-RP.3 if sitting III has run, else the "P takes"
  group as a stated assumption.
- **Builds:** the degradation writer and pins (TR-D17); the snapshot trigger set and the sandbox
  snapshot primitive on the docker backend; `mc.state_as_of.v2`; a live retention pass; the F-S2-11
  re-proof; the `external.openai` dimension charged; the T2-1 Transcript read every way the CLI
  offers, with defects fixed; a release 1.4.6 only if the tombstone writer needs columns the 1.4.4
  vocabulary lacks.
- **Proves:** FX-P-ASOF: one point answers agent context, filesystem and the as-of table facts in
  one read; FX-P-TRIGGERS: a submission and a governed effect each produce a snapshot and an
  unchanged digest produces none; FX-P-RETAIN: expiry leaves placeholders and the projection stays
  current.
- **Size and spend:** 1-2 sessions; under 2 USD.

### K. The domain family and the Knowledge Services binding

- **Goal:** *"How do we offer something automated or extensible that deterministically relates
  mission control to the entity."*
- **Inputs:** the supplement whole; `docs/knowledge/knowledge-services.md`;
  `mission-control-general/.../expansion/KNOWLEDGE-SERVICES.md` (deleted 2026-11-01; last at `66185d2e`); biotech's `intent-v2-fields.md`,
  `plan-receipt-guide.md`, `apply-v2.ts`, OD-06, OD-07, OD-45.
- **Rests on:** DP-D4..D11, D14 (RD); RS.1, RS.2, RS.4.
- **Builds:** the `domain_effect` checker and the receipt-form submission; auto-attribution by
  capability; the minimal `knowledge.*` binding (`ingestion_apply`, `receipt_get`,
  `verify_result`, `run_effects`) with the `mc.knowledge_request.v1` wrapper and the `context.run`
  fill from the context schema; receipts as external artifacts with `fulfills`; the effect summary
  projection; domain deliverables as references with subjects; the disposition ladder; the chain
  release's lineage intent; release 1.4.7 for the disposition and summary rows (owner executes).
- **Proves:** FX-K-RECEIPT on T0 against a stubbed executor; FX-K-LIVE on T1 against biotech's
  executor on the local Neo4j test stack (`scripts/neo4j-test.sh up`): one stage ingests two
  companies, the receipt fulfills the obligation, a uid resolves back to the point.
- **Non-goals:** the AI Engineer Postgres adapter; a Neo4j writer in the kernel; publication gates.
- **Size and spend:** 2 sessions; 0 USD on T0/T1.

### R. Review Gates and steering

- **Goal:** *"This is so important for me to be part of the process and to guide these missions."*
- **Inputs and plan:** the human review gates supplement, HG-1..HG-5 and RV, after HR0..HR9.
- **Rests on:** HG-D1..D24.
- **Note:** T10 is a transfer point of OC-2's policy, so R follows OC-2; its revision service
  touches OC-3's cycle path.

### F. Lifecycle and observability on obligations

- **Goal:** *"Tracing, observability and lifecycle inspection and controls."*
- **Builds (strawman, R7):** `obligation_fulfilled`, `output_submitted`, `transfer_planned` as public
  events with `unit_key`, `point_ref` and location; `run inspect` per-unit "2 of 3 obligations";
  interventions targeting an obligation; fork from a fulfillment row; async-subagent admission
  (WP-S4) and communication obligations (OC-D23); the orphaned-fence fix; the Transcript stage
  group showing released-by, transferred items and fulfillment together.
- **Rests on:** R7.1-R7.3; OC-D23.

### G. Linked workflows on obligations

- **Builds (strawman, R5):** release by obligation fulfillment; chain links as transfer point T9
  through the same policy; supplied deliverables as promoted artifacts; lineage across missions,
  including the trusted mission-start intent (DP-D11); GD→GD and SG→GD on Deep Agents.
- **Rests on:** R5.1-R5.4.

### H. Parallelism and workers

- **Builds (strawman, R6):** the concurrency default; the `cognitive` worker role; activity slots;
  workspace isolation for parallel writers on the Deep Agents backends; `fan_out` implemented or
  refused at compile; a live proof of two stages on two workers.
- **Rests on:** R6.1-R6.4. Independent of C-G; recommended as soon as a second slot exists.

### I. Retrieval surface and the Mission Control skill

- **Builds (strawman, R8, CS):** the generated workspace from the registries, the noun-verb CLI
  grammar with one-release aliases, the skill bundles, `run workspace RUN`, the cards for
  obligations, transfer points, lane features, model tools, mission types (RS.5).
- **Rests on:** R8.1-R8.4, CS-D1..D14.

### T2-2. The biotech scenario, live

- **The mission:** the supplement §5: companies, executives, trials, sources with chunks, evidence
  reports, a synthesis stage; read back with `run outputs`, one uid resolved to a point, one
  source resolved to its bytes.
- **Rests on:** K, R (one Review Gate before synthesis), F.
- **Spend:** under 15 USD.

## 4. Where the ledger and the specifications change

| Sprint | Ledger entry | Specification folded | Release |
| --- | --- | --- | --- |
| A | Turn 8 | surface sheet refreshed | none |
| OC-1 | Turn 9 | OC §8 answers recorded; GLOSSARY §2 terms | 1.4.5 |
| B | Turn 10 | OWNER-INTERVIEW R3 answers; new concept `agent-configuration` | none |
| OC-2, OC-3 | Turns 11, 12 | OC §4 answers | none |
| P | Turn 13 | TRACING-PROPOSAL P8a completed; ADR-0055 known limits closed | 1.4.6 if needed |
| K | Turn 14 | the supplement's DP answers; `knowledge-services` concept rewritten | 1.4.7 |

ADR candidates accumulate as OC §9 lists them, plus: the four-state authority table and the
receipt bridge; the domain output family; snapshot triggers as data; deliverable disposition.

## 5. Decision log (to fill, by sitting)

From sitting I on, the record is the sitting's answers file under `answers/` (ledger rows IA-05 and
after); this table keeps one line per decision pointing to it.

| Date | Sitting | Id | Answer | Consequence |
| --- | --- | --- | --- | --- |
| | | | | |

## 6. Parking lot

| Date | Raised in | The owner's words | Where it goes |
| --- | --- | --- | --- |
| 2026-10-23 | the architecture call | the service map (user, content, evidence and report, application and product APIs, the assistant) | RS, sitting II |

## 7. The first session: interview sitting I (copy into the first message)

We are in the provider consolidation program, after tracing Stage 3 (merged to `main`,
`a7a8b0da`). This session is **interview sitting I** of
`docs/specs/archive/provider-consolidation-2026-10/proposals/SPRINT-SEQUENCE-2026-10-23.md` §2: rounds R0, RA, R1,
R1b and R3.8. Work in `platform/mission-control` on a docs branch `docs/interview-sitting-1`;
commit docs only, when I say. Follow `PROCESS.md` §1.2 for how to ask, and
`OWNER-INTERVIEW-2026-10-22.md` §4.3, §4.4 and §7 for how a round runs and what the interviewer
must not do. Build nothing.

1. **Read, in this order:** `SPRINT-SEQUENCE-2026-10-23.md` whole; `OWNER-INTERVIEW-2026-10-22.md`
   §0-§5 (rounds R0, R1, R1b, R3.8 only); the output-contracts specification
   `docs/specs/archive/provider-consolidation-2026-10/specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md` §0-§4 and §8; the
   supplement `docs/specs/archive/provider-consolidation-2026-10/proposals/DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md` whole;
   the ledger `providers/deep_agents/CHANGES.md` Stage 2 §4b observations and the Stage 3 deferred
   list; `DEEP-AGENTS-SURFACE-2026-10-22.md` §1 and "Implications".
2. **Re-verify** against live code, citing `file:line`, the rows of OWNER-INTERVIEW §2.2 that R1 and
   R1b rest on (stage outputs, `output_refs`, cycle and iteration transfer, version) and the
   supplement's §2 and §3.2 tables. Mark drift in those tables before the first question.
3. **Open the answers file first:** `python docs/tools/program_ledger.py new-answers --topic
   DEEP-AGENTS --sitting I --interview docs/specs/archive/provider-consolidation-2026-10/interview-instructions/OWNER-INTERVIEW-2026-10-22.md`,
   and add the row it prints to `LEDGER.md` (IA-05). **Run the rounds** R0, RA, R1, R1b, R3.8 in that order: context in my terms (two minutes of
   reading), at most four questions per batch with the recommendation first and what each option
   changes later, the restated mental model after each round (a manifest fragment, a command, what
   I will see), the record in the answers file (my words in *Answer*, your reading in *What it
   changes*, the date, and where each decision becomes and is folded), and the drift check
   against the five properties.
4. **After the rounds:** fold the answers into OC §8 and the supplement §8 (one line per decision,
   dated), recording each fold in the answers file's *Becomes* and *Folded* columns; point
   OWNER-INTERVIEW §8 and §5 here to it; set the file `final` when every decision has both; write `providers/deep_agents/SESSION-A.md` and
   `providers/deep_agents/SESSION-OC-1.md` in full from the cards in §3 (goal in my words, inputs,
   the decisions they rest on with my answers, builds, proves, non-goals, host facts copied from
   the specification's session instruction); move
   `platform/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md` to
   `providers/deep_agents/` and correct its relative links; update `LEDGER.md` (rows IA-01, IA-02, IA-05,
   PR-05, SE-04, SE-05) and offer to file the `OVE` issues for sprints A and OC-1 with a
   `## Provenance` section (ask me first; nothing earlier is back-filled); run
   `python docs/tools/agents_docs_index.py` and `python docs/tools/program_ledger.py check`.
5. **End with:** the decision log, anything deferred with its stated assumption, the two session
   files' paths, and the one command I will run first in sprint A.

**Host facts** are those of the specification's session instruction (Windows 11, one heavy job at
a time, the disposable Postgres 17 container `mc-ft-disposable-pg17`, credentials by name only).
No paid run happens in this session.
