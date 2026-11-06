---
type: Specification
title: "P1 subagents: child capabilities like the parent, async children that really run on the Agent Server, and the contract → discrimination → routing → materialization decision for subagents across lanes (packet for turn 3, 2026-10-20)"
description: "The next part of the deep_agents sprint. Starting state of sync and async subagents with citations, the exact async wire path, the per-lane native forms, the owner's recorded answers (seeded children with their own full capability set plus an explicit inherit-from-parent child per provider; the authoring rule decided for the coordinator), the refined async recommendation awaiting the owner, the work packages, what to collect for the later state and communication work, and the proof tiers."
tags: [mission-control, providers, consolidation, deep-agents, subagents, agent-server, P1]
status: archived
archived: 2026-11-02
archived_from: providers/deep_agents/SUBAGENTS.md
archived_reason: "built (turn 3); concept deep-agents-children"
---

> **Archived 2026-11-02** (built (turn 3); concept deep-agents-children). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# P1 subagents (turn 3 packet)

Read [PROCESS.md](../../../provider-consolidation-2026-10/PROCESS.md) first. §4 records the owner's answers (Q1–Q7). **Turn 3 (2026-10-20) built WP-S1 and WP-S2**: see [CHANGES.md](../../../provider-consolidation-2026-10/providers/deep_agents/CHANGES.md) for the modules, the tests and the proofs; §3.1 is implemented with one amendment (the support matrix is served beside the describe document, see §3.1 point 1); §7 is collected below. WP-S3 (Q3 "A"), WP-S4 (Q4) and WP-S5 are the next turn's.

## 1. Goal of this part

1. A Deep Agents child can be seeded with the same kinds of capability as a parent: MCP
   servers, Agent Skills and plugins (C10), chosen from the catalog, materialized natively.
   Separately and explicitly, the provider's **inherit-from-parent** child (the general-purpose
   subagent every framework has) is a first-class, receipted thing rather than an implicit one.
2. A `kind: async` subagent profile on a manifest-launched Deep Agents run actually spawns a
   child on the Agent Server, the child runs with the profile's prompt, model and tools, and its
   result reaches the parent (C10, C11).
3. The subagent contract → discrimination → routing → materialization chain is decided and
   written down for every lane, so the coordinator agent and the owner author subagents one
   way and each lane adapter does the translation.

Out of scope for this part, but **collected** while working (§7): subagent → parent
communication beyond the result; saving and restoring child state for forks and lifecycle
inspection (the cognition-point work, WP-1/WP-2).

## 2. Starting state (verified 2026-10-20 on `main` plus turn 2)

Paths are relative to `src/mission_control/`.

### 2.1 Sync children (in-process `SubAgent`)

| Fact | Where |
| --- | --- |
| A manifest `agents:` entry on a Deep Agents node is read from its catalog row and adapted into a `SyncSubagentProfile` (inline prompt pinned by digest, model inherit or profile, tools / Skills / MCP narrowed from the parent's selection, a state and a context slice, ceiling-bounded budget) | `application/authoring/lanes/deep_agents.py::_sync_child` (turn 2) |
| The binding compiler enforces the child's tools, Skills and MCP refs ⊆ the parent's | `domain/execution/materialization.py::compile_deep_agent_execution_binding` |
| The materializer gives the child its tools, the parent's loaded MCP tools for its servers, its Skill roots and a filesystem permission pair; `readonly` cannot be enforced beside a sandbox; `max_turns`, `background`, `context_mode: fork` have no native form (receipt `degraded`) | `adapters/deep_agents/materializer.py::_materialize_subagents` |
| deepagents 0.7.5 `SubAgent` accepts `tools`, `model`, `middleware`, `interrupt_on`, `skills` (backend paths), `permissions`, `response_format` | installed package, `deepagents.middleware.subagents` |
| **deepagents auto-adds a `general-purpose` child to every parent** ("has access to all tools as the main agent", the parent's model) unless the harness profile disables it (`GeneralPurposeSubagentProfile(enabled=False)`). Mission Control never configures it, so every Deep Agents parent today carries an implicit, unreceipted inheriting child that can call every parent tool, MCP tools included | `deepagents.graph.GENERAL_PURPOSE_SUBAGENT`; `adapters/deep_agents/adapter.py::_compile` passes no profile |
| **Plugins are not expanded for children**: a profile cannot name a plugin, and a plugin selected by the parent contributes nothing to a child | gap |
| **Child-only capabilities are impossible** today: a child may only narrow the parent's set | changes under the owner's Q2 answer (§4) |

### 2.2 Async children: the exact wire path

How the middleware reaches the server and what is sent, as built:

1. The parent's binding carries `AsyncSubagentContract`s (sealed by the lane adapter from
   `ManifestLaunchBindings.deep_agents_async_graphs`). Each carries `agent_protocol_url` and
   `deployment_credential_ref`. **The URL comes only from the launch binding**; the settings
   `agent_server_endpoint` / `agent_server_api_key` are read by no source code
   (`bootstrap/settings.py:107-108`).
2. `DeepAgentsAsyncSubagentAdapter._tools` builds the stock deepagents
   `AsyncSubAgentMiddleware` with one `AsyncSubAgent` spec `{name, description, graph_id,
   url: contract.agent_protocol_url, headers}`; `headers` is `Authorization: Bearer bl1.<claim>`
   (an HMAC scope claim minted from the secret behind `deployment_credential_ref` for the
   parent's `request_scope`, refreshed when it lapses) plus the scope header
   (`adapters/deep_agents/async_subagents.py:126-186`). The LangGraph SDK client is created
   with the same URL and headers (`:188-201`).
3. `start` sends, in order (`:214-269`):
   - `POST /threads` with `thread_id = child_execution_id` (the persisted Mission Control
     child id, so the thread is idempotent), `if_exists: do_nothing`, `graph_id`, and metadata
     `belllabs_child_execution_id`, `belllabs_parent_run_id`, `belllabs_parent_binding_id`,
     `belllabs_contract_digest`, `request_scope`;
   - `GET /threads/{id}/runs` (adopt an existing run with the spawn key; refuse two);
   - `POST /threads/{id}/runs` with `assistant_id = contract.graph_id`,
     `input = {"messages": [{"role": "user", "content": <objective>}]}`, metadata plus
     `belllabs_spawn_key`, `multitask_strategy: reject`.
   **Nothing else travels**: no `config`, no `context`, no prompt, model, tools or Skills. The
   objective is the `description` string the parent model wrote into `start_async_task`.
4. Server side: `deployment_auth` verifies the claim and scopes threads by
   `metadata.request_scope`; `entrypoints.child(config)` is an **async graph factory the
   server calls per run with the run's config** (`adapters/agent_server/entrypoints.py:11-13`),
   but `async_subagents/graph.py::graph(config)` ignores the config and builds the fixed
   technical child once per process (its own prompt, OpenAI `gpt-5.6-luna`, one tool,
   `StateSandboxFactory`), stamping its served identity (graph id, revision, binding digest)
   into thread state.
5. Verification: before submitting, the parent reads `GET /belllabs/async-subagents/served-graphs`
   and requires the contract's identity to match; after completion it re-reads the identity
   stamped in thread state (`:194-210, 302-321`).
6. Check and admission: `check_async_task` reconciles; during the parent's cognition the result
   is always `completed_pending_admission`; admission and settlement happen after cognition in
   `AsyncChildCompletion.complete` through the one registered policy
   (`policy:async-result:technical-child@1`).

The platform mechanism for dynamic children exists: a graph factory receives `config`, and
`runs.create` accepts `config={"configurable": {...}}`; `assistants.create(graph_id, config)`
pins such a config under a stable assistant id (LangGraph SDK signatures, inspected).

| Requirement for a manifest-launched async child | Status | Where |
| --- | --- | --- |
| Contract sealed from the profile and `deep_agents_async_graphs` | exists (turn 2) | `lanes/deep_agents.py::_async_child` |
| Served graph identity authored to match the server | operator-authored; no tool emits the digest | `async_subagents/bindings.py:49-117`; served-graphs endpoint |
| Deployment credential in the operation's `secret_refs` | **blocker**: `node()` adds only the model and sandbox refs, so `_headers` fails | `manifest_launch_inputs.py` (`node`); `async_subagents.py:126-146` |
| Dependency class compatible with the worker factory | **blocker**: the graph binding defaults to `{nonblocking}`, the factory to `required_blocking`; spawn rejects the mismatch | `lanes/deep_agents.py`; `deployment_composition.py:476-478`; `service.py:366-367` |
| `result_admission_policy_ref` registered | one ref only | `deployment_composition.py:338-343, 974-984` |
| `objective_schema_ref` / `result_schema_ref` resolved | missing: stored, never validated | `domain/execution/contracts.py:796-797` |
| Profile prompt, model, tools reach the child | missing: fixed technical child | §3.2 |
| Result reaches the parent during cognition | missing | `async_subagents.py:797-807`; `deployment_composition.py:915-925` |
| Worker `ASYNC_SUBAGENT_SPAWNING_ENABLED=true`, base role; server token, `OPENAI_API_KEY`, profile `runtime` | exists (names) | `settings.py:105`; `agent_server/runtime.env` |
| Server persistence | `langgraph dev` in-memory; ADR 0017 not used locally | `http_app.py:38-72` |

Tests: `tests/integration/agent_server/test_canonical_server_local.py` (real server, no parent;
passes), `tests/unit/integrations/test_async_subagent_submission_fence.py` (offline), and the
closest end to end,
`tests/acceptance/mission_control/test_postgres_children_and_artifacts.py::test_real_hosted_async_children_complete_and_settle_in_postgres`
(real server, Postgres, Temporal, Stage Graph; hand-built binding; stubbed parent and child
models; injects the token ref by hand). The live RRM-013 test exists only as a stale `.pyc`.

### 2.3 Every lane's native subagent form (for the routing decision)

| Lane | Native form | Fields that survive the neutral profile | Inherit-from-parent child |
| --- | --- | --- | --- |
| deep_agents sync | in-process `SubAgent` | model, tools, skills, mcp_servers (turn 2), readonly (permissions, not beside a sandbox), interrupt_on | built-in `general-purpose` (all parent tools, parent model), auto-added |
| deep_agents async | Agent Server graph | name, description, budget; tools/MCP as an unenforced ceiling | none |
| cursor_local / cloud | `.cursor/agents/<name>.md` (+ inline, max 20) | model, readonly, background | built-ins `explore`, `shell`, `browser`, … (reserved names) |
| claude_agent_sdk | `.claude/agents/<name>.md` | model, tools, skills, mcp_servers, readonly (`permissionMode: plan`), background, max_turns | built-in `general-purpose` (inherits the parent's tools); inline path is dead code |
| codex | `.codex/agents/<name>.toml` (project trust) | model, readonly (`sandbox_mode`) | none verified |
| claude_managed / codex_agents | provider flag | none | `multiagent` flag only |

Compile loads the profile body but validates only host support; nothing at compile checks
`kind`, `placement`, capabilities or the prompt for a lane (`manifest_service.py:1289-1306,
1544-1559`). The body is first acted on at launch.

## 3. The decision: contract → discrimination → routing → materialization for subagents

### 3.1 Decided (owner answers of 2026-10-20, see §4)

**Two child shapes, both explicit.** Every provider has a general child that inherits from the
parent, and every provider can host a seeded child with its own capabilities. The contract says
which one a profile is:

- `capabilities: inherit` — the provider's inheriting child. Deep Agents: the built-in
  `general-purpose` `SubAgent` (all parent tools, MCP included, the parent's model), which
  Mission Control now configures and receipts explicitly instead of letting deepagents add it
  silently (and disables when the mission does not declare it). Claude: the built-in
  `general-purpose` agent. Cursor: its built-ins. Codex and hosted lanes: `unsupported`,
  refused when required.
- `capabilities: seeded` (the default when a profile selects anything) — the child's own
  catalog selection: `skills`, `mcp_servers`, `plugins` (a plugin is an amalgamation of the
  former; its hooks, prompts and resources are deferred), `tools`, resolved from the catalog at
  compile like the parent's, **not limited to the parent's selection**, admitted against the
  node's delegation ceiling and grant (MCP credentials resolve for the child the same way they
  resolve for a parent). Deep Agents materializes them as the child's own tools, MCP tools and
  Skill roots; file lanes write them into the agent file.

**One authoring rule for the coordinator.** The coordinator writes the neutral
`mc.subagent_profile.v1` core and nothing lane-specific unless the lane's support matrix names
the field. The combinatorial complexity is carried by the system, not by the author:

1. the per-lane **subagent support matrix** is generated from the lane adapters (what survives,
   what degrades, what is lane-only) and exposed where the coordinator already looks:
   `missionctl lane describe <lane>` shows it as `subagent_fields` (`native | degraded |
   unsupported` per `SUBAGENT_FIELDS` name). *Built 2026-10-20 as
   `application/authoring/lanes/support.py`, served beside the describe document by
   `GET .../lanes/{profile}`; folding it into the persisted `mc.lane_describe.v2` needs a
   lane-describe migration (the seeded describe documents are immutable, see
   `tests/unit/harness/test_lane_contracts.py`), an owner decision for the next turn;*
2. compile tells the author before launch: a `kind`, `placement` or capability a lane cannot
   honour is a compile issue (blocker when required, warning otherwise), using the profile body
   compile already loads;
   *Built: `application/authoring/subagent_discriminator.py`, called from
   `ManifestCompileService._resolve_mission`;*
3. lane-only knobs live under `provider_overrides.<lane>` and are **typed** per lane
   (`SUBAGENT_OVERRIDE_MODELS`, registered beside the provider options), so an author who
   needs one gets validation and a schema, and nobody else sees them; *Built: `domain/capabilities/subagent_overrides.py`;*
4. the receipt sealed into the binding is the record of what actually happened.

So Q1 is settled as: neutral core, typed per-lane overrides, matrix-driven authoring.

### 3.2 How the async child gets the profile's prompt, model and tools (Q3: D built, A next)

Facts (§2.2): the server already runs a per-run graph factory that receives the run config;
the parent already controls the run payload; the stamped served identity already gives exact
per-run verification; nothing today carries the child's configuration across.

Refined options:

| Option | Mechanism | Pros | Costs |
| --- | --- | --- | --- |
| **A. Sealed child binding by reference, assistant per binding (recommended)** | At launch the lane adapter seals a `DeepAgentExecutionBinding` for the child (prompt inline, model component, tool / MCP / Skill components, state sandbox) and stores it in Mission Control custody under its digest. The parent ensures an **assistant** on the server per child binding (`assistants.create(graph_id, assistant_id = uuid5(digest), config.configurable = {belllabs_child_binding_ref, digest}, if_exists = do_nothing)`), then `runs.create(assistant_id)`. The server factory reads the ref from `config`, fetches the binding through its own API client under the scope claim, verifies the digest, compiles with the shared materializer (provider-neutral model factory, MCP connections from the binding with server-side credentials, Skill bundles from the bundle store), caches per digest, and stamps `graph_binding_digest = child digest` | exact per-run identity with the existing verification; the served graph stays one generic `belllabs_async_child`; run payloads stay small; the same materializer path as the worker | the server needs read access to custody (an API client plus the bundle store) and the model and MCP credentials; one new assistant per child binding |
| B. Sealed child binding inline in the run config | As A but the whole binding JSON travels in `runs.create(config.configurable)` every run; no assistant, no server-side fetch | no server-to-API dependency | the binding (a few KB, prompt and components) is persisted into every checkpoint's metadata; server still needs bundle store and credentials for Skills and MCP |
| C. One served graph per profile, compiled at deploy time | The operator adds each profile's child to `langgraph.json` as its own graph | exact and simple at runtime | every new profile is a server redeploy; the coordinator cannot seed a child without the operator |
| D. Plumbing first with the fixed technical child | WP-S2 only: fix the two blockers, the policy registry and the served-graphs helper, prove a manifest-launched spawn of the existing fixed child, then do A | earliest honest end-to-end proof; de-risks auth, fencing, settlement | the child still ignores the profile until A lands |

Recommendation: **D then A**. D is small and proves the path from a manifest; A is the design
that makes a profile's prompt, model and tools reach the child without redeploys, with exact
verification already in place. B is the fallback if the server cannot be given custody access.

## 4. Owner questions and recorded answers

| ID | Question | Answer (2026-10-20) |
| --- | --- | --- |
| Q1 | Subagent contract shape | Deferred to the agent with the criterion "think about the coordinator agent and how to teach it to seed a mission across providers". Decided as §3.1: neutral core, typed per-lane overrides, support matrix and compile issues carry the complexity |
| Q2 | Child capabilities | "A child can be seeded with all capabilities per provider where possible (skills, MCP servers, plugins; plugins are an amalgamation and may also carry hooks, prompts and resources, some of that complexity deferred). Each framework usually has a general subagent that inherits from the parent; this should be explicit and handled." Recorded as the two explicit child shapes of §3.1 |
| Q3 | Async child configuration | First round: "explore more and give a more precise recommendation; doesn't the middleware need to point to the HTTP Agent Server, what is sent?" (answered in §2.2). Second round, with the refined options of §3.2: **D then A** accepted. WP-S2 (plumbing with the fixed technical child, manifest-launched) then WP-S3 (sealed child binding by reference, one assistant per binding digest, server factory fetches, verifies and compiles) |
| Q4 | Result delivery during the parent's cognition | **Answered 2026-10-20 (turn 3)**: admit at check time through the sealed policy. `check_async_task` runs the contract's admission policy when the child is `completed`, writes `child_result_index` and returns the admitted text during cognition; post-cognition completion stays the settlement path. Built in WP-S4 (not turn 3) |
| Q5 | Live tier and spend for the async proof | **Answered 2026-10-20 (turn 3)**: 5–15 USD authorized for this turn's live fixtures ("this is really important"). Models: GPT-6 Sol as the main agent, GPT-6 Luna as the subagents. Spend is recorded per run in the ledger; the agent stops at the first failure and never exceeds 15 USD. Spent in turn 3: 1,935 tokens in the recorded attempt (CHANGES.md turn 3, live drill) |
| Q6 | `record_async_child` Temporal signal | **Answered 2026-10-20 (turn 3)**: retire it unless cancellation or heartbeat fencing reads `_active_async_child_ids`; if something reads it, keep it and document why in §7 |
| Q7 | Child shape on `mc.subagent_profile.v1` (turn 3 plan question) | **Answered 2026-10-20 (turn 3)**: `capabilities: inherit | seeded`; an `inherit` profile may omit its prompt (the provider's default child prompt is used and receipted by digest) and the profile's name is the native name; `seeds: {skills, mcp_servers, plugins, tools}` holds catalog pins resolved at compile; the existing `tools`/`skills`/`mcp_servers` name fields keep narrowing from the parent. Additive and digest-stable |
| Q8 | `subagent_fields` into the persisted `mc.lane_describe.v2` | **Answered 2026-10-20 (after turn 3)**: yes, through a new lane-describe migration in the db-contract package (next session, item 3 of NEXT-SESSION.md); the HTTP sibling key is retired once the migration lands |

## 5. Work packages (WP-S2 and WP-S3 wait for Q3)

| WP | Scope | Builds | Proof | Tier |
| --- | --- | --- | --- | --- |
| **WP-S1 child shapes and capability seeding** (C10) | general + deep_agents | `SubagentProfile.capabilities: inherit \| seeded` and `plugins`; the compile-time `SubagentDiscriminator` (profile body → per-lane verdicts, `kind`/`placement`/capability admission, resolution of the child's own catalog pins); typed `provider_overrides` registry (`SUBAGENT_OVERRIDE_MODELS`) with the Deep Agents model; the `subagents.fields` support matrix on the v2 describe generated from the adapters; Deep Agents: explicit `general-purpose` child configured and receipted, seeded children with their own MCP / Skills / plugin members (members → Skills, MCP; hooks, prompts, resources deferred) and the binding compiler's subset rule replaced by the ceiling and grant checks | adapter tests extended; a compile test with an off-lane override, a refused `kind`, and a seeded child that names a Skill the parent lacks; the offline stack run with a child using its own MCP tool and a plugin Skill (the scripted model already calls `task`) | T0 |
| **WP-S2 async plumbing** (Q3-D) | deep_agents | the deployment credential joins the node's `secret_refs` when async contracts exist; dependency class alignment between graph binding and factory; the admission policy registry keyed from the launch binding (unknown ref refused at launch); a `missionctl` helper that prints the served graphs so the operator authors `deep_agents_async_graphs` without hand-copying digests; retire the dead `agent_server_endpoint` settings | the acceptance test rewritten to launch from a manifest with a `kind: async` profile (no hand-built binding, no injected token) | T0, then T2 under Q5 |
| **WP-S3 dynamic child configuration** (Q3-A) | deep_agents + Agent Server | child binding sealed at launch and stored in custody; assistant per binding; server factory that fetches, verifies, compiles and caches by digest; provider-neutral model factory on the server (D5); MCP and Skill materialization on the server; `deployment.require_assistant` widened to scope-owned assistants of the allowed graph, and the served-graphs identity reworked for per-run digests (see [ASYNC-SUBAGENTS-EXPLAINED.md](../docs/ASYNC-SUBAGENTS-EXPLAINED.md) §7) | the same acceptance test with the profile's prompt and tool observed in the child's frames | T0, T2 |
| **WP-S4 result to the parent** (Q4) | general + deep_agents | admission at check time; `child_result_index` written when admitted; `check_async_task` returns the admitted text; start/check/cancel frames with `subordinate_ref` | offline stack: parent starts, checks, reads the result, finishes; transcript shows the child frames under the parent | T0 |
| **WP-S5 other lanes' adapters (start)** | general | Claude and Codex subagent file rendering behind `application/authoring/lanes/claude_agent_sdk.py` and `codex.py` adapters consuming the discriminator output and signing receipts; no behaviour change | projection golden files unchanged | T0 |

## 6. Proof fixtures for this part

- **FX-DA-SUB1**: a Goal Directed run on the offline stack whose executor has a seeded sync
  child with one MCP tool and one plugin-provided Skill the parent does not select, plus the
  explicit inherit child; assert the child frames show the tool call and the Skill read, and
  the receipt lists both children and each capability `native`.
- **FX-DA-SUB2**: the same run with a `kind: async` child; assert the Agent Server thread id
  equals the child execution id, the child reaches `completed`, the parent reads the admitted
  result during cognition (after WP-S4), and settlement leaves no open reservation.
- **FX-DA-SUB3** (T2, Q5): FX-DA-SUB2 with the real child on OpenAI; record spend.

## 7. Collected (turn 3): identities, server state, messages, forks

Collected on 2026-10-20 while building WP-S1/S2, for the state and communication part (WP-1/WP-2,
WP-S4). Paths are relative to `src/mission_control/`.

### 7.1 Where a child's identity appears

| Identity | Formed where | Persisted where |
| --- | --- | --- |
| Sync child name | the profile name, the `SubAgent["name"]` the parent's `task` tool calls | the sealed binding (`sync_subagents[].name`), the receipt row `subagent:<name>` |
| Sync child checkpoints | LangGraph nested namespace `tools:<task tool call id>` under the parent's thread | the parent's checkpointer (`mission_control_runtime` schema); 4 nested checkpoints per `task` call in the drills |
| Sync child frames | `subordinate_ref` on frames whose namespace starts with `tools:` (`adapters/deep_agents/frames.py::_subordinate`) | `provider_frame` rows of the parent run |
| Async child execution id | `uuid5(NAMESPACE_URL, f"async-child:{parent_binding_id}:{tool_call_id}")` (`application/subordinates/service.py::spawn`) | `async_subagent_execution` (0015/0016 tables) with lifecycle, usage, result text, result manifest |
| Async link id | `uuid5(NAMESPACE_URL, f"async-link:{child_id}")` | the parent ↔ child link row: dependency class, policy ref, result decision, settled flag, usage disposition |
| Agent Server thread id | **= the child execution id** (`DeepAgentsAsyncSubagentAdapter.start`, `POST /threads {thread_id}` with `if_exists: do_nothing`) | the server's checkpointer; `langgraph dev` keeps it in memory only (gone on restart) |
| Agent Server assistant id | the graph id (`belllabs_async_technical_child`) today; WP-S3 makes it `uuid5(child binding digest)` | server side; the contract's `graph_id`, `graph_revision`, `graph_binding_digest` are the parent's record |
| Provider run id | the server's run id from `POST /threads/{id}/runs` | `provider_run_id` on the execution row; reconnect adopts it by the spawn key |
| Spawn key | `belllabs_spawn_key` in run metadata (deterministic per tool call) | server run metadata; the parent searches for it before starting (adopt one, refuse two) |
| Scope claim | `bl1.<hmac>` minted from the deployment credential for the parent's `request_scope` | never persisted; threads and runs carry `request_scope` in metadata and `deployment_auth` filters by it |

### 7.2 What a child's state looks like at the server

- Thread state is the child's graph state: `messages`, the BellLabs base channels the hosted
  binding declares, and the served identity stamped by `ServedGraphIdentityMiddleware`
  (`hosted_graph_id`, revision, binding digest), which the parent re-reads at completion.
- The parent reads it only through the Agent Protocol under its scope claim (`GET /threads/{id}`,
  `GET /threads/{id}/runs/{run_id}`); `deployment_auth` denies another scope's thread and the
  store entirely. No Mission Control code reads the server's checkpointer directly.
- `langgraph dev` persists nothing across restarts; the production topology is ADR-0017's separate
  runtime database (not composed locally). A parent that reconnects after a server restart finds
  no thread and the child classifies `in_doubt` (`provider_binding_lost`), never a second spawn.

### 7.3 Every message that crosses parent ↔ child today

| Direction | Carrier | Content |
| --- | --- | --- |
| parent → child, start | `POST /threads/{id}/runs` `input.messages[0]` | the `description` string the parent model typed into `start_async_task` (the objective); nothing else: no prompt, model, tools or Skills (WP-S3) |
| parent → child, follow-up | `update_async_task` → a new run on the same thread | one user message |
| parent → child, cancel | `cancel_async_task` → `POST .../runs/{run}/cancel` | none; the receipt is `provider_acknowledged` or `ambiguous` |
| child → parent, result | the thread's last assistant message, read by `check_async_task` and by `AsyncChildCompletion` | text, plus usage from the message's `usage_metadata` (streamed usage, `stream_usage: True`) |
| child → parent, during cognition | `check_async_task` | `pending`, `running`, `completed_pending_admission` (today), `error`, `in_doubt` with a note; the admitted text only after the policy decides (WP-S4 moves that to check time) |

The stock `update_async_task` can carry any string; it has no typed payload and no file
transfer. Shared files between parent and child do not exist on this lane (the hosted child's
sandbox is the graph's own `StateBackend`).

### 7.4 Where a fork of the parent would have to re-link or re-spawn children

- `application/recovery/run_forks.py`: `AsyncChildForkClassifier` classifies the parent's
  children at the fork boundary over the authority lineage
  (`LineageAsyncChildForkClassifier`); an **active** child makes the snapshot unsafe
  (`snapshot_not_quiescent`, EXEC-016). A child the inspection lists but the lineage does not is
  classified active (fail closed). Children stay parent-owned and are never copied into the
  derived run.
- Sync children need nothing: their checkpoints live in the parent's thread under `tools:*`
  namespaces, and a cognitive-seed fork (P1-S6, copy-and-restamp) copies the root lineage only;
  a fork resumed mid-`task` would re-run the child from the parent's pending tool call.
- The parent's `async_tasks` state (the stock task table) travels with the parent's checkpoint,
  so a forked parent would hold task ids of children that belong to the source run; WP-2 must
  clear or re-link that table when it seeds the derived unit.

## 8. What the owner will see when this part is done

```yaml
# manifest fragment (Deep Agents node)
agents:
  - pin: subagent.general@1#sha256:…         # capabilities: inherit (the provider's general child)
  - pin: subagent.reviewer@1#sha256:…        # kind: sync, seeded: its own skills/mcp/plugins
  - pin: subagent.researcher@1#sha256:…      # kind: async; served graph bound in launch bindings
provider_options:
  deep_agents:
    summarization: {trigger_messages: 40}
```

`missionctl lane describe deep_agents` shows the subagent field matrix; compile warns or blocks
on anything the lane cannot honour; `missionctl run transcript RUN` shows the children's
frames under the parent with `subordinate_ref`; `missionctl run inspect RUN` lists the async
child, its provider run and its result decision; the sealed binding's
`materialization_receipt` names each child and each child field as native or degraded.

**Q8, built 2026-10-21 (turn 4):** `subagents.fields` is on the persisted `mc.lane_describe.v2` of every lane (release 1.4.3, migration `0046_lane_describe_subagent_fields`); the HTTP sibling key is retired and `application/authoring/lanes/support.py` reads the describe. See the turn 4 ledger entry.
