---
type: Specification
title: "P1 deep_agents design: shared agent configuration, provider-specific discrimination, the cognition coordinate data model, and the steps to prove C01–C16 (draft 2026-10-20)"
description: "Phase B draft for the deep_agents sprint. It answers the owner's three questions: which agent configuration is shared across providers and compiled once; how provider-specific configuration is discriminated and contracted; and how a Temporal workflow, its activity, the Deep Agents checkpoint and the exact input state at that point are stored and related so a run can be read as of a point and forked from it. It then lists the ordered work packages, their fixtures and tiers, and the owner decisions they need."
tags: [mission-control, providers, consolidation, deep-agents, design, time-travel, P1]
---

# P1 deep_agents design (draft for owner review, 2026-10-20)

Companion to [AUDIT.md](../../../archive/provider-consolidation-2026-10/docs/AUDIT.md). Positions here amend the program's §6 for the
`deep_agents` lane and propose the lane-neutral contracts that later lanes reuse. Nothing in
this page is built yet unless the audit says so.

## 1. Shared agent configuration: what every provider must receive

The mission compiler already treats the catalog kinds as lane-neutral and projects them per
host for the file-based lanes (`render_host_files`). The Deep Agents lane bypasses that
pipeline with its exact binding, which is why hooks, plugins and subagents are refused there.
The list below is the complete set of **shared** items the compile step must check and that
each lane materializes natively. It is longer than "skills, MCP, plugins, subagents".

| # | Shared item | Lane-neutral declaration today | Native carrier per lane (deep_agents / claude_agent_sdk / codex / hosted) |
| --- | --- | --- | --- |
| 1 | Instructions, additive over repo `AGENTS.md`, plus the operating contract | node `instruction`, `operating_contract`, ADR 0044 layering | `system_prompt` (+ `MemoryMiddleware` for AGENTS.md-like files) / `system_prompt.append` / `developer_instructions` / session instructions |
| 2 | Model (and per-role model) with settings | `model.profile`, `settings` | model component by digest / `ModelPin` / profile / pack pin |
| 3 | Tools (pinned, with schema digests) | `capabilities[kind=tool]` | in-process `BaseTool` / SDK tools / app-server tools / hosted toolsets |
| 4 | MCP servers (stdio, remote) with tool subsets and credentials | `capabilities[kind=mcp_server].tools` | `MultiServerMCPClient` / `.mcp.json` / `config.toml` / remote only |
| 5 | Skills | `workspace.skills` | backend `/skills` mount / `.claude/skills` / `.agents/skills` / Skills API |
| 6 | Plugins (bundles of 1–9) | `plugins[]` | expanded into members per lane |
| 7 | Hooks (one event vocabulary, projected per lane; the four Kernel Hooks always first) | `hooks[]` (ADR 0026) | `HookScriptMiddleware` / `settings.json` + SDK callbacks / `hooks.json` / provider hooks |
| 8 | Subagents (see §2.2) | `agents[]` + `mc.subagent_profile.v1` | `SubAgent` dicts, async graphs / `.claude/agents/*.md` / `.codex/agents/*.toml` / flag |
| 9 | Memory (persistent agent notes) | `memory_refs` (catalog) | `MemoryMiddleware` / CLAUDE.md memory / none |
| 10 | Sandbox and environment: image, runtimes, packages, Environment Kit | `sandbox.profile`, `execution_environment`, `kit` | state, Docker, LangSmith / worktree + kit / worktree + kit / provider image API |
| 11 | Workspace: repo, policy (`reuse`), inputs, outputs, declared transfer | `workspace` | `StateBackend` files or sandbox upload / lease worktree / same / upload or refs |
| 12 | Secrets and `config:` values delivered to the runtime | `secrets`, `variables` (ADR 0043) | resolved secrets map / `ProcessSecretDelivery` / same / vaults |
| 13 | Network policy and egress allowlist | `network` | Docker `none` / sandbox policy / `network: none` enforced / provider |
| 14 | Context packet and seeded inputs | Context Packet (ADR 0027) | backend seed files / `inputs/` on lease / same / uploads |
| 15 | Output contract (structured response, declared `outputs/`) | output schema binding | `response_format` + writable slot capture / `outputs/` collection / same / same |
| 16 | Budgets and governors (tokens, cost, iterations, wall clock, patience) | `budget`, `governors` | usage from `usage_metadata` / usage frames / `turn/completed` / provider cost API |
| 17 | Compaction and continuation policy (soft/hard thresholds, session mode, rollover) | `continuation` (v2), `GoalSessionRolloverPolicy` | `SummarizationMiddleware` trigger + hydrator / fresh session from packet / native `thread/compact` / budget cap |
| 18 | Human control policy (gate classes, reviewers, timeout) | mission HITL policy (ADR 0038) | `interrupt_on` → Human Task / `can_use_tool` / approval RPCs / `always_ask`, `required_actions` |
| 19 | Observation and tracing (frames, LangSmith project, redaction) | `observation`, tracing policy ref | frame recorder + tracing policy / hooks + transcript / events / provider events |
| 20 | Placement and lane requirements (`requires`, admitted against the describe) | `placement`, `requires`, `lanes` | describe matrix per lane |

**Position P1-S1.** Keep the catalog kinds and the manifest as the single declaration. Add a
lane-neutral `mc.agent_configuration.v1` contract that the compiler emits per node (the 20
items above, each with its resolved refs and digests) and a per-lane **materialization
receipt** (`mc.materialization_receipt.v1`: item → `native | emulated | degraded | unsupported`,
native locator, digest). The receipt is what the ledger and the describe matrix read; "observed
in use" (C01) is a frame-derived fact on top of it. For `deep_agents` the consumer is a new
`DeepAgentsProjection` that replaces the unused `InProcessProjection` and feeds
`compile_deep_agent_execution_binding` with hooks, subagents, memory and the continuation policy.

## 2. Provider-specific configuration: discrimination and contracts

> **Built 2026-10-20 (turn 2).** §2.1 and §2.2 are implemented: see
> [CHANGES.md](CHANGES.md) for the modules, the tests and the API sequence. The finished part
> to read is `application/authoring/lanes/deep_agents.py`, with
> `domain/capabilities/subagents.py` and `domain/authoring/provider_options.py` as its inputs
> and `domain/execution/materialization_receipt.py` as its output.

### 2.1 Discriminated options

The discriminator already exists for the session lanes: `ProviderOptions` is a union keyed by
`provider` (`domain/execution/bindings.py:294-302`), and `lane_environments` repeats the
neutral environment per candidate lane. Deep Agents has no entry.

**Position P1-S2.** Add `provider_options.deep_agents` (`DeepAgentsOptions`, schema
`mc.provider_options.deep_agents.v1`) carrying only what has no neutral meaning:
`sandbox_backend` (`state | docker | langsmith`), `filesystem_permissions`,
`summarization` (trigger clause, keep window), `state_packs` and `context_packs`,
`interrupt_on` extras (`args_schema`, `when` predicates by name), `async_subagents`
(graph id, server profile, policy refs) and `agent_server_profile`. The manifest gets one
optional `provider_options:` map keyed by lane profile; validation refuses keys for lanes the
node does not list. Admission records which options were honoured in the materialization
receipt.

### 2.2 One subagent contract, three kinds

The neutral `mc.subagent_profile.v1` (name, description, prompt, model, tools, skills,
mcp_servers, readonly, background, context_mode, interrupt_on, max_turns) is the right general
object. What is missing is a `kind` and a bridge to each lane's native form.

**Position P1-S3.** Extend the profile with `kind: sync | async | linked_run`, `placement`
(`in_process | agent_server | lane`), `sandbox: shared | own | none`, `budget` and
`provider_overrides: {lane_profile: {...}}`. Admission evaluates each field against the lane's
`LaneSubagents` capability and writes a per-field verdict into the receipt; `unsupported`
fields are refused when `requires.subagents` names them, otherwise reported `degraded`. Per
lane:

| Kind | deep_agents | claude_agent_sdk | codex | hosted |
| --- | --- | --- | --- | --- |
| `sync` | `SubAgent` dict (prompt by digest, model component, tools, skills, `interrupt_on`); MCP tools passed as in-process tools (new); nested `tools:*` checkpoints observed | `.claude/agents/*.md` | `.codex/agents/*.toml` | flag only |
| `async` | `AsyncSubAgent` on the Agent Server through the governed middleware (exists) | not native: Mission Control async subordinate (linked run) | same | same |
| `linked_run` | a Mission Control linked run on any lane (chain packet) | same | same | same |

State to parent (C11) stays the lineage graph with a fidelity label per child; `sync` children
on this lane are `full` (frames carry `subordinate_ref`), `async` children are `lifecycle_only`
unless the Agent Server frames are mirrored.

## 3. The cognition coordinate: Temporal workflow → activity → checkpoint → state as of

> **Built 2026-10-21 (turn 4).** P1-S4, P1-S5 and P1-S6 are implemented as described in
> [COGNITION-POINTS.md](../../../archive/provider-consolidation-2026-10/specs/COGNITION-POINTS.md) and the turn 4 entry of [CHANGES.md](CHANGES.md):
> the finished part to read is `domain/execution/cognition_points.py`, with
> `adapters/deep_agents/cognition_points.py` (the lane's observations),
> `application/execution/cognition_points.py` (the index) and
> `adapters/deep_agents/time_travel.py` (`read_as_of`, `seed_fork`) around it. Differences
> from the draft below: the table's `point_locator` and `roles` columns, the frame range
> resolved from provider keys rather than written by the frame writer, and the fork seed as a
> copy of the lineage up to the point (no restamping of ancestors is needed: only descendants
> of the expected source are classified).

### 3.1 What is already true (verified live)

The audit's §5 chain is real and deterministic: an `activity_attempt_observation` row names the
Temporal workflow id, run id, activity id and attempt; it belongs to a unit generation whose
`cognitive_namespace` is the LangGraph `thread_id`; every checkpoint in that thread is stamped
with the unit key, generation, invocation id and the attempt observation id; and the
settlement records the unit's source and result checkpoint ids. So "Temporal workflow →
activity → Deep Agents checkpoint" is persisted today **at unit-generation granularity**, and
the saver holds every intermediate step. What is missing is the index below the unit (turn and
step), the read-as-of surface on the operator API, and a governed way to seed a fork from any
of those checkpoints.

### 3.2 Position P1-S4: do not abstract the provider lifecycle; index it

The owner's instinct is right. Provider lifecycles differ in kind (LangGraph checkpoint, Claude
session file and `fork_session`, Codex thread and `thread/fork`, Cursor workspace snapshot,
hosted session cursors) and must not be squeezed into one generic "agent state" blob. What is
general is the **coordinate** and the **two behaviours** every lane implements against it:

- `mc.cognition_coordinate.v1`: `run_id`, `unit_key`, `execution_generation`,
  `harness_execution_id`, `turn_no`, `point` where `point` is a tagged union
  `{kind: "checkpoint", thread_id, checkpoint_ns, checkpoint_id}` (deep_agents),
  `{kind: "session_cursor", session_ref, turn_ref}` (Claude, hosted),
  `{kind: "thread_item", thread_ref, item_ref}` (Codex) or
  `{kind: "workspace_snapshot", snapshot_ref}` (Cursor). The point is opaque to the kernel and
  exact to the lane.
- `read_as_of(coordinate) → StateAsOf` (transcript up to the point, redacted channel facts,
  workspace file list or snapshot ref, budget consumed, frames range) with a `restore_level`
  achieved (`R0..R3`).
- `seed_fork(coordinate, patch) → ForkSeed` returning the level restored and the native
  artefacts created (new thread, copied session, snapshot checkout).

Both are lane ports (`application/execution/harness/protocol.py` additions:
`read_as_of`, `seed_fork`, declared in the v2 describe as `time_travel: {read: R?, fork: R?}`).
The kernel owns the index and the API; the lane owns the native semantics.

### 3.3 Position P1-S5: the index table, written by the kernel, reconciled from the saver

Add one common table, `cognition_point` (migration in `packages/mission-control-db-contract`,
written by the runtime role), with one row per observable point of a unit generation:

| Column | Source |
| --- | --- |
| `request_scope`, `run_key`, `unit_key`, `execution_generation`, `harness_execution_id`, `turn_no` | the unit generation and the session turn the point belongs to |
| `point_kind`, `point_ref` (jsonb: the lane's exact point), `parent_point_ref` | lane |
| `ordinal`, `source` (`input`, `loop`, `interrupt`, `resume`, `compaction`, `terminal`) | LangGraph `metadata.step` and `source` for this lane |
| `temporal_workflow_id`, `temporal_run_id`, `temporal_activity_id`, `activity_attempt`, `task_queue` | the `activity_attempt_observation` that wrote it (`belllabs_attempt_ref` stamp) |
| `frame_from_ordinal`, `frame_to_ordinal` | the frames recorded between this point and the previous one |
| `message_count`, `files_digest`, `channel_facts_digest`, `usage_delta` (jsonb) | redacted facts folded from the saver at write time |
| `budget_snapshot_ref`, `workspace_checkpoint_ref` | K11 per-turn workspace checkpoint when available |
| `seedable` | whether `seed_fork` may use it (false for an in-doubt or unverified lineage) |

Writers: (1) the Deep Agents adapter emits one `cognition_point` per root checkpoint when the
unit settles (it already walks the stamped lineage in `_capture_result`), stamped from the
attempt observation it holds; (2) the frame writer sets `turn_id` and the point's
`frame_from/to` ordinals (K09); (3) a reconciler re-derives rows from the saver when a crash
left a lineage unsettled, using the stamps. Reads never touch the saver for listing; only
`read_as_of` at `R3` opens the saver, through the registered reader, with the delta-channel
fold the inspection summary already uses (audit §4 item 4). Retention follows the forkable-run
pin (K11). The existing per-unit history endpoint becomes a view over this table and moves
from the technical facade to the operator API and MCP (K15).

Fill the dead columns while at it: `mission_run.temporal_workflow_id/run_id`,
`agent_session.checkpoint_namespace/checkpoint_ref`, `session_turn` gains `point_ref`, and
`provider_frame.provider_key` gets its checkpoint slot from the recorder (the key format
already reserves it).

### 3.4 Position P1-S6: fork from a checkpoint on this lane (R3)

A fork from "stage 1, activity, Deep Agents checkpoint X, adding new state" becomes:

1. The operator forks at a `cognition_point` (`ForkRequest.cognitive_seed` is already typed as
   `{unit_key, checkpoint}`; the refusal in `domain/policies/forks.py:491-496` is lifted only
   for lanes whose describe declares `time_travel.fork >= R3`).
2. The kernel creates the derived run and its fresh namespaces as today (snapshot plus packet,
   R0/R1), then calls `seed_fork` on the lane for the derived unit generation.
3. The Deep Agents `seed_fork` **copies** the checkpoint tuple (checkpoint, blobs, pending
   writes, and the delta-channel history up to X) into the derived unit generation's namespace
   under new stamps (new unit key, generation 1, new invocation id, new attempt ref), then
   applies the fork patch as an `aupdate_state` at that copied checkpoint (`as_node` the last
   node, values such as an added human message, extra `files`, or an edited `artifact_index`).
   It records a `checkpoint_transition` with `classification: reconstructed_from_fork` and
   `source_key` = the copied point. Copying, not branching in place, respects the namespace
   ownership rule (one owner per thread, `CheckpointNamespaceOwnershipError`) and keeps the
   source run immutable.
4. The derived unit then classifies as `interrupted` (pending tasks at X) or
   `terminal_unobserved` and runs as any resumed generation; the lineage graph records
   `restore_level: R3` with the source coordinate.

Workspace state at X comes from K11 (per-turn checkpoint of the backend files: the `files`
channel on `StateBackend` is already in the checkpoint; the Docker sandbox needs a per-step
snapshot or an upload of the slot files).

### 3.5 Keeping the other lanes separate

Each later sprint implements the same two ports with its own point kind: Claude maps
`read_as_of` to the transcript cursor and `seed_fork` to `fork_session` (R1 until truncation to
a turn is proven), Codex to `thread/fork` plus rollback (R3 candidate), Cursor to the workspace
snapshot (R2), hosted lanes to packet replay (R1). The index table and the coordinate contract
do not change; only `point_kind` does. This is the owner's "separate lifecycles, one way to
retrieve them".

## 4. Human control on this lane (C08)

**Position P1-S7.** Map `interrupt_on` to the approval broker: when the gate class requires a
human decision, the HITL middleware raises the LangGraph interrupt, the adapter records the
frame (`updates.interrupt` already lands) and binds a Postgres Human Task **before** the
activity returns `requires_action`; the operation parks in `waiting` instead of `in_doubt`; the
resolution resumes the same thread with `Command(resume=decision)` as a new turn of the same
generation. Timeout policy and reviewers come from the mission (K12). The `pending_interrupt`
reason in `_classify` becomes a normal `interrupted` classification when a bound Human Task
exists for the leaf.

## 5. Model defaults and provider factory (C13, D5)

**Position P1-S8.** Replace the OpenAI-only factory with a provider-neutral
`ExactModelFactory` keyed by the model component's `provider` (`openai`, `anthropic`, later
`bedrock`), using the installed `langchain-anthropic`; resolve `default` through an
installation catalog entry per (lane, role) recorded on the run. The Agent Server child graph
uses the same factory.

## 6. Work packages and proof

Order matters: the index and read surface come first because every later proof reads through
them. Tiers follow the program (§7.2); T0 is the offline stack of the audit, T2 adds a real model.

| WP | Builds | Proves | Tier | Depends on |
| --- | --- | --- | --- | --- |
| **WP-0 harness and ledger** | `fixtures/consolidation/*.mission.yml` runnable on the offline stack with lane parameter; `CAPABILITY-LEDGER.json` rows for deep_agents; a `deep_agents` launch-bindings block with real digests and a model name; a `missionctl` assertion runner over the operator API; fix the fixture grant so forks are callable (P1-A6) | the suite itself | T0 | owner model choice (D5) |
| **WP-1 cognition points (K09, K11, P1-S5)** | `cognition_point` migration; adapter writer; `turn_id` and checkpoint slot on frames; `session_turn.point_ref`; reconciler from the saver; unit-level history moved to the operator API and MCP; `read_as_of` port with the delta fold; `missionctl run points` and `run state-as-of` | C06 read at R3, C14 coordinate reads | T0 | — |
| **WP-2 boundary snapshots and turn forks (K08, K10, P1-S6)** | automatic snapshot at stage/verifier settlement and generation rollover; `seed_fork` port; Deep Agents copy-and-restamp seeding; `cognitive_seed` admitted for R3 lanes; lineage records `restore_level` | C06 fork from (iteration 2, turn K) with a patch, divergence asserted | T0 then T2 | WP-1 |
| **WP-3 shared configuration (P1-S1, S2, S3)** | `mc.agent_configuration.v1`, receipts, `DeepAgentsProjection`, manifest `provider_options`, subagent `kind`, hook scripts and kernel hook ports wired in production, memory channel, continuation policy from the manifest | C01, C10, C11 on FX-GD1 (probe MCP, skill, plugin, subagent, hook observed in use) | T0 then T2 | WP-0 |
| **WP-4 GD kernel (K01–K04, K03 session generation)** | clean `outputs/` per operation; authorable threshold and rollovers; session generation separate from iteration with the registered Deep Agents hydrator; verifier findings in the next packet | C02 on FX-GD2 (≥3 iterations, mid-iteration rollover, verifier failing once) | T0 then T2 | WP-1 |
| **WP-5 human control (K12, K13, P1-S7)** | `interrupt_on` → Human Task binding; timeout policy and reviewers from the mission; expiry receipts for settled-node injects; artifact injection (K14) into the backend | C07, C08 on FX-GD4 (allow, deny, timeout, worker kill and restart mid-turn) | T0 then T2 | WP-1 |
| **WP-6 SG kernel (K05–K07)** | cycle deliveries and governed cap; Goal Loop as a stage (K06, deferrable); fail on unresolvable refs | C03–C05 on FX-SG1–SG3 | T0 then T2 | WP-4 |
| **WP-7 model and runtime (P1-S8, C12)** | provider-neutral model factory and installation default; Docker sandbox with a kit layer that installs runtimes (or a pre-built image) and a declared network policy; `config:` values delivered (K19) | C12, C13 on FX-GD1 | T2 | D5 |
| **WP-8 describe and close** | v2 describe for `deep_agents` generated from the ledger (features, approval modes, compaction control, `time_travel` levels); `docs/knowledge/deep-agents-lane.md` corrected; `CLOSE.md` with spend | honest declaration | — | all |

Not in P1 (owner-accepted deferrals proposed): C09 Human Gate enrichment, C15 cross-provider
links, C16 live mutation (K17), Agent Server production persistence topology (ADR 0017,
separate database), async child frame mirroring.

## 7. Fixtures for this lane

The program's FX-GD1–GD4 and FX-SG1–SG3 run unchanged on the offline stack with `lane:
deep_agents`; three lane-specific additions:

- **FX-DA-POINTS**: after FX-GD2, list `cognition_point` rows for iteration 2 and assert each
  root checkpoint of the saver has exactly one row carrying its activity attempt, frame range
  and `message_count`; `read_as_of(point)` returns the same message identities the saver's
  delta history returns.
- **FX-DA-FORK**: fork from (iteration 2, executor, step K) with a patch that adds one human
  message and one file; assert the derived run's first checkpoint has the copied point as
  parent, new stamps, `restore_level: R3`, and that the derived executor's first model call sees
  the added message.
- **FX-DA-HITL**: a tool with `interrupt_on` raises; a Human Task exists before the activity
  returns; allow resumes the same thread; deny ends the turn with a receipt; timeout honours
  `keep_waiting`.

## 8. Owner decisions this design needs

| ID | Decision | Recommendation |
| --- | --- | --- |
| D5 | Model factory and default for the lane | provider-neutral factory; default `openai:gpt-5.4-nano` for T2 proofs, Anthropic as the second factory |
| P1-D1 | Accept the coordinate contract and `cognition_point` as the kernel index (P1-S4, S5) | **accepted 2026-10-21** (COGNITION-POINTS.md Q1); built in turn 4 |
| P1-D2 | Allow `cognitive_seed` forks for lanes declaring R3 (P1-S6) | **accepted 2026-10-21** (Q1): the source thread is copied up to the point into the derived namespace, never branched; built in turn 4 |
| P1-D3 | Subagent `kind` and `provider_options` on the manifest (P1-S2, S3) | accept; manifest stays single-schema |
| P1-D4 | Human control binding for `interrupt_on` (P1-S7) | accept with K12 defaults |
| P1-D5 | Live spend ceiling for T2 on this lane | set per fixture, small model only |
