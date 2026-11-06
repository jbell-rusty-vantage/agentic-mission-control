---
type: Specification
title: "Provider consolidation program: proving Goal Directed and Stage Graph workflows lane by lane"
description: "How Mission Control moves, one provider at a time, from declared lane capability to proven capability: the sixteen capabilities every lane must prove for Goal Directed and Stage Graph workflows, the kernel work that comes first, the recommended design positions for time travel, sandboxes, context transfer, human control and mutation, the lane-parameterized fixture suite, the per-provider sprint loop and the owner decisions needed. Drafted 2026-10-19 from the baseline audit."
tags: [mission-control, specifications, providers, consolidation, program, fixtures]
---

# Provider consolidation program

<!-- final-output-contracts-2026-10-26 -->
**Current output/context sprint (2026-10-26):** [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) and the [final Sprint OC packet](sprint-oc/README.md) are ready for implementation. Start [KICKOFF](../archive/provider-consolidation-2026-10/sessions/KICKOFF.md). Five accepted target ADRs and 31 issues replace the interview-first route; new runtime qualification remains unrun. Unrelated provider-program decisions remain unchanged.


**Status: draft for owner review (2026-10-19), refreshed 2026-10-20.** Run 2 of the
materialization-observation sprint is finished and integrated on `main`. On 2026-10-20 the owner
chose to proceed **one provider at a time** together with Mission Control, which is this program's
shape. Decisions D1–D9 (§9): D1 (accept the program) is overtaken by events, the program has run since 2026-10-19; D2–D9 are tracked as open or answered in the [decisions concept](../../knowledge/decisions.md#open-decisions-provider-consolidation-readme-section-9). Each sprint starts on its own branch from `main`.

| Read | For |
| --- | --- |
| [LEDGER.md](LEDGER.md) | **Start here.** Where every proposal, document, spec, issue, interview and session stands, with its status, Linear id and next step; finished documents are under `archive/` and keep their row. Convention: [program-workspace.md](../../agents/program-workspace.md) |
| [BASELINE-2026-10-19.md](../archive/provider-consolidation-2026-10/docs/BASELINE-2026-10-19.md) | What the code does today: citations, the per-lane matrix with Run 2 live evidence, a code map (§12) and each sprint's starting position (§13) |
| [RUN-2-CARRY-FORWARD.md](RUN-2-CARRY-FORWARD.md) | Everything Run 2 left open: parked runs, 25 findings (RF-01..25), the 64 open issues grouped by sprint, fixtures, holds, and how to restart live work |
| [archive/specs/TRACING-AND-OBSERVABILITY.md](../archive/provider-consolidation-2026-10/specs/TRACING-AND-OBSERVABILITY.md) | *Archived 2026-10-23.* Specification candidate and session brief (2026-10-21): the verified lifecycle saving, read, inspect and fork functionality per workflow type with Deep Agents cognition inside, the owner's fork scenario (Stage 2 cycle 2, inject, new run) traced and found mis-targeted, the LangGraph saver going remote, the Mission Transcript and precise-fork targets, the research, exploration and reasoning the proposal must contain, its acceptance criteria, TR-G1..15, TR-D1..17 (D17: pruning by degradation, completed later) and the FX-TR proofs; runs before the queued output-contracts and context-transfer session |
| [TRACING-PROPOSAL.md](../archive/provider-consolidation-2026-10/proposals/TRACING-PROPOSAL.md) | The proposal that answers the brief (2026-10-21, for owner confirmation): audit corrections, the capture model per lifecycle moment for both families, release 1.4.4 migrations, the writers as deep modules, the Transcript read model with a worked example, the precise fork for Stage Graph and Goal Directed, the remote-saver outcomes, determinism table, FX-TR proofs, TR-D1..19 with the recorded answers, and the owner's three stages (implementation with minimal verification over work packages WP-TR-1..5; real fixtures on a 10 USD budget; adversarial review, clean code, tests and documentation) |
| [archive/sessions/SESSION-STAGE-1.md](../archive/provider-consolidation-2026-10/sessions/SESSION-STAGE-1.md) | *Archived 2026-10-23.* The instruction for Stage 1 (fixed by the owner 2026-10-21, every decision closed): one session over WP-TR-1..5 with a commit per package: release 1.4.4, settlement transaction, reconciler, joinable events, lifecycle writers into the existing completion tables, capture completeness (model-input callback, capture profiles, frame-body scheme, hook ports, subagent points, environment manifest), transcript v2 with the settlement-triggered projection, replay, retention classes, the precise fork with one message field, saver outcomes; subagents on independent streams |
| This page | How the program runs, what each lane must prove, the kernel work, design positions and fixtures |
| [PROCESS.md](PROCESS.md) | How a session on this program works (orient, audit, cross-reference, plan, **confirm with the owner**, build, prove, document, hand off) and the discriminator-and-router rule for contracts that become provider-specific |
| [docs/specs/archive/provider-consolidation-2026-10/docs/AUDIT.md](../archive/provider-consolidation-2026-10/docs/AUDIT.md), [DESIGN.md](providers/deep_agents/DESIGN.md), [CHANGES.md](providers/deep_agents/CHANGES.md) | P1 phase A audit with the 2026-10-20 offline live trace, the phase B design draft (shared configuration, provider options, the cognition coordinate and fork-from-checkpoint, work packages WP-0..8), and the cumulative change ledger with the API sequence |
| [docs/specs/archive/provider-consolidation-2026-10/specs/SUBAGENTS.md](../archive/provider-consolidation-2026-10/specs/SUBAGENTS.md), [ASYNC-SUBAGENTS-EXPLAINED.md](../archive/provider-consolidation-2026-10/docs/ASYNC-SUBAGENTS-EXPLAINED.md), [SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md](../archive/provider-consolidation-2026-10/specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md) | The subagent part of P1 (child capabilities, async children on the Agent Server, the subagent routing decision), the owner's walk-through of the async path (three layers, what travels, what the server serves), and the instruction for the queued output-contracts and context-transfer session (sequence not fixed; tracing and observability comes first) |

## 1. Why this program, and how it differs from the running sprint

The running sprint spread work across every provider at once to reach "declared" capability. The
baseline shows the result: nine lane profiles whose describe matrices mostly say `native`, one lane
with real live evidence (`claude_agent_sdk`, S0-01 and F1 run k), and a set of **lane-neutral
kernel gaps** that no single-lane sprint would have found. Examples: a Goal Loop that hard-fails past
100k tokens, an `outputs/` folder that is never cleaned, forks that can only start at the current head,
and no way to read state "as of" a past turn.

This program inverts the approach:

1. **One provider at a time**, in the owner's priority order, each a mini-sprint (two when Goal
   Directed and Stage Graph need separate proof).
2. **The workflow is the unit of proof.** A lane is not "done" when its adapter compiles. It is done
   when Goal Directed and Stage Graph fixtures run on it end to end with every required capability
   observed and recorded.
3. **Kernel first, then lanes.** Lane-neutral defects are fixed once, before the first provider
   sprint, so later lanes inherit them instead of rediscovering them.
4. **Honest declarations.** Each sprint ends by making the lane's describe matrix say exactly what was
   proven. "native" is earned by a fixture, not asserted.

## 2. Provider order

| Sprint | Lane profile(s) | Why at this position |
| --- | --- | --- |
| P1 | `deep_agents` | We own the loop and LangGraph gives a native checkpoint per turn. It is the best lane to build the kernel against (time travel, fork, HITL interrupts, subagent state). |
| P2 | `claude_managed` | The provider owns the loop and sandbox. This proves the remote-session base (ADR 0052) and hosted HITL. |
| P3 | `cursor_local`, `cursor_cloud` | Two placements on one SDK. The local lane needs a Linux/WSL worker with memory headroom. |
| P4 | `codex_agents` (OpenAI Agents API) | Shares the remote-session base with P2, so most hosted machinery is already proven by then. |
| P5 | `claude_agent_sdk`, `claude_cloud` | The local lane already has the most live evidence. "Cloud" needs an owner decision first (§9 D3). |
| P6 | `codex`, `codex_cloud` | The local lane has native compaction, `thread/fork` and `turn/steer` available. Cloud has the same decision as P5. |

**OpenAI note.** Mission Control supports only the hosted Agents API (lane `codex_agents`). It does not
use the `openai-agents` Python package (baseline §10). If an SDK-run lane is wanted, it is a new lane
profile and a new decision (§9 D4), not part of P4.

## 3. The capability catalog

These are the sixteen capabilities every lane must prove, numbered so that proof records, issues and
fixtures can reference them. "Both programs" means Goal Directed (GD) and Stage Graph (SG).

| ID | Capability | Proven when |
| --- | --- | --- |
| C01 | **Seed and spawn** with full agent configuration | A run starts on the lane with instructions (additive over repo AGENTS.md), MCP servers (stdio where the lane allows, remote), skills, plugins, the sandbox/environment, provider subagents, the model, a compaction/token-threshold policy and a continuation policy. Each item is observed in use inside the agent, not just written to disk. |
| C02 | **GD iteration progression** | ≥3 iterations. One iteration crosses the token threshold, and continuation produces a new session generation whose packet carries the compacted state. The verifier's findings reach the next executor. Sandbox policy is applied as declared. |
| C03 | **SG stage progression** | The same as C02, applied to stages, including a stage whose session crosses the threshold mid-stage. |
| C04 | **Dependent-stage transfer** | The downstream stage receives schema-validated outputs, file artifacts and declared workspace state deterministically: digests match, nothing stale is collected, and nothing from a sibling or earlier attempt leaks in. |
| C05 | **Cyclic stage continuation and handoff** | A cycling stage re-runs with its prior results and unmet obligations delivered. It stops by predicate or cap as a governed outcome, then hands its accepted result to its dependents. |
| C06 | **Retrieve, time travel and fork** | State is read through the API at (iteration, turn) coordinates, including the transcript, frames, workspace and budget as of that point. A fork from "turn K of iteration 2" runs, with the lane's best restore level (§6.1) recorded. |
| C07 | **Intervene** | Queue, add_context, interrupt-and-inject, cancel and pause, each with an honest receipt. A real file is injected into the sandbox with a reference in context. An inject aimed at a settled node is refused with a reason. |
| C08 | **Durable human control** | Approvals for native tools, MCP tools, custom tools and the session level survive a worker restart, honour a configured timeout policy (not silent deny), and use configured reviewers. No in-memory state carries correctness. |
| C09 | **Human Gate checkpoint node** | A stage ends at a review gate. The reviewer approves, requests changes (which reach the remediation stage) or denies, durably. *Deferrable to its own sprint.* |
| C10 | **Subagent configuration** | Provider subagents are configured with their own instructions, model, tools, skills and MCP (and sandbox where the lane allows), and are observed doing so. |
| C11 | **Subagent state to parent** | The parent and the coordinator can read subagent lifecycle, outputs and usage. The lineage graph says how faithfully each was observed. |
| C12 | **Sandbox and runtime provisioning** | Python/Node runtimes and dependencies are installed (not just files written) by the Environment Kit route the lane supports. A failure is detected before the first agent turn. |
| C13 | **Model selection and defaults** | The model is chosen per agent and per subagent. "default" resolves through a declared installation default per lane, and the resolution is recorded on the run. |
| C14 | **Coordinator peek and act** | A coordinator, including an agent inside another run, reads current stage/iteration, latest turns, tool calls, subagents, files and budget live, then acts (inject, cancel, fork, spawn). |
| C15 | **Linked-run context transfer** | GD→GD and SG→GD links transfer context, both on the same lane and across providers (e.g. `claude_managed` → `codex_agents`), under a default policy. |
| C16 | **Mutate a running workflow** | An approved revision changes instructions, model, MCP/skills or the stage set of a live run at a defined boundary, with lineage recorded. Out-of-policy changes route to a fork. |

## 4. Program shape

```text
Sprint 0  Foundation ── kernel fixes (K01–K21) · fixture harness · proof ledger · design positions
   │
   ├─ P1 deep_agents ───────── A audit · B design · C build · D prove GD · D' prove SG · E close
   ├─ P2 claude_managed ─────── same loop
   ├─ P3 cursor_local/cloud ─── same loop, per placement
   ├─ P4 codex_agents ───────── same loop
   ├─ P5 claude local/cloud ─── same loop (cloud after decision D3)
   └─ P6 codex local/cloud ──── same loop (cloud after decision D3)
Cross-lane closers: C15 cross-provider links after P2+P4 · C09 Human Gate sprint when scheduled
```

Sprints run strictly in sequence. Inside a sprint, independent streams may run in parallel, keeping
the host memory limit in mind (one heavy job at a time on this laptop).

### 4.1 Sprint 0: Foundation

Sprint 0 delivers what every lane needs before any lane can pass a fixture.

1. **Kernel fixes** (§5). These are lane-neutral and proven with the offline fake lane plus Postgres and
   local Temporal.
2. **Fixture harness** (§7). One lane-parameterized suite: `fixtures/consolidation/<fixture>.mission.yml`
   plus an assertion runner that reads only the public API, so the proof matches what a coordinator
   could see.
3. **Proof ledger.** `CAPABILITY-LEDGER.json` in this packet has one row per (lane, program, capability):
   status, fixture run ids, receipts, cost, and the describe cell it justifies. Describe matrices are
   updated **from** the ledger at sprint close.
4. **Design positions** (§6) accepted or amended by the owner, recorded as ADRs (several amend proposed
   ADRs 0027, 0037, 0039, 0041 and 0049).

### 4.2 The provider sprint loop

Every provider sprint runs the same five phases and leaves the same files in
`providers/<lane>/`.

| Phase | Output | Exit criterion |
| --- | --- | --- |
| **A. Audit** | `AUDIT.md`: re-verify the baseline rows for this lane against `main`, plus a **provider fact sheet** from current vendor docs covering session lifecycle, resume/fork/rewind, compaction, mid-turn messaging, HITL hooks, subagents, sandbox images, usage/cost, rate limits and SDK versions | Every C01–C16 row for this lane has a current-state verdict with citations |
| **B. Design** | `DESIGN.md`: per-capability mapping (native, emulated or unsupported, with the reason), the lane's restore level for C06, and its HITL mapping. Owner decisions are listed explicitly | Owner signs off on decisions; unsupported cells are justified |
| **C. Build** | Issues `PC-<lane>-NN` in Linear (project Mission Control) and code on a sprint branch, with reviewed commits | `make check` green; offline fixture tier green for this lane |
| **D. Prove** | Fixture runs in tier order (§7.2), first for GD and then for SG. Receipts go under private session evidence; digests go in the ledger | Every required cell is `proven` or has an owner-accepted deferral |
| **E. Close** | Ledger rows, describe matrix flipped from the ledger, knowledge docs (`docs/knowledge/<lane>.md`) corrected, `CLOSE.md` with spend and open findings | Ledger, describe and docs agree |

A lane may need two passes of C→D: GD first, because it exercises C01–C02 and C06–C08 with the fewest
moving parts, then SG for C03–C05.

## 5. Kernel work (Sprint 0)

These items come from the baseline and are not tied to any one lane. Severity follows the baseline.

| ID | Item | Capability | Severity |
| --- | --- | --- | --- |
| K01 | Each operation starts with a clean `outputs/`. Prior outputs are archived into custody and excluded from collection. Fixes the run h/i defect and stops the GD verifier collecting executor files | C02–C04 | critical |
| K02 | Make the GD token threshold and `max_rollovers` authorable in the manifest with sane defaults. Remove the hard-coded `max_rollovers=0`. Crossing the threshold must trigger continuation, never a hard failure | C02 | critical |
| K03 | Separate **session generation** from **iteration**. Continuation (ADR 0041) can roll a session inside an iteration or stage at a turn boundary under pressure, not only when a turn ends without outputs | C02, C03 | critical |
| K04 | Deliver verifier findings to the next executor's packet. Refuse, rather than silently reuse, a missing handoff | C02 | high |
| K05 | Deliver `prior_result_refs` and `unmet_obligation_refs` to a re-run cycling stage. Turn the cycle cap into a governed outcome. Add Revisit Region predicates (`until`, `until_no_progress`) | C05 | high |
| K06 | Allow a Goal Loop as a Stage Graph stage (a nested family), so a goal-directed or "infinite" stage can feed dependents | C05 | high |
| K07 | Fail on unresolvable output refs instead of degrading them to zero-byte references | C04 | medium |
| K08 | Take an **automatic snapshot at every boundary**: stage settled, verifier settled, and session generation rollover | C06 | critical |
| K09 | Add **time coordinates**: `turn_id` on frames, an interrupted-turn row, and filters for iteration, stage cycle and turn. Add a read-as-of API (`until` cursor plus a state projection at a past point) on HTTP, MCP and CLI | C06 | critical |
| K10 | Add a fork-boundary kind for **turn K** of any unit, with liability, budget and effect fencing. Snapshots pin their own lease reference instead of "latest" | C06 | high |
| K11 | Add a per-turn workspace checkpoint (git tree id per turn on lease lanes) keyed to `turn_id`. Pin frame retention for forkable runs | C06 | high |
| K12 | Approval timeout policy: `keep_waiting`, `deny` or `escalate` per mission, defaulting to keep_waiting with a Human Task deadline. Reviewers come from the mission, not a worker setting | C08 | critical |
| K13 | Expire with a receipt any inject aimed at a settled node. Pause receipts must report what actually happened (boundary vs tool gate) | C07 | high |
| K14 | **Artifact injection**: put a custody artifact into the live sandbox (lease lanes write to `inputs/injected/`; hosted lanes use the provider file API) plus a mandatory context reference, applied at the next turn boundary or by cancel-and-replace | C07 | high |
| K15 | A **unified peek** (`mc.inspection.v2`): current stage/iteration/generation/turn, budget, effects, lineage, recent tool calls and the workspace file list, plus a file-read endpoint. Exposed on HTTP, MCP and CLI | C14 | high |
| K16 | `missionctl wait` token refresh. Reproduce and fix the missed second `review_required` wake | C14 | high |
| K17 | **Revisions on a live run**: the revision proposal → approval → applied-at-boundary path for instructions, model, MCP/skills and adding/removing not-yet-started stages, with lineage. Out-of-policy changes route to a fork | C16 | high (can follow P1) |
| K18 | Fix chain packets so they consult the consumer lane's file support instead of hard-coding a writable workspace. Add a cross-lane transfer policy (§6.6) | C15 | medium |
| K19 | *(added 2026-10-20 from Run 2, proposed)* Deliver `config:` values to the lane's runtime environment, not only to compile (RF-10) | C01 | high |
| K20 | *(added 2026-10-20, proposed)* Recovery hygiene: clean up a cancelled unit's lease (RF-17); stop classifying a pre-create refusal as `in_doubt` (RF-01); add a governed write-off for an unsettled usage reservation and for an `in_doubt` unit with no incident, then apply it to the two Run 2 records left `cancelling` (`eaa586c3`, `7132d2de`; their Temporal workflows were terminated 2026-10-20) | C06, C07 | high |
| K21 | *(added 2026-10-20, proposed)* Tooling: configurable `missionctl` HTTP timeout (RF-16); the 6 pre-existing unit failures (RF-20); the frozenset dump (RF-11); the LS fixture CRLF hash (RF-19); Linux `mypy` on Windows-only modules (RF-24); a default lease root that fits Windows MAX_PATH (RF-25); MO-69 binding digest tool; MO-07 remaining documentation clauses | — | medium |

Deferrable from Sprint 0 with owner agreement: K06 (until P1 SG proof), K17 (until after P2), and
C09 Human Gate enrichment (`request_changes`, remediation target, default answer and a
`missionctl human-task` command).

## 6. Design positions (recommended defaults; owner to accept or amend)

### 6.1 Time travel and fork: one coordinate system, four restore levels

- **Coordinate.** `run → unit (stage@cycle | goal@iteration/role) → session generation → turn_no → frame
  ordinal`. Every read and fork API accepts this coordinate. Postgres is the authority and Temporal
  history is never used to read the past (it continues-as-new).
- **Restore levels.** Each lane declares the highest level it supports, and each fork records the level
  it achieved:

| Level | What a fork from turn K restores | Lanes expected |
| --- | --- | --- |
| R0 boundary | State as of the last settled boundary (exists today) | all |
| R1 packet | R0 plus the transcript up to K, compacted into the fork packet | all with frames |
| R2 workspace | R1 plus files as of turn K (per-turn checkpoint, K11) | lease lanes; cursor_cloud via branch sha |
| R3 native cognition | The provider conversation itself as of K | deep_agents (LangGraph `checkpoint_id`), codex (`thread/fork` plus rollback), claude_agent_sdk (`fork_session`; truncation to K must be proven) |

Hosted lanes (`claude_managed`, `codex_agents`) are expected to stop at R1 unless their fact sheets show
a branch or rewind primitive.

### 6.2 Iteration, session and context

- An **iteration** (GD) or **stage activation** (SG) is a program decision. A **session generation** is a
  context decision. They are independent: an iteration may span several generations.
- Compaction is **native-first** where the lane offers control. Otherwise Mission Control seals a
  checkpoint and starts a new generation from a continuation packet (ADR 0039/0041). The threshold
  policy is authored per agent (soft/hard ratios or absolute tokens), defaults per lane come from the
  catalog, and both are recorded on the run.
- The packet for a new generation or iteration always carries: goal and contract, Loop State, the sealed
  handoff, verifier findings, open obligations, injected instructions/artifacts, and a workspace map.

### 6.3 Sandboxes

- Default lease policy: **one lease per family (run), reused across iterations and stages for the
  executor role**. `outputs/` is clean per operation (K01), and a boundary snapshot is taken (K08).
- The **verifier role gets a read-only view** (a snapshot checkout or a separate lease), never the
  executor's writable tree.
- Stages may declare `reuse: none` for isolation. Their inputs then arrive only through the packet and
  declared workspace transfer (a snapshot of the upstream lease, mounted read-only or merged).
- Agent configuration is re-materialized at every session generation (already true) and checked against
  the binding digest.
- **Runtime installation** is the Environment Kit's job, not the agent's. Local lease lanes need a base
  layer that actually installs runtimes (or a pre-built image); hosted lanes map the kit onto the
  provider image API. The cooperative `mc_prepare` bash route on hosted lanes should become a
  pre-turn, Mission Control-driven step where the provider allows it, so a failed setup is caught
  before the first turn.

### 6.4 Human control

- Every human-in-the-loop decision is a Postgres Human Task bound **before** any wait (already the
  approval broker's model). Provider-native mechanisms are the trigger only: `can_use_tool`, Codex
  approval RPCs, LangGraph `interrupt()`, Managed Agents `always_ask`, Agents API `required_actions`,
  Cursor hooks.
- Gate classes per mission: native tool, MCP tool (per server/tool), custom tool, and session level
  (pause before the next turn). A lane that cannot enforce a required class is refused at admission
  (already implemented: `admit_gate_coverage`).
- Timeout policy and reviewers come from the mission (K12). A timeout never silently becomes a deny
  that cancels work, unless the mission says so.

### 6.5 Subagents

- **Configurable** (C10): whatever the provider allows natively is projected — model, instructions,
  tools, skills, MCP — and anything else is declared degraded at admission. Spawnable "real" subagents
  with their own sandbox and full capability set are Mission Control linked runs or async subordinates,
  delivered later as custom spawning tools (owner deferral).
- **State to parent** (C11): the lineage graph is the single read model, with a fidelity label
  (`full`, `lifecycle_only`, `unavailable`) per child. It is exposed through the unified peek (K15), not
  only Socket.IO.

### 6.6 Linked workflows across providers

- What crosses a link is **lane-neutral**:
  - the accepted outputs and artifacts;
  - a compacted transcript summary (written by Mission Control, not provider-specific);
  - the obligations and acceptance disposition;
  - optionally a workspace snapshot.
- The consumer lane decides how each item materializes: a writable lease gets files; hosted lanes get
  uploads through the provider file API or references.
- Default policy:
  - summary plus artifacts always;
  - workspace snapshot only when both ends are lease lanes, or when the consumer declares a repo binding;
  - never a provider-native conversation handle across providers.

### 6.7 Mutation

- **In-policy** changes, applied at the next boundary as a revision with lineage: instructions, adding
  context, model within the same lane, MCP/skills additions within the catalog, and adding or removing
  stages that have not started.
- **Out-of-policy** changes, refused with a suggestion to fork: changing the lane, removing a running
  stage, or changing acceptance contracts already used.

### 6.8 Coordinator

- One peek contract (K15) for humans, CLI, MCP and agents.
- An agent inside a run gets coordinator powers only through a **delegated, scoped credential**: a
  capability `mc.coordinate` limited to runs it launched or was granted, with rate and depth limits.
  The operator bearer still never enters an environment (ADR 0049 amended).

### 6.9 Model defaults

`default` resolves through an installation-level catalog entry per (lane, role), recorded on the run.
No lane silently falls back. Deep Agents needs a non-OpenAI model factory before Anthropic models can
be default there.

## 7. Fixtures

### 7.1 The suite

Each fixture is a Mission Manifest plus assertions that call only the public API. They are
parameterized by `lane` and `placement`, and the same files run on every lane.

| Fixture | Program | Shape | Proves |
| --- | --- | --- | --- |
| **FX-GD1** seed-and-spawn | GD | 1 iteration; every C01 item configured (a probe MCP server, a probe skill, a probe plugin, a probe subagent, an env kit that installs a pinned Python and Node package) and asserted from agent behaviour | C01, C10, C12, C13 |
| **FX-GD2** long loop | GD | ≥3 iterations, a low token threshold forcing a mid-iteration generation rollover, verifier failing once with findings | C02, C11 |
| **FX-GD3** time travel | GD | Read state at (iteration 2, turn K); fork from there with an instruction patch; assert restore level and divergence | C06 |
| **FX-GD4** controls | GD | queue, add_context with an injected artifact, inject, pause/resume, approval allow/deny/timeout, worker kill and restart mid-turn | C07, C08 |
| **FX-SG1** pipeline | SG | diagnose → patch → review with schema outputs, `reuse: within_run`, one stage crossing the threshold | C03, C04 |
| **FX-SG2** cycle | SG | evaluate stage cycling until a predicate holds, with a dependent consuming the final result; then the cap-hit variant | C05 |
| **FX-SG3** nested loop | SG | a goal-directed stage feeding a downstream stage (after K06) | C05 |
| **FX-SG4** gate | SG | stage ends at a Human Gate; request_changes then approve (C09 sprint) | C09 |
| **FX-CO1** coordinator | GD+SG | a coordinator (CLI, then an agent in a run) peeks live, injects, forks, and spawns a linked run | C14 |
| **FX-LK1** links | GD→GD | same-lane link, then cross-provider link | C15 |
| **FX-MU1** mutation | SG | revise instructions and model mid-run, add a stage; then an out-of-policy change refused | C16 |

### 7.2 Tiers and order

| Tier | Runs against | Purpose | Cost |
| --- | --- | --- | --- |
| T0 offline | fake lane + Postgres + local Temporal | kernel and lane-adapter correctness; runs in `make check`-adjacent CI | none |
| T1 recorded | recorded provider transcripts (replay) | adapter regressions without spend | none |
| T2 local live | real provider, local worker (WSL2 for lease lanes) | the real proof for local lanes | per-sprint ceiling |
| T3 cloud live | real provider, Temporal Cloud and/or the AWS worker | hosted lanes, remote operation | per-sprint ceiling |

A cell is `proven` only at T2 or T3. Every live run records: run id, manifest digest, worker commit,
receipts digests, spend, and the coordinate reads used by the assertions.

### 7.3 Required matrix

All of C01–C08 and C10–C14 are required for every lane at the level its design allows. C06 is required
at the lane's declared restore level. C09, C15 and C16 are required once their sprints or kernel items
land. A lane-level "unsupported" needs an owner-accepted reason in `DESIGN.md`.

## 8. Lane briefs (what each sprint should expect from the baseline)

- **P1 deep_agents.** Strongest native position (per-turn checkpoints, observable subagents). Gaps:
  - continuation hydrator not registered;
  - HITL interrupts classified in-doubt instead of bound to Human Tasks;
  - OpenAI-only model factory and no default model;
  - no Environment Kits (read-only Docker);
  - input/output tokens 0 and no cost;
  - subagents without MCP;
  - manifests refuse subagents;
  - the v1 describe says `qualified=True` but over-claims.

  Owner hold D7 ("Deep Agents changes await the owner's brief") is lifted by this program if accepted.
- **P2 claude_managed.** The HL-24 end-to-end drill has never run. Gaps:
  - setup is cooperative through `mc_prepare`;
  - no compaction/continuation (the budget cap stops the session);
  - subagents flag-only and refused on code missions (owner TODO wants them);
  - remote MCP only, with OAuth credentials not provisioned;
  - AGENTS.md is a stale snapshot;
  - fork caps at R1 unless the provider adds branching.
- **P3 cursor.** Local:
  - refuses Windows, so it runs on WSL2/Linux. Run 2 measured the SDK bridge at a 199 MB peak on
    WSL; the 3.6 GB figure belongs to the Windows `cursor-agent` CLI;
  - Run 2's MR-03 is blocked: the SDK rejects `observe_run` and the agent runs on unobserved (RF-18);
  - MCP secrets come from the ambient environment, not the Secret Broker;
  - no compaction control.

  Cloud:
  - SCM integration blocks drills (owner prerequisite);
  - inline MCP secret expansion is unverified;
  - no fail-closed hooks.
- **P4 codex_agents.** Gaps:
  - the approval round trip failed live;
  - built-in shell/file are ungated (HITL limited to function tools, per ADR 0053);
  - the instruction override semantics are unverified;
  - no subagents by design;
  - no compaction/continuation;
  - cost unknown.
- **P5 claude.** Local (Run 2 MR-01 local and MR-11 Temporal Cloud passed, both Stage Graph):
  - usage is unknown on every run;
  - the inline subagent path is dead code;
  - the `fork_session` R3 candidate is unused;
  - a possible user-skill isolation leak through `CLAUDE_CONFIG_DIR`.

  Cloud has no adapter and no control API; see D3.
- **P6 codex.** Local passed Run 2's MR-02, and MR-12 passed on Temporal Cloud: a Stage Graph, with
  usage that settles. Native compaction, `thread/fork` (R3 candidate) and `turn/steer` (native
  mid-turn inject) are available but unused. Subagents carry only model and read-only, and their
  threads park units `in_doubt` (RF-14). Allowlist egress is advisory (RF-13). Cloud is as P5.

## 9. Owner decisions needed

| ID | Decision | Recommendation |
| --- | --- | --- |
| D1 | Accept the program, the capability catalog and Sprint 0 before P1 | Accept; start after Run 2 close-out lands on `main` |
| D2 | Accept the design positions §6.1–6.9 (some amend proposed ADRs) | Accept as the Sprint 0 ADR set |
| D3 | What "Claude cloud" and "Codex cloud" mean, given no control API for the subscription cloud products | Treat `claude_managed` and `codex_agents` as the cloud placements with control; keep `claude_cloud`/`codex_cloud` as fire-and-collect lanes with only C01, C04 and C12 required, or drop them |
| D4 | Add an `openai-agents` SDK-run lane? | Not now; revisit after P4 |
| D5 | Deep Agents default model provider (needs an Anthropic factory?) | Add a provider-neutral model factory in P1 |
| D6 | Per-sprint live spend ceilings and which tier T3 uses (Temporal Cloud dev namespace, AWS worker) | Set per sprint in its `DESIGN.md` |
| D7 | Human Gate enrichment (C09) timing | Its own short sprint after P2 |
| D8 | In-run coordinator credential (`mc.coordinate`, §6.8) | Accept the scoped-delegation design |
| D9 | Approval timeout default (§6.4) | `keep_waiting` with a Human Task deadline |

## 10. Working rules

- Branch from `main` (the Run 2 close-out is committed there). Each sprint uses its own branch and
  merges only after the ledger and describe agree.
- In phase A, copy the sprint's rows from [RUN-2-CARRY-FORWARD.md](RUN-2-CARRY-FORWARD.md) into
  `AUDIT.md`. In phase E, record each item's outcome there.
- Postgres plus local Temporal are required for any persistence or runtime claim (Mission Control
  AGENTS.md). Report passed, failed, blocked and unrun separately.
- Host limits: about 15 GB RAM. Run one heavy job at a time behind the memory guard, and run lease-lane
  live tiers on WSL2/Linux.
- Credentials are cited by name only. Private receipts stay out of git, and only digests enter the
  ledger.
- Every sprint starts with phase A against the current code. The baseline ages quickly.
