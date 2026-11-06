---
type: Research
title: "P1 deep_agents audit: what the lane does today for Goal Directed and Stage Graph, with a live offline trace (2026-10-20)"
description: "Phase A of the deep_agents sprint: re-verification of the baseline rows against main, a provider fact sheet for deepagents 0.7.5 on LangGraph 1.2.10, the configuration surface the lane actually consumes, the persisted chain from Temporal workflow to LangGraph checkpoint, and the evidence from two live runs (Goal Directed and Stage Graph) on the disposable offline stack plus the Agent Server integration suite."
tags: [mission-control, providers, consolidation, deep-agents, audit, P1]
status: archived
archived: 2026-11-02
archived_from: providers/deep_agents/AUDIT.md
archived_reason: "P1 audit done"
---

> **Archived 2026-11-02** (P1 audit done). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# P1 deep_agents audit (2026-10-20)

Source: `main` at `0fc89d0b` in `platform/mission-control`. Paths are relative to
`src/mission_control/` unless they start with `tests/`, `docs/`, `scripts/`, `agent_server/`
or `packages/`. Labels follow the [baseline](BASELINE-2026-10-19.md): **[T]** tested,
**[U]** implemented, unproven live, **[D]** documented only, **[L]** evidenced live. A new
label **[L0]** marks evidence from the T0 offline stack of this audit (real Postgres 17, real
local Temporal, the production workers and configured API, but scripted cognition, so no
provider was paid and no model behaviour was observed).

## 1. Starting position

The lane has never been served live from the Run 2 private tooling: its `launch-bindings.json`
has no `deep_agents` block and its `capability-pins.json` lists no models, checkpointers,
sandboxes or skills (keys inspected 2026-10-20). The only committed Deep Agents binding is the
scaffold `deployments/examples/manifest-launch-bindings.deep-agents.example.json`, which still
carries `OWNER-SELECT` placeholders for the model name, authority, workspace and policy refs.
Default pins (`infra/capability-pins/research-capabilities.json`) exist for one OpenAI model
(`model.wp-cp-040`, no model name), one checkpointer, one store, one `state` sandbox, the
`agent-browser` skill and tool, and the Firecrawl and Tavily MCP servers.

The Run 2 register assigns no lane issue to P1; it inherits every kernel item K01–K21.

## 2. How the lane runs (as built)

| Aspect | As built | Label |
| --- | --- | --- |
| Host | Allowed on Windows, Linux and macOS (`bootstrap/preflight.py:322-341`); the worker uses a selector loop on Windows (`bootstrap/worker.py:801-806`). The Agent Server is needed only for async subordinates (ADR 0006; the materializer accepts only `local_in_worker`, `adapters/deep_agents/materializer.py:498-511`) | T, L0 |
| Composition | Registered always (`adapters/temporal/deployment_composition.py:556-559`); every pinned model gets `OpenAIExactModelFactory` (`:403-405`); sandbox factories `state`, `docker`, `langsmith` (`:407-417`); one Postgres saver and store per worker keyed by the pinned digests (`:434-435`); the adapter exists only when that persistence exists (`:1140-1160`); the harness wrapper at `:1258-1260` | T |
| Activity shape | A unit generation runs **one `operation.execute` activity** and inside it **one LangGraph invocation** of the compiled deep agent (`adapters/deep_agents/adapter.py:189-457`). `lane.turn` segments are used only when `MISSION_CONTROL_LANE_SEGMENT_LOOP=true` (`bootstrap/settings.py:342`), and even then the harness runs the same adapter once per turn (`application/execution/harness/deep_agents_harness.py:200-232`) | T, L0 |
| Thread namespaces | Stage Graph: `belllabs/stage/{unit_key}/gen/{N}`, one thread per unit generation. Goal Loop, generation 1: `belllabs/goal/{run}/epoch/{e}/session/{session_generation}/role/{role}`, **one thread per role shared across iterations**; generation > 1: `.../unit/{unit_key}/gen/{N}` (`domain/execution/checkpoint_lineage.py:133-145`) | T, L0 |
| Checkpoint lineage | Every checkpoint is stamped with `belllabs_unit_key`, `_execution_generation`, `_invocation_id`, `_binding_digest`, `_state_schema_digest` and `_attempt_ref` (`checkpoint_lineage.py:41-55, 312-329`). Before any provider work the adapter classifies the namespace as `not_submitted`, `interrupted`, `terminal_unobserved` or `in_doubt` (`adapter.py:859-986`); a LangGraph `interrupt()` is `in_doubt` (`:970-975`). One `checkpoint_transition` row per unit generation records source and result keys (`adapters/postgres/operations/checkpoint_lineage.py:983-1036`) | T, L0 |
| Inject | `cancel_and_replace`; the replacement turn continues the same thread from the interrupted leaf with one more user message and the same invocation id (`adapter.py:254-312`) | T |
| Frames | `DeepAgentFrameRecorder` turns `astream` v2 parts into Provider Frames with `langgraph_step` but **no checkpoint id** (`adapters/deep_agents/frames.py:173-205, 352-386`); the result checkpoint id travels only in the `run_result` body excerpt (`:283-295`). The harness `observe` yields a single terminal frame per turn (`deep_agents_harness.py:234-262`) | T, L0 |
| Snapshot and fork | Harness `snapshot` is emulated from the captured checkpoint plus the mount manifest (`deep_agents_harness.py:264-283`). Run snapshots name each unit's `result_checkpoint` as a `QualifiedCheckpointKey` (observed in the drill) but a `cognitive_seed` fork is refused `cognitive_seed_not_supported` (`domain/policies/forks.py:491-496`; HTTP 422 observed) | T, L0 |
| Continuation | `DeepAgentsSessionHydrator` and `StateBackendWorkspaceSnapshots` exist (`adapters/deep_agents/compaction.py:503-653`) but are constructed only in tests; production registers hydrators for Cursor, Claude and Codex only (`deployment_composition.py:590-620`, `provider_lane_composition.py:232-244`), so `request_continuation` raises `unsupported_control` (`application/context/hydrators.py:62-69`) | gap |
| Compaction | `ObservedSummarizationMiddleware` always replaces the stock summarization middleware so a compaction is emitted as frames (`materializer.py:314-323`, `compaction.py:128-160`). The trigger comes from worker `Settings`, not the manifest (`deployment_composition.py:576-587`); `ContextPressurePolicy.from_manifest` has no production caller | T |
| Usage and cost | Tokens come from `usage_metadata` on messages and from sync subagent calls observed at the chat-model boundary (`adapter.py:1325-1347, 1414-1432`); cost is never computed. The drill shows settled tokens per turn from the scripted model, so "tokens 0" in the baseline is unverified for a real model | U |
| Describe | v1, `qualified=True` (`application/execution/harness/describe.py:51-105`). Because v1 has no `features`, `approval_modes`, `compaction_control` or `enforcement_coverage`, admission refuses every approval class except `workflow_gate` and every observation beyond terminal result, tool lifecycle and usage (`domain/execution/lane_requirements.py:146-183`) | over-claims |

## 3. Configuration surface the lane consumes

The manifest surface is lane-neutral (`domain/authoring/manifest.py:579-594`, `manifest_v2.py:312-329`,
`mission_environment.py:280-288`): instructions per node, model, sandbox, workspace and skills,
capabilities (MCP servers with tool subsets), agents (overlay `readonly`, `is_background`,
`model`), hooks, plugins, budgets, governors, side effects, and in v2 `auth`,
`execution_environment`, `continuation`, `requires`, `materialization`, `observation`,
`placement`, `lanes`, `lane_environments`, plus `kit`, `variables`, `secrets`, `network`,
`git` and `provider_environment`. There is **no lane-specific block**: `ManifestModel` forbids
extra keys (`manifest.py:409-415`); the only per-lane repetition is `lane_environments`.

What reaches a Deep Agents binding, and how:

| Item | Path | Deep Agents today |
| --- | --- | --- |
| Instructions | node `instruction` → prompt segments → `system_prompt` of `create_deep_agent` (`adapter.py:781-810`) | system prompt only; no `memory_refs` (dropped before the binding), no AGENTS.md layering (ADR 0044) |
| Model | `model_profiles` → `DeepAgentModelComponent` by digest → OpenAI factory; settings allow-list (`materializer.py:198-234`) | OpenAI only; no installation default (D5) |
| MCP | `capabilities[kind=mcp_server]` → `DeepAgentMCPServerComponent` → in-process `MultiServerMCPClient` tools, schema digests verified (`materializer.py:581-630`) | stdio and remote, exact |
| Skills | `workspace.skills` → bundle by digest uploaded to the backend under `/skills` (`materializer.py:527-570`) | exact |
| Tools | pinned tools by digest and schema (`materializer.py:572-579`) | exact |
| Hooks | catalog hook scripts → `HookScriptMiddleware` (`materializer.py:388-437`) | **refused at manifest launch** (`application/authoring/manifest_launch_inputs.py:784-792`); the binding compiler has no `hook_scripts` input (`domain/execution/materialization.py:107-129`); production registers no kernel hook ports, so the four kernel hooks run against null ports (`adapters/deep_agents/hooks.py:236-243`, `deployment_composition.py:436-445`) |
| Plugins | expanded by `render_host_files` for file lanes | refused at launch (same line) |
| Subagents | neutral `mc.subagent_profile.v1` (`domain/capabilities/subagents.py:31-60`) ↔ `SyncSubagentProfile` (`domain/execution/contracts.py:687-698`) → `SubAgent` dicts (`materializer.py:439-495`, `adapter.py:766-779`) | refused at launch; the two vocabularies are bridged only in the unused `InProcessProjection` (`application/agentic_components/projections.py:1348-1446`); no MCP on children; filesystem permissions stripped beside a sandbox |
| Async subagents | `AsyncSubagentContract` (`contracts.py:743-788`) → governed middleware (`adapter.py:213-223`, `async_subagents.py`) → hosted graph (`agent_server/langgraph.json`, `adapters/agent_server/async_subagents/graph.py:35-48`) | OpenAI-only hosted graph; spawning off by default (`settings.py:105`) |
| Sandbox | `sandbox_profiles` → `state` / `docker` / `langsmith` factory | Docker is read-only, no network; no Environment Kits (`application/environments/requirements.py:38,112`) |
| Kit, variables, secrets, network, git | v2 additions | not materialized; compile warnings only (`application/authoring/manifest_v2_admission.py:237-247`) |
| Continuation policy | v2 `continuation` | digested into other lanes' `policy_digest`; ignored for Deep Agents |
| HITL | `interrupt_on` per tool is a `create_deep_agent` argument (fact sheet §5) | never set; interrupts classify `in_doubt` |

## 4. Provider fact sheet: deepagents 0.7.5 on LangGraph 1.2.10 (installed, inspected 2026-10-20)

1. **Agent construction.** `create_deep_agent(model, tools, system_prompt, middleware, subagents,
   skills, memory, permissions, backend, interrupt_on, response_format, state_schema,
   context_schema, checkpointer, store, name, cache)`.
2. **Sync subagents.** `SubAgent` TypedDict: `name`, `description`, `system_prompt`, optional
   `tools`, `model`, `middleware`, `interrupt_on`, `skills`, `permissions`, `response_format`.
   `CompiledSubAgent` wraps any runnable whose state has `messages`. Children run in nested
   checkpoint namespaces `tools:<id>` of the parent thread (4 nested checkpoints per child call
   in the drill).
3. **Async subagents.** `AsyncSubAgent`: `name`, `description`, `graph_id`, optional `url`,
   `headers`; `AsyncSubAgentMiddleware(async_subagents=, system_prompt=)` exposes start, check,
   list and cancel tools over a LangGraph client. Mission Control replaces the stock middleware
   with `BellLabsAsyncSubagentMiddleware` so each child is reserved and linked first.
4. **Checkpoints and time travel.** Every super-step writes a root checkpoint with `metadata.step`
   and `metadata.source` (`input`, `loop`) and copies the invocation `metadata` onto it. Reads
   are by `configurable.{thread_id, checkpoint_ns, checkpoint_id}`; `aget_state_history` walks
   parents; `aupdate_state(config, values, as_node)` at a past checkpoint creates a new child of
   that checkpoint (a branch), and invoking with `checkpoint_id` pinned continues from it.
   **`messages` is a `DeltaChannel`** in LangGraph 1.2: a checkpoint's `channel_values` holds
   `artifact_index`, `child_result_index`, `context_manifest`, `files`, `skills_metadata` but not
   the messages; they come from `saver.aget_delta_channel_history(config, channels=["messages"])`
   or from the compiled graph's `aget_state`. The drill read the executor's messages as of step 4
   and step 14 this way.
5. **HITL.** `interrupt_on: dict[tool_name, bool | InterruptOnConfig(allowed_decisions,
   description, args_schema, when)]` wires `HumanInTheLoopMiddleware`; a tool call matching it
   raises a LangGraph `interrupt()` that must be resumed with a `Command(resume=...)`.
6. **Compaction.** `SummarizationMiddleware(model, backend, trigger=ContextSize | TriggerClause
   | list, keep=('messages', 20), ...)` summarizes in place and writes the summary to the backend.
7. **Skills and memory.** `SkillsMiddleware(backend, sources)` lists `SKILL.md` files from
   backend paths with progressive disclosure; `MemoryMiddleware(backend, sources)` loads memory
   files (an AGENTS.md-like channel) into the system prompt and lets the agent `edit_file` them.
8. **Backends.** `StateBackend` (in-state files), sandbox backends (Docker, LangSmith) that
   implement `SandboxBackendProtocol`; filesystem `permissions` are refused beside an executable
   sandbox.
9. **Agent Server.** `agent_server/langgraph.json` serves `belllabs_async_technical_child` and
   three qualification graphs with custom auth (`deployment_auth:auth`) over `langgraph dev`
   (in-memory runtime locally; `make agent-server`, port 2024).

## 5. The persisted chain from Temporal to LangGraph (verified on the drill database)

```text
root workflow     mc/{inst}/{app}/run/{run_id}                                   [derived; mission_run.temporal_* never written]
  └ operation wf  {root}/operation/{semantic_attempt_id}                        [derived; persisted only inside activity_attempt_observation]
       └ activity operation.execute                                              [activity_attempt_observation: workflow id, run id, activity id, attempt, worker, namespace, expected_source]
            └ activation (unit_key) → attempt (unit_key:gen:N) → runtime_unit_generation (cognitive_namespace = thread_id, lease_holder = observation id)
                 └ harness_execution (one per generation; native_execution_refs = [invocation_id])
                      └ agent_session (native_session_ref = thread_id; checkpoint columns NULL)
                           └ session_turn (turn_no, native_turn_ref = invocation_id; no checkpoint column)
                                └ provider_frame (langgraph step on message chunks; no checkpoint id)
                 └ checkpoint_transition (source / result / result_parent checkpoint ids; one per generation)
                 └ cognitive_namespace (head checkpoint per thread)
                      ═ string equality on invocation_id ═  mission_control_runtime.checkpoints (thread_id, checkpoint_ns, checkpoint_id, parent, metadata stamps incl. belllabs_attempt_ref)
```

Persisted today: everything above the double line, plus the stamped checkpoints themselves.
Missing: a per-step or per-turn index in `mission_control`, a checkpoint id on frames and
turns, the activity task queue, the Temporal ids on `mission_run`, and any
`continuation_checkpoint.runtime_checkpoint_ref` (always NULL). The checkpointer role cannot
read `mission_control` (`packages/mission-control-db-contract/runtime/descriptor.json:44`), so
joins across the two schemas happen in the application. `ExecutionLineageEnvelopeV2`
(`domain/graph_runtime/definitions.py:839-884`) already names every field of this chain,
including `activity_id`, `task_queue_id`, `agent_thread_id` and `agent_checkpoint_ref`, but is
exported as a schema only.

Read models: the per-unit checkpoint history and redacted state summary
(`application/execution/inspection.py:515-593, 780-830`; routes
`interfaces/http/runtime_inspection.py:145-194`) are mounted **only in the technical facade**
(`bootstrap/technical_api.py:259`). The configured operator API serves
`/runs/{id}/inspection`, `/snapshots`, `/forks`, `/transcript`, `/frames/tail` and
`/checkpoints` (sealed continuation checkpoints) (`interfaces/http/mission_control.py:311-420`,
`transcript.py`, `continuation.py`), none of which accepts a unit, turn or checkpoint
coordinate.

## 6. Live evidence (T0 offline stack, 2026-10-20)

Stack: `scripts/offline_operator_stack.py` (fresh `mct_*` database on the disposable Postgres 17
`mc-ft-disposable-pg17`, local Temporal dev server on 127.0.0.1:17233, the production workers
with the scripted `TechnicalModel` and one in-process sync subagent plus the qualification MCP
server, the configured API with a signed operator token). Private evidence (git-ignored):
`.scratch/pc-p1-deep-agents/drill-gd/` and `drill-sg/` (stack log, transcript, snapshot,
`pg_dump` of both schemas, run ids). No provider was called.

### 6.1 Goal Directed run `84341b2b-8825-57b0-9b05-c0a4497e3ae4`

- Start to `run.completed` in 63 s; 2 iterations (executor, verifier each), outcome `completed`;
  the `missionctl wait` wake arrived as `terminal_result` (inbox seq 3).
- Rows: 4 `activation`, 4 `attempt`, 4 `runtime_unit_generation`, 4
  `activity_attempt_observation` (one `operation.execute` attempt each, activity id `1`,
  attempt 1), 4 `checkpoint_transition`, 2 `cognitive_namespace`, 4 `harness_execution`,
  2 `agent_session` (one per role thread), 4 `session_turn` (turn 1 and 2 per session, so the
  turn counter spans iterations), 86 `provider_frame`, 61 `mission_event`.
- Checkpoints: 44 root checkpoints (11 per unit, steps −1..9 then 10..20 in the shared role
  thread) and 16 nested `tools:*` checkpoints (4 per sync-subagent call). Iteration 2's executor
  was pinned to iteration 1's result checkpoint (`expected_source_checkpoint` =
  `1f1cc894-136b-…`) and its first checkpoint has that id as parent, so the thread is one
  linear lineage across iterations. Every checkpoint carries the unit, generation and
  `belllabs_attempt_ref` stamps.
- Time travel read: the saver's delta-channel history returned the executor's messages as of
  step 4 (human packet, `task` call, child result) and as of step 14 (the whole iteration 1
  plus the iteration 2 packet and first `task` call).
- Snapshot at the head succeeded (`boundary_kind: goal_verifier_settled`, projection version
  26) and lists each unit as a `reuse_candidate` with its `result_checkpoint` key;
  `sandbox_snapshot_refs` is empty on the `state` backend. A fork with a `cognitive_seed`
  naming executor step 4 was refused HTTP 422 `cognitive_seed_not_supported`. A plain fork
  returned 403 because the drill grant lacks the fork path's second permission
  (`application/missions/runtime.py:94`); the fork path itself is proven offline by the RRM-006
  suite. `GET /runs/{id}/checkpoints` listed no sealed continuation checkpoint.
- Usage: each turn settled `input 8 / output 12` tokens from the scripted model;
  `cost_micros unknown`; the inspection `usage_disposition` stayed `unknown` on the session rows.

### 6.2 Stage Graph run `092b6f58-c45a-5ec3-9d83-92ad56994cab`

- `draft` → declared wait `stagegraph-wait:release-review` (the run parked in lifecycle
  `waiting`) → `satisfy_wait` command (`accepted_pending_application`, applied at the family
  boundary) → `review` → `completed`; 2 accepted outputs (`artifact:rrm009:draft:…`,
  `artifact:rrm009:review:…`), 4 settlements.
- Rows: 2 units, each in its own thread `belllabs/stage/{unit_key}/gen/1` with no
  `expected_source` (fresh namespace), 11 root checkpoints each (steps −1..9), 8 nested
  subagent checkpoints, 2 `context_selection` rows of purpose `stage_start` (the review stage's
  packet carried the draft's accepted output).

### 6.3 Agent Server

`make agent-server` (`langgraph dev --config agent_server/langgraph.json --port 2024`) served
`/ok` and `/info` (runtime in-memory, custom auth: `bearer token required` on `/assistants/search`).
`tests/integration/agent_server/test_canonical_server_local.py` passed 3/3 in 38 s: authenticated
bounded child run and cancel, profile rollover denying the old graph, and authenticated
interrupt-resume plus thread copy on the served child.

## 7. Verdict per capability (C01–C16)

| ID | Verdict on `main` | Evidence |
| --- | --- | --- |
| C01 seed and spawn | **partial [T, L0]**: instructions (system prompt), model (OpenAI), stdio and remote MCP, skills, pinned tools, state or Docker sandbox, compaction middleware. Missing: hooks, plugins, subagents, memory and AGENTS.md layering from manifests; env kits; `config:` values; a default model | §3; drill: MCP tool `lookup_binding_marker`, skill bundle and sync child observed in use |
| C02 GD progression | **partial [L0]**: ≥2 iterations with shared role threads proven; no threshold crossing possible (`max_rollovers=0` lowering, K02); verifier findings not delivered (K04); no session generation rollover (K03) | §6.1 |
| C03 SG progression | **partial [L0]**: two stages, declared wait, dependent packet; no mid-stage threshold | §6.2 |
| C04 dependent transfer | **[L0]** schema outputs and packet proven on `state` backend; K01 `outputs/` hygiene and K07 unresolved refs untested for this lane | §6.2 |
| C05 cycles | **[D]** untested on this lane | baseline §3 |
| C06 retrieve, time travel, fork | **R0 only [T, L0]** through the operator API; R3 reads are possible from the saver (proved) and listed per unit by the technical facade; fork from a checkpoint refused by policy | §5, §6.1 |
| C07 intervene | **[T]** queue, add_context, inject (`cancel_and_replace` continuing the thread), cancel, pause (boundary); K13/K14 open | §2 |
| C08 durable human control | **gap**: interrupts are `in_doubt`, no Human Task binding, `interrupt_on` unused | §2, §4 item 5 |
| C09 Human Gate | **[T]** `mc.human_gate.v1` is lane-neutral; deferred to its sprint | baseline §6 |
| C10 subagent configuration | **partial [T]**: sync children with model, prompt, tool and skill subsets (no MCP, no own sandbox); async children OpenAI-only; neither reachable from a manifest | §3 |
| C11 subagent state to parent | **[T, L0]** sync children appear as `subordinate` frames and usage; async children through the governed service and lineage graph | §6.1 transcript (`technical-child` frames) |
| C12 sandbox and runtime provisioning | **gap**: Docker sandbox read-only, no network, no kits | §3 |
| C13 model selection and defaults | **gap**: OpenAI-only factory, no installation default (D5); `langchain-anthropic 1.5.4` is installed | §2 |
| C14 coordinator peek | **[L0]** inspect, transcript, frames and wait/wake proven on both programs; no unit, turn or checkpoint coordinate on the operator API (K15) | §5, §6 |
| C15 links | **[D]** untested | baseline §8 |
| C16 mutation | **[D]** absent (K17) | baseline §6 |

## 8. Items this audit adds to the register

| ID | Finding | Destination |
| --- | --- | --- |
| P1-A1 | The per-unit checkpoint history and summary reads exist but are mounted only in the technical facade, so a coordinator on the operator API cannot see them | K09/K15 in P1 |
| P1-A2 | Provider frames and session turns carry no checkpoint id; `agent_session.checkpoint_*` and `continuation_checkpoint.runtime_checkpoint_ref` are always NULL | K09/K11 in P1 |
| P1-A3 | Production registers no kernel hook ports; the stop fence, intent ledger, frame capture and usage hooks run against null implementations | P1 build (C01, C07) |
| P1-A4 | Manifest launch for `deep_agents` refuses hooks, plugins and subagents outright, and the neutral subagent profile is not bridged to `SyncSubagentProfile` | P1 build (C01, C10) |
| P1-A5 | `messages` is a LangGraph `DeltaChannel`: any read-as-of must fold delta history or use the compiled graph; the inspection summary already does the former | P1 design (C06) |
| P1-A6 | The drill grant (`operator` + `fork_operator`) cannot call the operator-API fork route; the fixture roles and the route's permission pair disagree | K21 tooling |
| P1-A7 | The example launch bindings and the default pins carry no model name; `settings.openai_model` (`gpt-5.4-nano`) and `settings.anthropic_model` (`claude-haiku-4.5`) exist but are not the lane's default resolution | D5, C13 |
