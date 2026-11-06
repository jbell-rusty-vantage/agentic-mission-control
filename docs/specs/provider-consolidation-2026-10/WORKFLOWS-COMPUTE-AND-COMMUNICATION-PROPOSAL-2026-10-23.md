---
type: Proposal
title: "Workflows, compute and communication beyond the current sprints: the workflow catalog and Map Reduce at the workflow level, literal parallelism and its integration policy, coordinator-requested compute, agent-to-agent conversation per provider, and timely steering of a running mission"
description: "Written 2026-10-23 in answer to four open questions outside the provider-consolidation sprints. What the four workflow systems cover and what a coordinator actually reaches for (named compositions compiled into them, not new families); Map Reduce as a Parallel Swarm of Goal Loops with a reduction policy that respects context windows (reducible output contracts, hierarchical reduce with a computed fan-in width, code integration by branch, provenance on every reduced claim); the three levels of parallelism and what literal parallelism needs on Temporal and on this host; compute as owner-created pools the coordinator consumes through a capacity broker, never raw cloud control; a provider matrix of subagent capability graded one-shot to peer, and one Agent Message contract that unifies parent-child conversation, child reports, coordinator injects and questions, bound per lane; the timeliness budget for steering a running mission and the one change that makes it timely on Deep Agents (cooperative inject at the model-call seam); a local proof plan; decisions WC-D1..D16."
tags: [mission-control, workflows, parallel-swarm, map-reduce, compute, sandboxes, subagents, agent-messages, interventions, proposal]
---

# Workflows, compute and communication beyond the current sprints

**Status: proposal, draft (2026-10-23).** The owner asked four questions outside the
provider-consolidation sprint work and asked for research, exploration and reasoning rather
than a plan: which workflows beyond Stage Graph and Goal Directed, and how a Map Reduce at the
workflow level should behave with literal parallelism and a precise integration policy; whether
the coordinator should be able to spin up cloud compute for parallel sandboxed agents; whether
agents in a mission should have a bidirectional subagent tool, modelled as agent messages, given
what each provider can do; and how a coordinator steers a running mission in time for it to
matter. This document answers in that order. It decides nothing. It is filed in this program
because the owner's design documents accumulate here; it can move to its own program with
`program_ledger.py move` when one exists.

It rests on the normative workflow annexes
(`mission-control-general/workflow-types/00` (deleted 2026-11-01; last at `66185d2e`), `02`, `03`, `04`, `05`), the knowledge pages
[workflow-systems](../../knowledge/workflow-systems.md), [parallel-swarm](../../knowledge/parallel-swarm.md),
[evaluator-optimizer](../../knowledge/evaluator-optimizer.md), [interventions](../../knowledge/interventions.md),
[deep-agents-turn-stops](../../knowledge/deep-agents-lane.md), [environments](../../knowledge/environments.md),
[environment-preparation](../../knowledge/environment-preparation.md) and [mission-chains](../../knowledge/mission-chains.md),
the interview rounds R5 and R6, the archived provider research sheets (Claude Code, Codex,
Cursor, Managed Agents, Agents API, Daytona, harness-in-sandbox) and primary pages read on
2026-10-23 for Codex subagents, Claude Code agent teams and Cursor subagents. The
[coordinator's projection](../coordinator-surface-2026-10/COORDINATOR-PROJECTION-PROPOSAL-2026-10-23.md) (PR-07) is assumed:
cards, wakes, the `mc_coordinator` tool, observer features. Facts are marked *existing*,
*specified* (in the annexes, not in code) or *proposed*. §9 lists what was not verified.

| Section | Answers |
| --- | --- |
| §1 | The frame: three laws the spec already settled, and three levels of parallelism |
| §2 | The workflow catalog: what exists, what a coordinator reaches for, and why the answer is named compositions, not new families |
| §3 | Map Reduce at the workflow level: the member, the reduction policy, the fan-in width, codebases |
| §4 | Literal parallelism: what it needs on Temporal, on the workers and on this host |
| §5 | Compute: pools the owner creates, a capacity broker the coordinator consumes |
| §6 | Agent-to-agent communication: the provider matrix, the Agent Message, the bidirectional subagent tool |
| §7 | Coordinator to mission: the timeliness budget and the one change that makes steering timely |
| §8 | A local proof in three steps |
| §9 | Decisions WC-D1..D16 and the honest list |

---

## 1. The frame

### 1.1 Three laws already settled

The annexes settled three things in 2026-09 that answer half of the owner's questions before
any new design, and every proposal below keeps them.

1. **Members share nothing but immutable inputs** (`03 §3.3`, "the inter-agent law applied
   within one Mission"). Parallel units do not read each other's work while they run. Exchange
   happens in convergence or a following stage.
2. **No child-to-parent token stream; agents communicate through artifacts and the ledger**
   (`03 §2`). Whatever "bidirectional communication" becomes, it is messages that are recorded,
   never a shared context.
3. **Convergence is explicit and has its own completion contract** (`03 §4.2`). Nothing is
   reduced implicitly. The candidate spec's `map_reduce` was already mapped to
   `all` plus a deterministic convergence; this document widens that, it does not replace it.

And one law from the program model: **the primary long-running strategy is compaction, a
validated checkpoint, transfer, a fresh session** (`00 §5.3`). The owner's framing is exact:
a context window fills, the only way to continue is to compact and transfer, so parallelism is
the only way to do *more* in one period. The cost of parallelism is integration, and the
integration step has a context window too. That last sentence is the design constraint for §3.

### 1.2 Three levels of parallelism

The word "parallel" names three different mechanisms in this system. A coordinator must choose
the level deliberately, because they differ in isolation, durability, cost and what can go wrong.

| Level | Mechanism | Shares | Durability | Exists |
| --- | --- | --- | --- | --- |
| **L1, inside one turn** | parallel tool calls and sync `task` subagents in one LangGraph superstep; QuickJS `Promise.all` fan-out | the parent's process, checkpointer, state schema, budget | one superstep: all-or-nothing on exception, checkpointed per task | existing on Deep Agents |
| **L2, beside one unit** | async subagents on the Agent Server; Codex and Agents API subagent threads; Cursor background subagents | the mission unit's budget slice and obligations; separate contexts | each child is its own run or thread; the parent's unit stays open | existing (Deep Agents async, governed) |
| **L3, workflow level** | separate program nodes (stages with no dependency today; swarm members tomorrow) as separate Temporal operations on separate workers | nothing but inputs; own workspace, sandbox, budget, Transcript, obligations | each is a durable unit with its own lifecycle, points and fork | existing for independent stages; swarm members specified only |

Map Reduce "spawn ten Goal Directed workflows and reduce them" is **L3**. L1 is for breadth
inside a thought (ten searches), L2 for delegation the parent supervises, L3 for work that must
survive the parent, be forked on its own, and be billed and reviewed on its own. The provider
matrix in §6 is mostly about L1 and L2; §2 to §5 are about L3.

---

## 2. The workflow catalog

### 2.1 What exists and what Goal Directed is

Two families run: Stage Graph and Goal Directed. Parallel Swarm and Evaluator Optimizer are
specified with accepted semantics (members, variants, completion policies, convergence; rounds,
rubrics, computed acceptance) and have no interpreter, blueprint or schema value.

Goal Directed is special for the reason the owner gives, and the annex says more than the code
does. The Goal Loop (`02`) is observe → propose → authorize → act → evaluate → review → decide,
with a typed **Progress Review** required at every iteration boundary and before major spend
(criteria status, evidence, remaining gaps, progress delta, uncertainty, the justified next
action), a Cycle Decision of `continue | accept | stop | revise | await_input`, a Loop Journal,
and a Continuation Decision that may compact and transfer, move to another model or runtime,
decompose through the action space, invoke a child mission, or stop. The implemented subset is
iterations with an independent verifier, convergence patience and continuation through the
packet; `revise` as re-planning, the Progress Review as a typed record and the decomposition
actions are not built. "Take stock and re-formulate on each iteration" is therefore not a new
workflow; it is the Goal Loop's own §7, §8 and §11, unbuilt. §2.4 names what to build.

### 2.2 The question behind "which other workflows"

When I survey as a coordinator I do not reach for a *family*; I reach for a *shape of work*:
"fan this out over the twelve sources and give me one evidence table", "try three approaches and
keep the one whose tests pass", "draft, critique, redraft until the rubric passes", "keep watching
this feed and process what arrives". Each shape is a composition of the four systems with a few
fixed policies. The spec designed for this: systems nest explicitly (`00 §5.1`), and the
annex already maps `speculative_race`, `map_reduce` and `evaluator_fan_in` to swarm policies
rather than new engines (`03 §4.2`).

So the recommendation is: **four systems, plus a catalog of named compositions** (mission
templates with fixed policies) that compile into them and carry their own card. New families
only where a composition cannot express the control flow. The test below sorts the candidates.

| Shape the coordinator asks for | Composition | New family? |
| --- | --- | --- |
| **Map Reduce** (fan out N workers, synthesize) | Stage(plan) → Swarm(fan-out from plan, members are Goal Loops or stages) → Stage(s)(synthesis); §3 | no; needs Swarm built |
| **Best of N / tournament** (same task, keep the best) | Swarm `all` with Member Variants → Evaluator Optimizer or `direct_model` ranking as convergence | no |
| **Speculative race** (first acceptable wins) | Swarm `first_accepted`, `cancel_remaining` | no |
| **Redundant extraction** (accept when k agree) | Swarm `quorum(k)` → `agreement_check` | no |
| **Draft, critique, revise** | Evaluator Optimizer (producer, evaluator panel, rounds) | no; needs EO built |
| **Debate / adversarial panel** (positions, rebuttals, judge) | Swarm of advocates → Stage(rebuttal round, inputs = all positions) → EO or human `SELECTION` | no; one new reduce kind (`debate`) |
| **Plan, fan out, synthesize, verify** (the research default) | Stage Graph: plan → Swarm → synthesis → EO(verify) | no |
| **Recursive decomposition** (a worker decides to split) | a Swarm member that is itself plan → Swarm → synthesis, under a depth governor; the member list is an artifact the plan stage produced (`FanOutMembers.source_output`) | no, but needs the Goal Loop's decompose action and a depth governor |
| **Campaign** (weeks of work in episodes) | a Mission Chain of Goal Loops with a memory space between them (PR-07 §8) and review gates on the links | no |
| **Pipeline with cycles** | Stage Graph with revisit regions (exists; K05 finishes it) | no |
| **Continuous intake** (watch a source, process each arrival forever) | a Goal Loop with no `until` plus a schedule or signal watcher that enqueues items; or a standing mission that spawns a child per arrival | **candidate**: a "Standing Mission" is the one shape where lifecycle differs (no terminal outcome by design) |
| **Human-paced** (work, review, steer, repeat) | review gates on stages and links (HG supplement) | no |

The honest reading: the four systems are the right primitives, Swarm and Evaluator Optimizer
need to be built, the Goal Loop needs its own §8 and §11, and *one* genuinely new shape (a
standing, non-terminating mission) should wait until the compositions above have run live.
The catalog a coordinator browses is the table above, as cards, each with the manifest template
that compiles it.

### 2.3 Where the "hierarchical blurriness" lives

The owner is right that there is blurriness between "ten subagents", "ten async children" and
"ten Goal Loops". It is not a modelling problem; it is a choice along §1.2's levels, and the
card should make the coordinator choose by three questions:

| Question | If yes | Level |
| --- | --- | --- |
| Must each worker survive the parent, be forked, reviewed and billed alone? | yes | L3 member |
| Must the parent keep supervising and talking to the worker while it runs? | yes | L2 child (§6) |
| Is it breadth inside one thought, cheap to redo, no side effects worth isolating? | yes | L1 |

The same work can be any of the three. Map Reduce at the workflow level is L3 because its whole
point is that the ten workers each run their own compaction and continuation and leave their
own Transcript. A nested Goal Loop inside a swarm member is permitted by the nesting matrix and
keeps its own journal (`02 §14`); recursion is bounded by a declared depth governor and by the
fact that fan-out never mutates the committed program: the plan stage produces the member
list as an artifact, the swarm expands from it with a maximum cardinality (`03 §2`).

### 2.4 What to build in Goal Directed

Three things, all in the annex, in this order: the typed **Progress Review** record at every
iteration boundary (it is also what the coordinator's decision log and the `prompt.obligations`
section read); the Cycle Decision **`revise`** as a re-plan within the action space, including
"decompose into a swarm" and "change approach" as recorded actions, not as a new objective (a
new objective is a successor mission, per the review-gates boundary law); and the **Context
Health Policy** as a pinned catalog record rather than one token percentage. Verifier findings
to the next executor (K04) and authorable thresholds (K02) are prerequisites already listed.

---

## 3. Map Reduce at the workflow level

### 3.1 The shape

```yaml
program:
  kind: stage_graph
  stages:
    plan:
      agent: planner                      # produces plan.items: [{key, brief, inputs}]
      outputs: [{ name: items, kind: structured_record, schema: catalog://schemas/work-items@1 }]
    fan_out:
      kind: parallel_swarm
      members:
        fan_out_from: { stage: plan, output: items, identity: item.key, max_members: 12 }
        template:
          kind: goal_directed             # each member is a Goal Loop
          agent: worker
          outputs: [{ name: finding, kind: structured_record, schema: catalog://schemas/finding@2 },
                    { name: notes, kind: document }]
          budget: { tokens: 400000, wall_clock: 45m }
      completion: { policy: best_effort, min_accepted: 9 }
      on_resolution: cancel_remaining
      governors: { concurrency: 4, swarm_budget_usd: 20, straggler_grace: 10m }
      convergence:
        kind: stage_graph                 # one or more synthesis nodes
        stages:
          reduce:
            reducer: hierarchical         # §3.3
            fan_in: auto                  # §3.4
            agent: synthesizer
            inputs: [{ from: members.*.finding }, { from: members.*.notes, tier: reference }]
            outputs: [{ name: synthesis, kind: document, template: catalog://obligations/synthesis@1 },
                      { name: conflicts, kind: structured_record, schema: catalog://schemas/conflicts@1 }]
          verify:
            depends_on: [reduce]
            kind: evaluator_optimizer
            rubric: catalog://rubrics/synthesis-quality@1
```

Everything in that block except `parallel_swarm`, `fan_out_from`, `reducer`, `fan_in` and the
nested `goal_directed` member exists or is specified. The members are L3 units: each gets its own
workspace or sandbox, budget slice, Transcript, cognition points and obligations; each is forkable
on its own; each compacts and continues on its own. The coordinator sees twelve units under one
swarm node in `run inspect`, with the member key and variant on every output.

### 3.2 The reduction policy: what makes integration precise

Reduction fails in practice for four reasons: the member outputs are not reducible; the reducer's
context cannot hold them; conflicts are averaged away; and the result cannot be traced back. The
policy addresses each.

**Reducible by contract.** A swarm member's obligations are the reduction's input schema, so the
template must declare output kinds a reducer can consume: `structured_record` with a declared
key and a merge rule per field (`union`, `first`, `max`, `concat`, `conflict`), `document` with a
section schema so reducers merge by section, `file_artifact` with a path convention, `code_change`
as a branch (§3.5), `verdict` with a scale. A swarm whose member template declares only prose is
refused at compile with "not reducible" unless its reducer is `model` with an explicit
`accept_prose: true`.

**Reducer kinds** (a closed set, each a card):

| Reducer | What it does | When |
| --- | --- | --- |
| `coalesce` | deterministic merge by key and field rules; conflicts become rows of a `conflicts` record, never silently resolved | records; the default for structured outputs |
| `agreement` | quorum or threshold agreement per key; disagreements to `conflicts` | redundant extraction |
| `rank` | an evaluator or `direct_model` judge orders candidates against a rubric; judge identity recorded | best of N |
| `synthesize` | a model (an agent executor with its own obligations) writes the integrated deliverable from the member deliverables; must emit `conflicts` and `provenance` records as obligations | documents, mixed evidence |
| `debate` | positions → rebuttal round → judge; a two-stage synthesize | adversarial panels |
| `integrate` | code: sequential merge of member branches with tests between merges (§3.5) | codebases |
| `hierarchical` | any of the above applied in a tree whose width is computed (§3.4) | when N outputs exceed one context |

**Conflicts are deliverables.** Every reducer owes a `conflicts` record (possibly empty): key,
the member outputs that disagree, and the disposition (`chosen: member X by rule R`,
`unresolved`, `escalated`). An unresolved conflict above a declared tolerance routes to a repair
cycle (re-run the disagreeing members with the conflict as input) or to a human `SELECTION`
review gate, as authored. Nothing is averaged.

**Provenance is mandatory.** Every claim, row or section in a reduced deliverable
`derives_from` member outputs by key, through the obligation lineage of OC-1. The synthesis
agent is given the member deliverables as inputs with handles (the three depth layers), and its
obligation template requires citations to member keys. `missionctl` can then answer "which member
said this".

**Partial reduction is a typed outcome.** `best_effort` and `quorum` make it normal that
convergence runs over fewer members than planned; the synthesis records which member keys were
absent and why (`not_accepted`, `cancelled`, `quorum reached`), and the swarm's output carries
`coverage: 9 of 12`. A downstream consumer can require full coverage.

### 3.3 Hierarchical reduce

Ten Goal Loops each produce a 6,000-token finding and a 30,000-token notes document. No single
synthesizer should read 360,000 tokens of notes, and it does not need to. The reduce is a tree:

1. **Leaf reduce** over groups of `k` members: each leaf synthesizer receives `k` findings inline
   (state layer) and `k` notes as references with fetch handles, and produces one intermediate
   synthesis with its own `conflicts` and provenance.
2. **Inner reduce** over the intermediates until one remains.
3. **Final verify** (Evaluator Optimizer) over the root synthesis against the member findings
   sampled by the evaluator, which may fetch any member deliverable by handle.

The tree is computed by Mission Control from `fan_in` (§3.4), compiled as nodes (so every
intermediate is a unit with a Transcript and a fork point), and shown as such. Intermediates are
artifacts with lineage; only the root is the swarm's projected output. The same tree reduces a
swarm of swarms (recursive decomposition) because an inner node's input is just more deliverables.

### 3.4 The fan-in width

`fan_in: auto` is a number computed, not guessed:

```text
k = floor( (context_target − prompt_tokens − reserved_output − tool_allowance) / expected_member_inline_tokens )
```

where `context_target` comes from the reducer agent's Context Health Policy (the
quality-preserving target, not the provider limit), `expected_member_inline_tokens` is the
measured size of the inline tier of a member's deliverables (known once members settle, estimated
from the template's schemas before), and the result is clamped to `[2, fan_in_max]`. The
coordinator may pin `fan_in: 4`. The computation and its inputs are recorded on the swarm's
receipt, so "why did this become a three-level tree" is answerable.

### 3.5 Codebases

For code the member outputs are branches, and the law that members share nothing means every
member works on its own worktree or sandbox clone from the same base commit. `integrate` then:

1. orders member branches (by declared priority, then by smallest diff);
2. merges one at a time into an integration branch, running the declared test command after
   each merge (the `test_run` deterministic executor);
3. on a textual or test conflict, opens a **repair cycle** for the conflicting member with the
   conflict as input (a Stage Graph revisit with `prior_result_refs`, K05), bounded by
   `max_repairs`; or, if authored, routes to a human `SELECTION` with both branches;
4. produces the integration branch, the `conflicts` record, and a `git_snapshot` as deliverables;
5. never force-pushes and never rewrites a member's branch; the member's branch stays as lineage.

Members that touch disjoint paths integrate trivially; the plan stage's brief should partition
by path when it can, and the card says so. Parallel *write-heavy* fan-out is where every
provider's own documentation warns of conflicts; the policy above is why Mission Control can
offer it anyway: the integration is a unit with obligations, not a hope.

---

## 4. Literal parallelism

### 4.1 What it needs

Temporal already runs independent Stage Graph stages concurrently; what is missing is capacity,
defaults and proof (interview R6). For swarms the list is:

| Need | What it is | Status |
| --- | --- | --- |
| One operation per member | each member's turn is its own `operation.execute` Activity on its own operation workflow; a swarm of 12 is 12 concurrent Activities | existing mechanism; the swarm interpreter is new |
| Worker capacity | `max_concurrent_activities` per worker; a `cognitive` worker role that serves only Deep Agents turns, so capacity scales by starting processes on this host, WSL2 or another machine | R6.2, sprint H |
| Concurrency governor | the swarm's `concurrency` (and the installation default for Stage Graphs, R6.1), enforced by the interpreter releasing at most `c` members at once; capacity shortfall queues members, it never fails them | proposed |
| Isolation | a workspace or sandbox per member: lease worktrees on the code lanes; on Deep Agents `StateBackend` is per thread already, Docker sandboxes need one container per member | R6 isolation row |
| Budget | `member_budget` and `swarm_budget` as reservations before release; a member's turn stop at its own cap (existing on Deep Agents) | existing per unit; swarm scope new |
| Rate limits | provider rate limits are the first wall when many members call the same model; a per-model-provider concurrency ceiling at the installation, shared across runs | proposed |
| Observation | the lineage graph and the unified peek already group children; a swarm node needs `members: running 4, accepted 7, not_accepted 1` in `run inspect` and a `swarm.resolved` event | proposed |

Temporal's own limits are far away at this scale (thousands of pending child workflows and
Activities per workflow); the real limits are host memory, worker slots and model rate limits.
LangGraph's in-graph `Send` fan-out is not this: it parallelizes inside one agent's turn (L1) and
shares one process; it is the wrong tool for ten Goal Loops and the right tool for ten searches.

### 4.2 On this host

The owner's machine has about 15 GB of RAM with a 6 GB WSL2 cap and a standing rule of one heavy
job at a time behind a memory guard. A Deep Agents turn holds a model client, a checkpointer pool
and, with Docker, a container. Realistic local parallelism is two to three concurrent members on
Deep Agents with the state backend, fewer with Docker sandboxes, and the code lanes' SDK bridges
on WSL2 (the Cursor bridge measured 199 MB; the Windows CLI 3.6 GB). That is enough to prove the
orchestration (§8) and not enough to run the owner's "ten" for real, which is what §5 is for.

---

## 5. Compute

### 5.1 The question, reframed

"Should the coordinator spin up infrastructure in the cloud?" splits into two: *who creates
compute*, and *who consumes it*. The answer I recommend: the owner creates **compute pools**
with ceilings; the coordinator **consumes** them by declaring a pool and a concurrency on a
swarm or a mission, and a **capacity broker** reserves, provisions, attaches and reclaims. The
coordinator never holds a cloud credential and never calls a cloud API; that keeps ADR 0043
(secrets never enter an environment) and ADR 0047 (owner prerequisites and preflight) intact and
makes the spend governable the same way token budgets are.

### 5.2 What exists to build on

- Environment Kits and the mission layer prepare an environment to a readiness level before
  agent work; sandbox profiles and `execution_environment` are declared per node; network policy
  resolves to exact hosts per lane with an enforcement record.
- Lanes already carry compute of three kinds: worker-hosted leases (WSL2 worktrees for the code
  lanes), Docker for Deep Agents (read-only today), and provider-owned compute (Cursor cloud
  VMs, Managed Agents cloud or self-hosted sandboxes, the Agents API environment).
- Deep Agents' backend list includes a long row of sandbox providers (Daytona, Modal, E2B,
  Runloop, Vercel Sandbox, AgentCore, LangSmith and others) through `BaseSandbox`, and Mission
  Control already has a `BaseSandbox` subclass for Docker. Daytona was researched to adapter
  depth (SandboxHost design; about 0.17 USD per hour for a 2 vCPU, 4 GiB sandbox; egress
  allowlists only from tier 3).
- The deployment options report sketches remote workers and the Agent Server's hosting.

### 5.3 The compute pool (proposed catalog kind `compute_pool`)

| Field | Content |
| --- | --- |
| `provider` | `local_docker`, `wsl2_worker`, `daytona`, `e2b`, `modal`, `vercel_sandbox`, `cursor_cloud`, `managed_agents_cloud`, `agents_api_environment`, `remote_worker` |
| `shape` | vCPU, RAM, disk, image or kit pin, region |
| `serves` | which lanes and which roles may use it (`deep_agents.sandbox`, `claude_agent_sdk.lease`, `cognitive_worker`) |
| `ceilings` | max concurrent slots, max slot hours per run and per day, USD ceiling per run and per day, idle reclaim after |
| `network` | the pool's egress policy; a mission's allowlist may only narrow it |
| `credential` | by name, held by the Secret Broker, delivered to the adapter only |
| `readiness` | the owner prerequisite and preflight that proved the pool works (ADR 0047) |

Pools are owner-created and preflighted like any prerequisite. They appear as cards. A mission or
a swarm declares `compute: { pool: daytona-small, concurrency: 8 }`; compile checks the pool
serves the lane, preflight checks the ceilings against the declared governors, and the receipt
records the pool and the slot ids.

### 5.4 The capacity broker (proposed)

Modelled on budget reservations: before a member is released, the broker **reserves** a slot
(and a cognitive worker slot where cognition runs on a Mission Control worker), **provisions**
through the provider's SandboxHost adapter with the kit, **attaches** the sandbox to the unit's
binding (digest recorded), and on settlement, cancel or incident **reclaims** it, with a reaper
for orphans (the recovery hygiene K20 already asked for, generalized). A shortfall queues the
member; a ceiling breach is a governed outcome, never an exception. Escalation is a Human Task:
"swarm X wants 8 slots, pool allows 4, approve a temporary raise?", answerable by the owner or by
a standing answer.

Two placements follow from where cognition runs:

| Placement | Cognition | Tools | Scales by |
| --- | --- | --- | --- |
| Worker-hosted lanes (Deep Agents, Claude Agent SDK, Codex, Cursor local) | a Mission Control worker | a sandbox from a pool | worker processes (`cognitive` role, local, WSL2 or a remote worker pool) **and** sandbox slots |
| Provider-hosted lanes (Cursor cloud, Managed Agents cloud, Agents API) | the provider | the provider's environment | the provider's own concurrency limits (Agents API: six concurrent subagents by default; Managed Agents: shared sandbox, at most 25 child threads) and our USD ceiling |

The first placement is where a `remote_worker` pool matters: a machine (or a sandbox that runs a
Mission Control worker) joins the `cognitive` task queue on demand. That is the furthest item in
this section and the only one that is truly "spinning up infrastructure"; everything before it is
slots in pools the owner already paid for.

### 5.5 Safety rules that do not bend

Sandboxes are credential-free (secrets reach them only through the broker's delivery for the
declared phases); network egress is the pool's policy narrowed by the mission; a sandbox does not
protect against prompt injection or exfiltration unless the network is closed, and the card says
so; the Stop Fence must reach a sandboxed turn the same way it reaches a local one (through the
kernel hook, not through the sandbox); and every slot has an owner-set idle reclaim so a parked
`in_doubt` unit cannot hold compute forever.

---

## 6. Agent-to-agent communication

### 6.1 What each provider can do (read 2026-10-23)

"How good is each provider's subagent capability" has a precise answer along six abilities. The
grade is the highest ability the provider documents.

| Provider surface | Spawn, parallel | Steer a running child | Child messages parent while running | Peer to peer | Nesting | Isolation | Grade |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Deep Agents sync `task` | yes, in one superstep | no (one shot) | no; result at return | no | children cannot `task` in fork mode; general child can | shared state, own context | one-shot |
| Deep Agents async (Agent Server) | yes | **yes**: `update_async_task` (new run on the child thread, interrupt or enqueue on 0.7.30) | pull by parent (`check`); push notifications 0.7.27+ beta; `waiting` status for a child on `interrupt()` | no | a child is a full deep agent; depth by policy | own thread, own server run | steerable |
| Deep Agents dynamic (QuickJS `task()`) | yes, scripted fan-out | no | no | no | no `task` inside the child | own context | one-shot |
| Claude Agent SDK subagents | yes; `background: true` | no mid-turn; **resume** a finished or idle subagent by name (SendMessage address) with a new message | no; result at return (`forward_subagent_text` streams its text to the harness) | no | one level | `isolation: worktree` (file agents only) | resumable |
| Claude Code agent teams (experimental, local) | lead spawns teammates | **yes**: mailbox messages delivered automatically; Escape interrupts a teammate's turn | **yes**: teammates message the lead and each other; protocol messages (plan approval, shutdown) | **yes** | no nested teams | separate sessions, shared repo; shared task list with file locking | peer |
| Codex multi-agent (`collaboration` tools, v2) | `spawn_agent`, built-in `default`, `worker`, `explorer`, custom TOML agents | **yes**: `send_input` to a running thread; "steer a running subagent, stop it, close it" | approval requests surface from child threads to the parent; results on `wait_agent`; `interrupt_message` recorded | no documented | `max_depth` default 1 | inherits the parent's sandbox and permissions; cannot override sandbox, MCP, provider | steerable |
| Cursor subagents | foreground and background; parallel Task calls; cloud subagents on own VM | not documented mid-run; **resume** by agent id after it finishes; background state readable from `~/.cursor/subagents/` | no; parent reads progress files | no | depth 2 since 2.5 | own worktree and branch, or own cloud VM, on request | resumable |
| Anthropic Managed Agents `multiagent_20261001` | predefined (≤20) and inline agents; dynamic workflows | **yes**: persistent session threads (≤25) you send to | thread results and events | within a workflow run | server-run workflows | shared sandbox and filesystem | steerable |
| OpenAI Agents API `multi_agent` | `create_subagent`, six concurrent by default | **yes**: `send_subagent_input`, `interrupt`, `resume`, `wait_for_subagents`, `close` | items and `subagent.*` events; per-subagent usage | no | one level | shared environment; subagents cannot call function tools | steerable |

Three observations drive the design. First, **steerable is now the norm** (Deep Agents async,
Codex, Managed Agents, Agents API) and the verbs are the same five everywhere: spawn, send, wait,
read, close, with interrupt as a sixth. Second, **peer messaging exists in exactly one place**
(Claude Code teams, experimental, file mailboxes, no SDK form yet). Third, **Mission Control can
observe most of it**: Codex app-server exposes `subAgentActivity` and `parentThreadId`, hooks
have `SubagentStart` and `SubagentStop` on Claude, Codex and Cursor, the Agents API has subagent
endpoints and events, Deep Agents async children are our own governed runs.

### 6.2 Should we build a bidirectional subagent tool? Yes, as one message contract

The owner's instinct is right and the spec's law tells us the shape: not a shared context, but
**messages that are recorded**. I propose one contract and one tool concept, bound per lane.

**`mc.agent_message.v1`** (proposed):

| Field | Content |
| --- | --- |
| `message_id`, `thread` | the thread is a parent-child conversation, a coordinator-unit channel, or a peer channel |
| `from`, `to` | agent identities: `unit:<key>`, `child:<unit>/<name>`, `coordinator:<id>`, `human:<task>` |
| `kind` | `instruction`, `context`, `question`, `answer`, `report`, `result`, `status`, `handoff`, `interrupt`, `close` |
| `body` | text plus artifact refs; never inline bodies above a cap |
| `in_reply_to` | for answers and results |
| `obligations` | obligation names this message touches (a `report` fulfils a communication obligation) |
| `delivery` | requested: `next_model_call`, `next_turn`, `next_iteration`, `interrupt`; achieved: the same vocabulary plus the point it entered at |
| `point_ref` | the cognition point at which the recipient saw it |

Every message is a frame first (`agent_message` frame kind, proposed), so the Transcript is
complete without the mailbox, the coordinator's decision log can show the conversation, and a fork
from a point sees what the agent had been told. Routing is a per-thread mailbox, the same durable
mailbox the command path already uses, generalized from "coordinator to run" to "any admitted
sender to any admitted recipient".

This unifies four things the owner listed separately. A coordinator **inject** is an
`agent_message{from: coordinator, kind: instruction}`. A parent **steering a child** is
`{from: unit, to: child, kind: instruction}`. A child **reporting** is `{from: child, to: unit,
kind: report}` and fulfils a communication obligation. An agent **asking the coordinator** (PR-07
§7) is `{to: coordinator, kind: question}`. One contract, four delivery bindings, one Transcript.

**The tool.** `concept.subagent_conversation` with verbs `spawn`, `send`, `wait`, `read`,
`interrupt`, `close`, exposed to the agent as the lane's native tools where they exist and as
Mission Control tools where they do not:

| Lane binding | spawn | send | wait / read | interrupt / close | Observed as |
| --- | --- | --- | --- | --- | --- |
| Deep Agents async | `start_async_task` | `update_async_task` (enqueue by default once on 0.7.30) | `check_async_task`, `list_async_tasks`; push notifications only through our governed wrapper after admission | `cancel_async_task` | our frames (child is our run) |
| Deep Agents sync | `task` | **not steerable**; `send` after return = a new `task` resumed on the child's thread (proposed: thread reuse per child name) | return value | n/a | nested points |
| Codex | `spawn_agent` | `send_input` | `wait_agent` | `close_agent` | `SubagentStart/Stop` hooks, app-server `subAgentActivity` |
| Claude Agent SDK | Task with `background` | resume by name (after idle) | result | n/a | `SubagentStart/Stop`, `forward_subagent_text` |
| Cursor | Task, `is_background` | resume by id (after finish) | background state files | n/a | `subagentStart/Stop` hooks |
| Agents API | `create_subagent` | `send_subagent_input` | `wait_for_subagents`, items | `interrupt`, `close` | `subagent.*` events |
| Managed Agents | thread create | thread send | thread events | thread close | events |

A lane that cannot `send` mid-run receipts the capability as `degraded: resume_only`; the card
says so, and a mission that `requires` steerable children refuses those lanes.

### 6.3 Rules

- **No token streams between agents** (the law). Messages carry text and refs; a child's
  working context is never mounted into a parent.
- **Messages are budgeted**: `max_messages` per thread and per unit, `max_questions` per child;
  a thread that exceeds its budget closes with a typed outcome.
- **A child's question routes to its parent first**; the parent is the child's coordinator. The
  parent may answer, forward to the mission coordinator (`escalate`), or let a standing answer
  apply. Unanswered past the deadline follows the mission's timeout policy (K12).
- **Peer messaging is a selectable capability, default off**, and off by law inside a swarm
  (members share nothing). Where it is on (a team of L2 children under one unit), it runs through
  the same mailbox with the same budgets and the Claude Code team semantics are the reference:
  a shared task list with claim locking, direct messages, protocol messages for plan approval and
  shutdown.
- **Communication obligations** (OC §3.7: `report: progress(every N)`, `join`) are what makes the
  conversation checkable: a curated feature counts model calls and marks the obligation unmet if
  no `report` arrived; the parent's unit cannot settle with an open required `join`.
- **Approvals from a child surface to the parent's gate**, as Codex and the Agents API already
  do, and from the parent to the Human Task Service as every approval does; a child never gets a
  wider permission than its parent (every provider agrees on this one).

---

## 7. Coordinator to mission: timeliness

### 7.1 What exists

Spawning a mission is a chain link or a launch; the coordinator is outside the run. The three
things the owner lists exist in these forms: a tool back to the coordinator is the one-way
`mc-signals` on the code lanes and nothing in-process on Deep Agents (PR-07 §7 proposes
`mc_coordinator`); hooks and callbacks are frames, Watchers and the inbox (PR-07 §6); injection
is the mailbox (`queue_instruction`, `add_context`, delivered at `next_turn` or `next_iteration`)
plus `interrupt_and_inject`, which on Deep Agents and Cursor means `cancel_and_replace` (cancel
the running turn, settle, run a replacement turn), with `cooperative_inject` declared by no lane
and `turn/steer` on Codex native but unused.

### 7.2 The timeliness budget

Steering is useful only if the sum of five latencies is shorter than the time the mission needs
to go wrong. Name them and set targets; today's values are the problem.

| Latency | From, to | Today (Deep Agents) | Target | What closes it |
| --- | --- | --- | --- | --- |
| **Detection** | the agent does the wrong thing → a frame exists | one frame per tool call and model request; settlement-time projection for some facts | per model call | decision-point and obligation events (PR-07 §6.2), the Progress Review record per iteration |
| **Classification** | frame → a notification I can act on | significance kinds at the reducer; manifest Watchers | per frame | watch conditions over the new fact roots; drift watchers (§7.3) |
| **Wake** | notification → I am running | the inbox long-poll returns at once if I am waiting; up to the wait window otherwise | at once while waiting | nothing new; do not poll |
| **Decision** | I read, I decide | my own reading; unbounded if the read is not scoped | one scoped read | the unit-scoped peek with position, the decision log; standing answers and watcher actions make it zero for known patterns |
| **Delivery** | my command → the agent's next model call sees it | `next_turn`: the rest of the current turn (minutes to an hour on a long unit); `next_iteration`: the rest of the iteration; `interrupt_and_inject`: cancel, settle, replace (seconds to a grace period, and it destroys the turn) | **one model call** | cooperative inject on Deep Agents (§7.4) |

Delivery is the one that is structurally wrong today: the only fast path destroys the turn, and
the safe path waits for a boundary that on a Goal Loop iteration can be far away. The point of
§7.4 is that Deep Agents, uniquely among the lanes, can make the safe path fast.

### 7.3 Detecting "the wrong direction"

The coordinator needs facts, not transcripts, to notice drift. The useful ones are cheap to
derive and most are already planned: no obligation progress for N minutes; the same tool failing
k times; budget burn rate above the plan's slope; a Progress Review whose delta is zero twice; a
child `waiting` on a question nobody answered; files written outside the declared output paths;
a model fallback; repeated compaction. Each is a watch condition over frames, points, obligations
and budgets, authored once as a catalog watcher template (`drift.no_progress@1`,
`drift.tool_loop@1`, `drift.burn_rate@1`) and selected per mission. They fire wakes, or act
directly through admitted commands (pause, instruct) when the coordinator pre-authorized that.

### 7.4 The one change: cooperative inject at the model-call seam

On Deep Agents every model call passes through `wrap_model_call`; the budget and fence stops
already answer there instead of the model, without adding a graph node. A **steering
middleware** at the same seam reads the unit's mailbox before each model call and, if an
admitted `instruction` or `context` message is waiting, appends it to the request as a message
(marked `mc_steer`, like the stops are marked), records the `agent_message` frame with the point
it entered at, and lets the call proceed. No cancel, no replacement, no lost work; the delivery
latency becomes one model call, which on a working agent is seconds to a minute. This is exactly
the `cooperative_inject` mode the harness protocol already defines and no lane declares; Deep
Agents would be the first, and the describe cell flips from `cancel_and_replace` to
`cooperative_inject` with `cancel_and_replace` kept for `interrupt` messages. The mailbox read
costs one indexed query per model call; the Stop Fence read already costs the same.

Two consequences. A **steering cadence** knob (`steer.check_every: 1 model call`, default 1,
raisable for cheap tight loops) bounds the overhead and is receipted. And the other lanes get an
honest binding: Codex's native `turn/steer` can carry the same message (unused today, worth
proving), the Claude Agent SDK and Cursor degrade to `next_turn` with `cancel_and_replace` for
interrupts, the hosted lanes degrade to the next turn they accept input on. The card for
`concept.steering` shows that table, and a mission that requires sub-turn steering refuses lanes
that cannot do it.

With §7.3 and §7.4 together the budget closes: detection per model call, classification per
frame, wake immediate, decision one scoped read or zero, delivery one model call. That is
"timely" in the only sense that matters: before the agent's next action, not after its turn.

---

## 8. A local proof in three steps

The owner hopes to try literal parallelism locally. Three steps, each honest about the host.

| Step | What runs | Proves | Cost |
| --- | --- | --- | --- |
| **P-1 orchestration** | the swarm interpreter over the offline fake lane with Postgres and local Temporal: plan → swarm of 6 fake members with staggered durations and one `not_accepted` → `coalesce` → verify; `best_effort(min 5)`, `concurrency 3`, one straggler cancelled | expansion from a plan artifact, the completion policy, feasibility, resolution, the conflicts record, coverage, the swarm node in `run inspect` | none |
| **P-2 two workers** | two `cognitive` worker processes (one Windows, one WSL2), 3 Deep Agents members on the state backend with GPT-6 Luna, `concurrency 2`, a `synthesize` reducer with `fan_in 2` so the tree has two levels | two turns running at once on two processes, member isolation, the hierarchical reduce, provenance in the synthesis, the swarm receipt's fan-in computation | under 3 USD, under the memory guard |
| **P-3 steering** | the same run with the steering middleware: a coordinator-authored watch condition fires on a planted drift, a standing `instruct` lands at the next model call, the Transcript shows the message and the point | §7.4 end to end, the timeliness budget measured | under 1 USD |

Compute pools and remote workers are not in the local proof; P-2 is the ceiling of this laptop.

---

## 9. Decisions and the honest list

### 9.1 Decisions for the owner (recommendation marked)

| ID | Decision | Recommendation |
| --- | --- | --- |
| WC-D1 | The catalog shape: four systems plus named compositions as templates with cards (§2.2), no new families until compositions have run live | Adopt |
| WC-D2 | Build order: Parallel Swarm (with fan-out from an artifact and nested Goal Loop members) before Evaluator Optimizer; the Goal Loop's Progress Review and `revise` beside it (§2.4) | Adopt; Swarm is what Map Reduce, best-of-N and decomposition all need |
| WC-D3 | The reducer kinds (§3.2) as a closed set of cards, `coalesce` the default for records, `synthesize` requiring `conflicts` and provenance obligations | Adopt |
| WC-D4 | Conflicts are deliverables; unresolved conflicts route to a repair cycle or a `SELECTION` gate, never averaged | Adopt |
| WC-D5 | Hierarchical reduce with a computed `fan_in` from the Context Health Policy, compiled as nodes (§3.3, §3.4) | Adopt |
| WC-D6 | Code integration by sequential branch merge with tests between merges and bounded repair cycles (§3.5) | Adopt |
| WC-D7 | Per-model-provider concurrency ceilings at the installation, shared across runs (§4.1) | Adopt |
| WC-D8 | Compute pools as an owner-created catalog kind with ceilings; the coordinator consumes, never creates (§5.3) | Adopt |
| WC-D9 | A capacity broker modelled on budget reservations, with reclaim and a Human Task for ceiling raises (§5.4) | Adopt |
| WC-D10 | `remote_worker` pools (machines joining the `cognitive` queue on demand) as the last compute increment, after sandbox pools | Adopt the order |
| WC-D11 | `mc.agent_message.v1` as the one contract for injects, steering, reports and questions, every message a frame (§6.2) | Adopt |
| WC-D12 | `concept.subagent_conversation` with spawn, send, wait, read, interrupt, close; first bindings Deep Agents async and Codex; `resume_only` as a degraded receipt elsewhere | Adopt |
| WC-D13 | Peer messaging default off, forbidden inside swarms, Claude Code team semantics as the reference where on | Adopt |
| WC-D14 | Cooperative inject on Deep Agents at the `wrap_model_call` seam, with a steering cadence knob; describe flips to `cooperative_inject` (§7.4) | Adopt; it is the single highest-value change in this document |
| WC-D15 | Drift watcher templates in the catalog (§7.3) | Adopt |
| WC-D16 | The local proof P-1..P-3 (§8) as the first live work of this line, after sprint H's worker role exists | Adopt |

### 9.2 Where this would land

Nothing here is in the sprint sequence. The natural homes, if the owner wants them placed: WC-D14
and WC-D15 fit sprint F (lifecycle and observability) because they are small and change the
coordinator's experience most; WC-D11 and WC-D12 fit after OC-2 (subagent transfer) as a sprint
"C2" (conversation); WC-D1..D7 are a new program ("workflow catalog") whose first sprint is the
swarm interpreter; WC-D8..D10 are a new program ("compute") that starts with the Daytona or Docker
SandboxHost and the broker. §8's proof depends on sprint H.

### 9.3 Honest list

- I did not run anything. The provider matrix (§6.1) rests on the archived research sheets
  (2026-10-12/13) and three pages read on 2026-10-23; the Codex `collaboration` tool names come
  from a GitHub issue and a community post about the v2 configuration, and the official page
  describes the behaviour (spawn, follow-up instructions, wait, close) without naming the tools.
- Whether Claude Code agent teams are reachable from the Agent SDK (as opposed to the interactive
  CLI) is not verified; the page calls them experimental and local.
- The steering middleware (§7.4) assumes a mailbox read from inside the Activity-wrapped turn is
  cheap and that appending a message in `wrap_model_call` does not disturb the summarizer or the
  structured-output read; both are plausible given the stops do the same, neither is tested.
- The fan-in formula (§3.4) needs measured inline sizes; the first runs will pin `fan_in`.
- Memory per concurrent Deep Agents turn on this host is not measured; P-2's "3 members" is an
  estimate under the memory guard.
- The `remote_worker` pool and running a Mission Control worker inside a provider sandbox are
  directions, not designs; nothing about worker registration or task-queue security was worked
  out here.
