---
type: Research
title: "How a Deep Agents async subagent works, from configuration to the Agent Server and back: the three layers, what the parent sends, how it hears back, and what the server actually serves"
description: "A walk-through for the owner of the async subagent path as built on 2026-10-20: the deepagents framework layer (the stock async tools and their default parent-child communication by polling), the LangGraph Agent Server layer (langgraph.json graphs served by LangGraph's own Agent Protocol routes, with our custom app and auth beside them, not in front of them), and the Mission Control governance layer (contracts, reservation and fencing, admission). Ends with what the accepted 'D then A' decision changes."
tags: [mission-control, providers, consolidation, deep-agents, subagents, agent-server, explainer]
status: archived
archived: 2026-11-02
archived_from: providers/deep_agents/ASYNC-SUBAGENTS-EXPLAINED.md
archived_reason: "built; design history cited by deep-agents-children"
---

> **Archived 2026-11-02** (built; design history cited by deep-agents-children). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# How the Deep Agents async subagent works

Three layers stack on each other. Keep them apart and the whole thing is simple.

| Layer | Who owns it | What it does |
| --- | --- | --- |
| **deepagents** (framework, 0.7.5) | LangChain | Gives the parent agent five tools (`start_async_task`, `check_async_task`, `update_async_task`, `cancel_async_task`, `list_async_tasks`) that talk Agent Protocol over HTTP to any LangGraph server, and keeps the task ids in the parent's state under `async_tasks` |
| **Agent Server** (LangGraph API server) | LangChain's server, configured by our `agent_server/langgraph.json` | Serves the Agent Protocol routes (`/threads`, `/threads/{id}/runs`, `/assistants`, …), schedules and runs graphs, holds the child's thread state and checkpoints, streams and cancels runs. Our code contributes the **graph**, an **auth module** and a **small custom app** beside the native routes |
| **Mission Control governance** | us | Turns a manifest `agents:` entry into an `AsyncSubagentContract` sealed in the parent's binding; wraps the five stock tools so every spawn is reserved, claimed and registered in Postgres before the server is called; verifies the served graph identity; admits the child's result and settles it |

Paths below are relative to `src/mission_control/`.

## 1. From configuration to a sealed contract (before anything runs)

1. The catalog holds a `mc.subagent_profile.v1` with `kind: async` (name, description,
   prompt, model, tools, budget…). A Deep Agents node selects it in its manifest `agents:`.
2. The operator's launch bindings file names, per profile name, the graph the deployment
   serves for it: `deep_agents_async_graphs.<name>` = `{graph_id, graph_revision,
   graph_binding_digest, agent_protocol_url, deployment_credential_ref, result/objective
   schema refs, result_admission_policy_ref, default budget, dependency classes, timeout,
   cancellation/late-result/fallback policies}` (`application/authoring/lanes/deep_agents.py::AsyncSubagentGraphBinding`).
3. At `missions:start` the lane adapter seals an `AsyncSubagentContract` from the profile and
   that binding (`lanes/deep_agents.py::_async_child`) into the parent's
   `DeepAgentExecutionBinding.async_subagents`. The contract is content-addressed; the parent
   will verify the server against it.

What the contract says about *where* the child runs is exactly two fields: `agent_protocol_url`
(for example `http://127.0.0.1:2024`) and `deployment_credential_ref`
(`environment:BELLABS_ASYNC_SUBAGENT_SERVER_TOKEN`, the shared secret the parent uses to mint a
scope claim). Nothing in worker settings points at the server; `settings.agent_server_endpoint`
is dead code.

## 2. The run: what the parent agent sees

When the operation activity materializes the parent (`adapters/deep_agents/adapter.py:213-223`),
it attaches `BellLabsAsyncSubagentMiddleware` **only if the binding has async contracts**. That
middleware is built from the stock deepagents `AsyncSubAgentMiddleware` so the model sees the
exact stock tool names, schemas and descriptions, plus a system-prompt addition listing the
available async subagent types by name and description (`adapters/deep_agents/async_subagents.py:687-724`).
The model does not know Mission Control is in the loop.

## 3. When the parent decides to call its async subagent

The model emits `start_async_task(description="…", subagent_type="researcher")`. What happens,
in order:

1. **Governance first** (`application/subordinates/service.py::spawn`): the service checks the
   dependency class against the contract, derives a deterministic child execution id from the
   parent binding id and the tool call id, reserves a slice of the parent's budget, claims an
   effect, registers the child on the run, and moves the child to `ADMITTED`, all in Postgres,
   **before any HTTP call**. If the worker's `ASYNC_SUBAGENT_SPAWNING_ENABLED` is off, this is
   where the spawn is refused.
2. **Fence** (`service.py::_submit_fenced`): one submission fence per child, bounded by the
   lease, so a crashed or retried activity cannot submit twice.
3. **Verify the server** (`async_subagents.py:194-210`): `GET {url}/belllabs/async-subagents/served-graphs`
   with the scope-claim bearer. The server lists the graph it hosts with its revision and
   binding digest; the contract must match exactly or the spawn fails closed.
4. **Create the thread** (`:214-249`): `POST {url}/threads` with `thread_id` = the Mission
   Control child execution id (so a retry finds the same thread), `if_exists: do_nothing`,
   and metadata `belllabs_child_execution_id`, `belllabs_parent_run_id`,
   `belllabs_parent_binding_id`, `belllabs_contract_digest`, `request_scope`.
5. **Look before starting** (`:271-299`): `GET {url}/threads/{id}/runs`; a run already carrying
   this child's spawn key is adopted, two are an ambiguity (`in_doubt`), none means start.
6. **Start the run** (`:250-269`): `POST {url}/threads/{id}/runs` with
   `assistant_id = contract.graph_id`, `input = {"messages": [{"role": "user", "content":
   description}]}`, the same metadata plus `belllabs_spawn_key`, and
   `multitask_strategy: reject`. **That is everything that travels.** The child's prompt,
   model and tools are not sent; the objective is the sentence the parent model typed.
7. **Record and return**: the child moves to `SUBMITTED` with its provider run id, and the
   tool returns `Launched async subagent. task_id: <child execution id>` to the model.

The bearer on every call is `bl1.<claim>`: an HMAC claim over the parent's `request_scope`,
minted from the shared secret, refreshed when it lapses (`async_subagents.py:126-146`,
`adapters/agent_server/async_subagents/auth.py`).

## 4. How the child and the parent communicate, by default

deepagents has **no push from child to parent**. The parent polls. The default mechanics, from
the stock tools (installed package, `deepagents.middleware.async_subagents`):

| Tool | What it does on the wire | What the parent gets back |
| --- | --- | --- |
| `check_async_task(task_id)` | `GET /threads/{id}/runs/{run_id}`; when the run status is `success`, `GET /threads/{id}` and read the thread's final messages | status (`pending`, `running`, `success`, `error`, `cancelled`) and, on success, the child's last message text |
| `update_async_task(task_id, message)` | `POST /threads/{id}/runs` on the **same thread** with a new user message | a new run continues the child's conversation; the task is marked `running` again |
| `cancel_async_task(task_id)` | `POST /threads/{id}/runs/{run_id}/cancel` | the task is marked `cancelled` |
| `list_async_tasks(status_filter)` | reads the parent's own state | the tracked tasks |

The task table lives in the parent's LangGraph state under `async_tasks`, so it survives
compaction and is visible in the parent's checkpoints. "Communication" therefore means: the
objective goes down as the first user message; later messages go down through `update`; the
result comes up as the child's final assistant message when the parent polls. There is no
shared memory, no event stream and no callback.

Mission Control keeps those semantics and adds a gate: the governed `check_async_task` reads
the real run and thread state, re-verifies the stamped served identity, attributes usage, and
**reveals the child's text only after the result is admitted** by the sealed admission policy
(`async_subagents.py:797-807`). Today that admission runs after the parent's cognition ends
(`application/subordinates/parent_completion.py`), so during cognition the parent only ever sees
`completed_pending_admission`. Changing that (admit at check time) is open question Q4 in
[SUBAGENTS.md](../specs/SUBAGENTS.md).

## 5. What the Agent Server route actually is

**We do not write FastAPI routes for threads or runs, and we do not capture the thread create.**
The LangGraph API server serves the Agent Protocol itself. Our `agent_server/langgraph.json`
tells it what to serve and where to plug in:

```json
{
  "graphs": {
    "belllabs_async_technical_child": "mission_control.adapters.agent_server.entrypoints:child",
    "block_c_qualification": "…", "block_c_qualification_n1": "…", "block_c_wait": "…"
  },
  "env": "runtime.env",
  "auth": {"path": "mission_control.adapters.agent_server.deployment_auth:auth", "disable_studio_auth": true},
  "http": {"app": "mission_control.adapters.agent_server.http_app:app", "middleware_order": "auth_first"}
}
```

Three plug-ins, three jobs:

1. **`graphs`**: `belllabs_async_technical_child` points at `entrypoints.child`, an **async
   graph factory**: the server calls it **per run with the run's config**
   (`adapters/agent_server/entrypoints.py:11-13`) and gets back a compiled LangGraph graph.
   Today the factory ignores the config and returns one process-wide compiled Deep Agent built
   from the fixed technical child binding (`async_subagents/graph.py::graph`), stamping the
   served identity into thread state through `ServedGraphIdentityMiddleware`. When the parent
   posts a run with `assistant_id = belllabs_async_technical_child`, the server resolves that
   id to this graph, creates the run, and executes it with its own scheduler and checkpointer.
2. **`auth`**: `deployment_auth.authenticate` runs on every request. A `bearer bl1.` header is
   verified as a subordinate scope claim and the principal gets `request_scope:<scope>`; the
   handlers on `threads`, `runs`, `assistants`, `store` and `crons` then **filter and enrich by
   metadata**: every thread and run must carry the caller's `request_scope`, so one tenant
   cannot read another's children; creating a run requires an allowed assistant
   (`deployment.require_assistant`: the graph id or its default assistant uuid, nothing else);
   the store is denied to subordinates; crons are denied. This is the only place our code
   touches the native thread and run requests, and it does so by authorization, not by
   routing.
3. **`http.app`**: `http_app.py` is a small FastAPI app **merged beside** the native routes
   (`middleware_order: auth_first`). It adds `GET /belllabs/async-subagents/served-graphs`
   (the identity the parent verifies), readiness, the graph-runtime contract schemas and docs.
   It does not handle `/threads` or `/runs`.

Why this shape rather than our own route in front: the server owns run scheduling, streaming,
cancellation, `multitask_strategy`, thread state and checkpoints. Keeping the stock Agent
Protocol means the stock deepagents client and tools work unchanged, LangGraph Platform or a
self-hosted server are interchangeable, and our additions stay at the edges (identity, auth,
governance).

Where the child's state lives: in the server's checkpointer, keyed by the thread id. With
`langgraph dev` that is in memory (gone on restart); production is ADR 0017's separate runtime
database, not yet composed. The parent never reads the child's checkpoints directly; it reads
thread state through the API under its scope claim.

## 6. The whole sequence in one picture

```text
manifest agents: [subagent.researcher kind: async]
   │  missions:start → lane adapter + deep_agents_async_graphs[researcher]
   ▼
AsyncSubagentContract  (graph_id, revision, binding digest, url, credential ref, policies)  ──sealed into──▶ parent DeepAgentExecutionBinding
   │
   │  operation.execute activity → materializer attaches BellLabsAsyncSubagentMiddleware (stock tool surface)
   ▼
parent model: start_async_task(description, "researcher")
   │
   ├─ Postgres: reserve budget · claim effect · register child · ADMITTED            (governance, before HTTP)
   ├─ fence
   ├─ GET  /belllabs/async-subagents/served-graphs       (identity must match the contract)
   ├─ POST /threads {thread_id = child id, metadata: belllabs ids + request_scope}
   ├─ GET  /threads/{id}/runs                            (adopt an existing run, refuse two)
   └─ POST /threads/{id}/runs {assistant_id = graph_id, input: objective message}
                 │
                 ▼   LangGraph API server (langgraph.json)
          auth: bl1 claim → request_scope; metadata filter; allowed assistant only
          graphs: entrypoints.child(config) → compiled Deep Agent (fixed technical child today)
          run executes on the server's scheduler and checkpointer; identity stamped in thread state
   │
parent model: check_async_task(task_id)  →  GET run, GET thread  →  Mission Control: verify stamp, attribute usage,
                                                                      reveal text only when admitted (today: after cognition)
parent model: update_async_task(task_id, msg) → POST /threads/{id}/runs (follow-up turn on the same thread)
parent model: cancel_async_task(task_id)      → POST /threads/{id}/runs/{run}/cancel
   │
after the parent's cognition: AsyncChildCompletion polls, decides through the registered admission policy, settles the reservation
```

## 7. What "D then A" changes

**D (plumbing, WP-S2; built 2026-10-20, see CHANGES.md turn 3)** does not change the shape above. It makes the shape reachable from a
manifest: the deployment credential joins the operation's `secret_refs` (today it is never
added, so the bearer cannot be minted), the dependency classes of the graph binding and the
worker factory agree (today they reject each other), the admission policy named by the
contract is registered from the launch binding, and a helper prints the served graphs so the
operator does not hand-copy digests.

**A (sealed child binding by reference, WP-S3)** changes what the factory builds:

- at launch, the lane adapter also seals a `DeepAgentExecutionBinding` **for the child** (the
  profile's prompt inline, its model component, its tools, MCP servers and Skills, a state
  sandbox) and stores it in custody under its digest;
- before the first spawn, the parent ensures a server **assistant** for that binding:
  `POST /assistants {graph_id: belllabs_async_child, assistant_id: uuid5(digest), config:
  {configurable: {belllabs_child_binding_ref, digest}}, if_exists: do_nothing}`, then posts
  runs with that `assistant_id`;
- the factory `entrypoints.child(config)` reads the reference from `config.configurable`,
  fetches the binding from custody through the server's own API client under the scope claim,
  verifies the digest, compiles it with the same materializer the worker uses (provider-neutral
  model factory, MCP connections with server-side credentials, Skill bundles from the bundle
  store), caches the compiled graph per digest, and stamps `graph_binding_digest` = the child
  digest, so the existing verification stays exact per run;
- two things must change for that to be allowed: `deployment.require_assistant` currently
  admits only the graph's default assistant, so it must accept assistants created under the
  caller's scope for the allowed graph; and the served-graphs identity becomes "graph
  `belllabs_async_child` accepts sealed child bindings" with the per-run digest verified from
  the thread stamp rather than from a single static digest.

Nothing in the communication model (§4) changes with A; the child simply runs the profile's
agent instead of the fixed technical one.

## 8. Short answers to the two questions

- **How does the async subagent communicate with the parent by default?** It does not initiate
  anything. The parent sends the objective as the thread's first user message, polls with
  `check_async_task` (run status, then the child's final message), can send follow-up messages
  with `update_async_task` (a new run on the same thread), and can cancel. Task ids live in the
  parent's state. Mission Control gates what the parent may read behind result admission.
- **Are we creating a FastAPI route that captures the thread create?** No. LangGraph's server
  serves `/threads` and `/runs` from `langgraph.json`; our `graphs` entry points at a per-run
  factory, our `auth` module authenticates the scope claim and filters every thread and run by
  `request_scope`, and our custom app adds only the served-graphs identity endpoint and
  readiness beside the native routes.
