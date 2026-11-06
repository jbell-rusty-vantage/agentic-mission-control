---
type: Research Note
title: "Cursor lanes full-maturity gap analysis (2026-10-12)"
description: "Capability-by-capability lifecycle and control audit of cursor_local and cursor_cloud against current Cursor SDK and API, with defects, CM work items and CD qualification drills."
tags: [mission-control, research, materialization-observation]
---

# Cursor lanes: full-maturity gap analysis (lifecycle and control)

Date: 2026-10-12. Scope: `cursor_local` and `cursor_cloud` in
`platform/mission-control`. This is a read-only audit. No repo file was edited.

**Complements, does not repeat.** The materialization-observation packet
(`docs/specs/archive/materialization-observation-2026-10/`, SPEC-01..05, PLAN MO-xx) already covers:
environments and secrets (MO-10..16), cognition and inline MCP (MO-30..35), signal ingress,
hooks, remote stop fence and webhooks (MO-40..47), knowledge workspaces, placement and
cross-lane forks (MO-50..53). Rows below that those items close are marked **[packet MO-xx]**.
Everything else is lifecycle or control work the packet does not name.

## Evidence base

- **Code read:** `adapters/cursor/{local,cloud,cloud_api,bridge,controls,frames,sse,snapshot,scm,workspace,projection,qualification}.py`,
  `adapters/temporal/deployment_composition.py`, `application/execution/harness/{describe,lane_turns}.py`,
  `application/frames/kinds.py`, `application/workspaces/{service,policy}.py`,
  `application/execution/operations/lane_outputs.py`, `domain/execution/lanes.py`.
- **Docs read:** AGENTS.md (root and adapters), knowledge `cursor-lane`, `lanes-and-harness`,
  `interventions`, HANDOFF-2026-10-10, both qualification READMEs, packet PLAN, GAP-REPORT,
  SPEC-03, and the fact sheet `research/cursor.md`.
- **Pinned SDK inspected in place:** `.venv/Lib/site-packages/cursor_sdk` 1.0.37
  (`_async_agent.py`, `_async_client.py`, `_bridge.py`, `_async_bridge.py`, `_store_callback.py`,
  `types.py`, vendored `proto/sdk/v1`).
- **Primary sources fetched 2026-10-12:**
  - S1 https://cursor.com/docs/cloud-agent/api/endpoints.md
  - S2 https://cursor.com/docs/sdk/python.md
  - S3 https://cursor.com/docs/sdk/typescript.md
  - S4 https://cursor.com/docs/sdk/bridge.md
  - S5 https://cursor.com/docs/cloud-agent/api/v0.md
  - S6 https://cursor.com/docs-static/cloud-agents-openapi.yaml
  - Plus the fact sheet's citations (S7 = `research/cursor.md`).
- **Tests:** `uv run pytest tests/unit -k cursor -q` gave **262 passed**, 2748 deselected
  (Windows, fakes). No integration, real-service or live run was made.

### Primary-source facts that matter here and are not in the fact sheet

1. **Follow-up runs (S1).**
   - `POST /v1/agents/{id}/runs` takes `prompt{text, images≤5}`, `mcpServers` (replaces the
     create-time set for that run) and `mode` (`agent|plan`).
   - It takes **no `model`** field. Only the SDK `SendOptions.model` overrides the model per
     send (S2).
   - `GET /runs` lists runs newest first.
2. **Cancel (S1).** Cancel is terminal: the run becomes `CANCELLED` and cannot be resumed.
   Continue by creating a new run on the same agent. A run that is already terminal or was
   never active returns `409 run_not_cancellable`.
3. **Usage (S1, S2).**
   - REST `/usage` returns `totalUsage` and `runs[]{id, usageUuid, usage{inputTokens,
     outputTokens, cacheWriteTokens, cacheReadTokens, totalTokens}}`. It carries **no cost**.
   - The SDK `get_usage(run_id=)` returns `cost{raw_cost_cents, charged_cents}`, which is
     "eventually consistent after a run ends".
   - Local agents return a **per-turn** breakdown keyed by usage UUID.
   - Local usage is gated per account (`403 feature_unavailable`). The interim source is
     `run.usage` / `result.usage`.
4. **Agent lifecycle (S1, S2).**
   - Agent status is `ACTIVE | IDLE | ARCHIVED`, where ARCHIVED means "archived or expired".
   - `archive` is reversible: an archived agent accepts no runs until `unarchive`.
   - `DELETE` is permanent.
5. **Artifacts (S1).** Artifacts are agent-scoped, with paths under `artifacts/`. Download
   returns `{url, expiresAt}` and the URL lasts 15 minutes. **Local SDK agents return an
   empty list and cannot download artifacts** (S2).
6. **SSE (S1).** The docs say to handle **either** the simplified events **or**
   `interaction_update`, not both. The terminal `result` payload has no usage.
7. **No-repo cloud agents (S1, S2).** Omitting both `repos` and `env` starts an agent with
   an empty workspace. SPEC-03 §3 says "All three cloud products launch against a GitHub
   repository", which is not true for Cursor.
8. **Local busy (S2).**
   - Local agents **do not raise `AgentBusyError`**.
   - `SendOptions.local.force=True` "expire[s] a stuck active run before starting this
     message".
   - Cloud returns `409 agent_busy`. That error is not retryable: wait, cancel, or poll
     `list_runs`.
9. **Errors (S2).**
   - Every error carries `is_retryable`, `retry_after` and `request_id`.
   - Types: `RateLimitError`, `AuthenticationError`, `PermissionDeniedError`,
     `IntegrationNotConnectedError(help_url)`, `NetworkError`, `APITimeoutError`,
     `ConfigurationError` (also raised for `409 agent_archived`), `AgentNotFoundError`,
     `UnsupportedRunOperationError`.
10. **Local store and resume (S2, S3, SDK source).**
    - Local agents persist agents, runs, run events and checkpoints. The default store is
      SQLite under the bridge state root. `jsonl` and `custom` stores are also available.
    - A `custom` store is delegated to the host through `StoreCallbackServer`
      (`_store_callback.py:279-380`).
    - `Agent.resume` "survive[s] a process restart".
    - `tools`, `disallowed_tools`, inline MCP and `system_prompt` (TypeScript) are **not
      persisted** and must be passed again on every resume.
11. **Bridge (S4, SDK source).**
    - The bridge is a loopback Connect server and ships for `win32 x64`.
    - Clients may **attach to an existing endpoint**: `AsyncClient.connect(base_url,
      auth_token)` at `_async_client.py:135`.
    - The sync `Bridge.launch` uses `subprocess.Popen` (`_bridge.py:177`). Only the async
      launcher uses `asyncio.create_subprocess_exec` (`_async_bridge.py:120`), which is what
      the Windows SelectorEventLoop cannot do.
    - `GetVersion` reports capabilities such as `agent.usage`.
    - The `sdk.v1` protos have **no Steer RPC**: Python 1.0.37 cannot steer.
12. **Steer (S3).** TypeScript `run.steer()` works on **local runs only**. Cloud runs always
    resolve `revert_to_followup`.
13. **Conversation export (S2, S3, S5).**
    - SDK `run.conversation()` returns `ConversationTurn[]` on local and cloud runs.
    - The bridge RPC is `GetRunConversation`.
    - v0 `GET /v0/agents/{id}/conversation` remains.
14. **Models (S1, S2).**
    - `GET /v1/models` and `Cursor.models.list()` give ids, parameter definitions and
      variants.
    - Create takes `model{id, params[{id,value}]}`. Omitting it resolves the user default,
      then the team default, then the system default.
15. **Local-only levers (S2).**
    - `tools` allowlist.
    - `custom_tools`: Python callables served over a loopback tool callback. These are a
      host-side tool channel that hooks are not.
    - `auto_review`.
    - `dirs` (multi-root).
16. **Cloud MCP transport conflict.** S1 lists `http|sse|stdio` for inline `mcpServers`. The
    fact sheet (from capabilities.md) says HTTP and stdio only. Treat SSE as UNVERIFIED until
    a drill settles it.

## Capability table

Status vocabulary: WIRED+TESTED / WIRED-UNTESTED / PARTIAL / DESIGNED-ONLY / ABSENT.
"Tested" means offline (fixtures or fakes). Nothing is live-qualified.

Paths are relative to `src/mission_control/` unless they start with `tests/` or `docs/`.

### 1. Launch (prepare and start)

- **Local: WIRED+TESTED.**
  - Code: `adapters/cursor/local.py:350-476`.
  - The live `cursor-sdk` launch is unexercised.
- **Cloud: WIRED+TESTED (fakes).**
  - Code: `adapters/cursor/cloud.py:370-527`.
  - Production composition passes no `workspaces`, `env_resolver` or `cost_reader`
    (`adapters/temporal/deployment_composition.py:606-639`).
- **Cursor native:**
  - Local: SDK `AsyncAgent.create`.
  - Cloud: `POST /v1/agents` with `agentId` or `Idempotency-Key`, `customSubagents`,
    `mcpServers`, `model.params`, `env{type,name}`, `envVars` (S1).
- **Needed:**
  - Compose the lease and env resolver [packet MO-06].
  - Named environment [packet MO-13].
  - Model params (CM-11).
  - Allow no-repo cloud agents (CM-22).

### 2. Observe: live stream

- **Local: WIRED+TESTED.** `adapters/cursor/local.py:671-701`, `adapters/cursor/frames.py:102-185`.
- **Cloud: WIRED+TESTED.** `adapters/cursor/cloud.py:791-894`.
- **Cursor native:** local `observe_run(after_offset)`; cloud SSE (S1).
- **Needed:** cloud persists **both** the simplified events and `interaction_update`
  (`application/frames/kinds.py:139-154`), which S1 says not to do. See CM-13.

### 3. Observe: replay and resume from a cursor

- **Local: WIRED+TESTED.** `adapters/cursor/local.py:226-238`, `local.py:725-730`.
- **Cloud: WIRED+TESTED.**
  - Per-run SSE keys and `Last-Event-ID`: `adapters/cursor/cloud.py:182-202`.
  - `400 invalid_last_event_id` reopens once: `cloud.py:811-820`.
- **Cursor native:** bridge offsets; `Last-Event-ID` (S1).
- **Needed:** nothing beyond CM-13.

### 4. Reattach after a worker crash

- **Local: PARTIAL.**
  - The bridge is a child of the worker (`adapters/cursor/bridge.py:413-430`), so an
    in-flight run dies with it.
  - `reattach` relaunches the bridge and resumes an idle agent
    (`adapters/cursor/local.py:551-602`).
  - The in-flight unit parks `in_doubt` (`local.py:606-629`).
- **Cloud: WIRED+TESTED (fakes).**
  - Rehydrates branch, projection and lease: `adapters/cursor/cloud.py:540-596`.
- **Cursor native:**
  - `AsyncClient.connect` attaches to a live bridge.
  - The local store survives restarts.
  - `list_runs`.
  - `local.force` expires a stuck run (S2).
- **Needed:**
  - **CM-05:** a detached bridge with a persisted endpoint and connect-on-reattach, so a live
    local run survives a worker crash.
  - Reconcile through `list_runs`.

### 5. `send_turn`, follow-ups and queueing (`wait_then_send`)

- **Local: WIRED+TESTED.**
  - Code: `adapters/cursor/local.py:633-650`.
  - The `AgentBusy` branch is dead code: local agents never raise it (S2).
- **Cloud: WIRED+TESTED.**
  - `409 agent_busy` returns `busy`: `adapters/cursor/cloud.py:627-637`.
  - The follow-up body sends the prompt only (`cloud.py:628`).
- **Cursor native:**
  - One active run per agent.
  - Follow-up runs take `mode` and `mcpServers`.
  - Local `force` (S1, S2).
- **Needed:**
  - Per-run `mcpServers` [packet MO-30].
  - Per-run `mode` and images (CM-15, CM-20).
  - Refuse an unknown `instruction_ref` instead of silently resending the original prompt
    (`local.py:639`, `cloud.py:624-626`). See CM-18.

### 6. `cancel_turn` and immediate cancel

- **Local: WIRED+TESTED.** `adapters/cursor/local.py:818-841`. The Stop Fence reaches it
  through the fail-closed Kernel Hooks.
- **Cloud: WIRED+TESTED.**
  - Code: `adapters/cursor/cloud.py:1109-1125`.
  - The fence reaches the run through the API cancel only (`fail_closed=False`).
  - `get_run` after a cancel is not guarded against `AgentNotFound` (`cloud.py:1122`).
- **Cursor native:** cancel is terminal; `run_not_cancellable` (S1).
- **Needed:**
  - Gate hooks plus the remote fence [packet MO-42].
  - Small robustness fix (CM-19).

### 7. `interrupt_and_inject`

- **Local: WIRED+TESTED.** `cancel_and_replace`; `application/execution/harness/lane_turns.py:1295-1330`.
- **Cloud: WIRED+TESTED.** Same mechanism.
- **Steer:** absent on both profiles, correctly.
- **Cursor native:**
  - Python 1.0.37 has no steer and the bridge `sdk.v1` has no Steer RPC.
  - TypeScript steer is local-only (S3).
- **Needed:** keep `cancel_and_replace`. Re-check steer on each SDK bump (watch item; not a
  work item).

### 8. Pause and resume (emulated)

- **Local: WIRED+TESTED.** Refused mid-run; applied at the run boundary
  (`application/execution/harness/controls.py:100-115`).
- **Cloud: WIRED+TESTED.** Same.
- **Cursor native:** no pause on either profile.
- **Needed:** nothing. This is honest as declared.

### 9. Fork: workspace

- **Local: WIRED+TESTED.** `mc.cursor_snapshot.v1`; `adapters/cursor/local.py:894-934`,
  `adapters/cursor/snapshot.py`.
- **Cloud: WIRED+TESTED.** `branch:<b>@<sha>`; `adapters/cursor/cloud.py:1180-1204`,
  `cloud.py:381-390`.
- **Cursor native:** none (no fork API).
- **Needed:** cross-lane forks [packet MO-53].

### 10. Fork: conversation

- **Local: ABSENT.** Hydration is packet-only (`adapters/cursor/controls.py:228-286`).
- **Cloud: ABSENT.** Packet-only (`adapters/cursor/controls.py:181-226`).
- **Cursor native:**
  - `run.conversation()` on both profiles.
  - v0 `/conversation`.
  - The local checkpoint store is a file under the state root (S2, S3, S5).
- **Needed:** **CM-07:** export the conversation into the fork packet. Also run a
  local-store-copy drill (CM-06).

### 11. Continuation and compaction (ADR-0039, ADR-0041)

- **Local: PARTIAL.**
  - Hydrators are composed: `adapters/temporal/deployment_composition.py:535-550`.
  - `summary-*` updates map to compaction frames: `application/frames/kinds.py:111-112`.
  - No `context_occupancy`, so pressure is always `unknown`
    (`application/execution/harness/lane_turns.py:1750-1760`).
- **Cloud: PARTIAL.**
  - Same as local.
  - `hydrate_agent` drops `customSubagents`, `env`, `envVars`, `metadata` and MCP
    (`adapters/cursor/cloud.py:1039-1048`).
  - The source agent is never archived.
- **Cursor native:** automatic summarization, observe-only; no compaction API.
- **Needed:**
  - CM-08: continuation agent parity and archiving the source agent.
  - CM-14: occupancy.

### 12. Approvals and Human Gates (ADR-0038)

- **Local: PARTIAL.**
  - `workflow_gate` is admitted.
  - `governed_effect` through Kernel Hooks is implemented but refused at admission.
  - `provider_permission` is unsupported (`adapters/cursor/qualification.py:125-290`).
- **Cloud: PARTIAL.** `workflow_gate` only.
- **Cursor native:**
  - Headless runs auto-approve.
  - Local `custom_tools` run in the host process.
  - `mode: plan` per run on both profiles (S1, S2).
- **Needed:**
  - **CM-15:** plan, then a gate, then agent mode.
  - **CM-16:** a local custom-tool approval and question channel.

### 13. Interventions: mailbox and `add_context` (ADR-0032)

- **Local: WIRED+TESTED.** Provider-neutral, at the boundary.
- **Cloud: WIRED+TESTED.** Same.
- **Cursor native:** n/a.
- **Needed:** nothing on the lane side.

### 14. Usage: tokens

- **Local: PARTIAL.**
  - `agent.get_usage()` is called with no `run_id`, so it is the agent total but recorded as
    "settled" turn usage (`adapters/cursor/bridge.py:359-374`, `adapters/cursor/local.py:867-886`).
  - Cache tokens are dropped.
- **Cloud: PARTIAL.**
  - `/usage?runId=` is read for the final run only, at settle
    (`application/execution/harness/lane_turns.py:2286-2307`).
  - Replaced and continuation runs are uncounted (handoff C3).
  - Cache tokens are dropped.
- **Cursor native:** per-run and per-turn breakdowns; four token kinds (S1, S2).
- **Needed:** **CM-02.**

### 15. Cost settlement and budget

- **Local: PARTIAL.** Agent-cumulative `charged_cents`, read once at settle. It is eventually
  consistent, so it may be early.
- **Cloud: DESIGNED-ONLY.** A `cost_reader` port exists (`adapters/cursor/cloud.py:169`,
  `cloud.py:1145-1149`) but is never composed.
- **Cursor native:** SDK `UsageCost` (cloud is not gated); REST carries no cost.
- **Needed:** **CM-01**, a deferred cost settlement.

### 16. Artifacts and declared outputs

- **Local: WIRED+TESTED.** `outputs/` registered; missing-output `stop` follow-up
  (`adapters/cursor/local.py:703-749`, `local.py:951-967`).
- **Cloud: PARTIAL.**
  - `artifacts/*` is staged.
  - Branch `outputs/` files are **never** registered, because `declared_output_path` needs
    `outputs/` (`application/execution/operations/lane_outputs.py:58-80`).
  - Cloud has no missing-output check (`adapters/cursor/cloud.py:952-956`).
- **Cursor native:** the artifacts API (cloud only).
- **Needed:** **CM-09**; [packet MO-51] for the knowledge channel.

### 17. PR and git collection

- **Local: ABSENT.** The patch artifact only.
- **Cloud: PARTIAL.**
  - `autoCreatePR` comes from the binding.
  - The `prUrl` is kept only when `latestRunId` equals the run (`adapters/cursor/cloud.py:780-789`).
- **Cursor native:** `autoCreatePR`, `skipReviewerRequest`, `open_as_cursor_github_app`,
  `prUrl` attach (S1).
- **Needed:**
  - The `repo_pr` Governed Effect [packet MO-14].
  - Record the PR in closing facts even after archiving (part of CM-09).

### 18. Model selection

- **Local: PARTIAL.** `ModelSelection(id)` only (`adapters/cursor/bridge.py:284-286`).
- **Cloud: PARTIAL.** `{"id"}` only (`adapters/cursor/cloud.py:483`).
- **Both:** no params, no validation, no per-turn override.
- **Cursor native:** `/v1/models` and `models.list()`; `params`; SDK `SendOptions.model`.
- **Needed:** **CM-11.**

### 19. Subagents

- **Local: WIRED-UNTESTED.**
  - Inline: `AgentOptions.agents` (`adapters/cursor/bridge.py:294-298`). File subagents come
    through `setting_sources=project`.
  - Lineage comes from the `subagentStart` hook.
- **Cloud: PARTIAL.**
  - `customSubagents` is **silently truncated to 20** (`adapters/cursor/cloud.py:474`).
  - Not re-sent on continuation.
  - No lineage.
- **Cursor native:** inline subagents (≤20 on cloud; `model`; `mcp_servers` names).
- **Needed:** **CM-12.**

### 20. Stage Graph, Goal Loop (GoalDirected) and Mission Chains

- **Local: WIRED+TESTED.** MP-20 parity rows with FIXTURE bridges.
- **Cloud: WIRED+TESTED.** Same, including `tests/integration/cursor/test_mp09_cloud_segment_loop_real_services.py`.
- **Cursor native:** n/a.
- **Needed:** live drills only.

### 21. Parallel Swarm and parallel units in one run

- **Local: DESIGNED-ONLY** (the swarm itself is spec-only), plus a probable defect.
  - The lease path is `root/<hash(run)>/a{attempt}-g{gen}` (`adapters/cursor/workspace.py:144-146`),
    and `attempt` here is the generation.
  - Two parallel cursor_local units of one run therefore get the **same path**, even though
    `CURSOR_LOCAL_POLICY` is `reuse="none"`.
- **Cloud: DESIGNED-ONLY**, plus a probable defect.
  - Every unit of a run shares branch `mc/<run>` (`adapters/cursor/cloud.py:178-179`,
    `cloud.py:161-166`).
  - With the allocator composed, the second unit is fenced out. Without it (production
    today), the units race on one branch.
- **Cursor native:** one VM and one branch per agent.
- **Needed:** **CM-10.** SPEC-03 §1 already designs `mc/{run}/{unit}`.

### 22. `409 agent_busy`

- **Local: n/a.** Local agents never raise it; `force` exists instead.
- **Cloud: WIRED+TESTED.** `tests/unit/cursor/test_cloud_capacity_and_busy.py`.
- **Cursor native:** described under item 5.
- **Needed:** CM-05 uses `force` after crash recovery.

### 23. `410 stream_expired`

- **Local: n/a.**
- **Cloud: WIRED+TESTED.** `adapters/cursor/cloud.py:821-842`, `cloud.py:896-950`.
- **Cursor native:** the retention header (S1).
- **Needed:** a drill only.

### 24. `429` and other provider errors

- **Local: ABSENT.**
  - `RateLimitError`, network, auth and integration errors are not mapped.
  - Only busy, not-found, cancel and sandbox errors are mapped (`adapters/cursor/bridge.py:303-374`).
- **Cloud: PARTIAL.**
  - `429` with `Retry-After` maps to `ProviderCapacityLimited` (`adapters/cursor/cloud_api.py:111-114`).
  - 401, 403, 5xx and `agent_archived` all become a generic `BridgeError` (`cloud_api.py:115`).
- **Cursor native:** typed errors with `is_retryable` and `retry_after` (S2).
- **Needed:** **CM-03.**

### 25. Dispatch reconciliation (lost receipt)

- **Local: PARTIAL.** Process memory only.
- **Cloud: WIRED+TESTED.** `agentId` lookup and `latestRunId`; `adapters/cursor/cloud.py:641-751`.
- **Cursor native:** local `list_runs`.
- **Needed:** CM-05.

### 26. Webhooks

- **Local: n/a.**
- **Cloud: ABSENT.**
- **Cursor native:** v1 webhooks are "coming soon"; v0 offers `statusChange`.
- **Needed:** [packet MO-45]. Add drill Q-C3 (can a v0-created agent be driven through v1?).

### 27. Multiple runs per agent

- **Local: WIRED+TESTED.** `turn_no > 1`.
- **Cloud: WIRED+TESTED.** Same.
- **Cursor native:** one active run per agent.
- **Needed:** nothing.

### 28. Environment selection

- **Local: PARTIAL.** Sandbox flag; `setting_sources` is fixed to `project`.
- **Cloud: PARTIAL.** `env.type` only (`adapters/cursor/cloud.py:490-491`).
- **Cursor native:** `env.name` (mutually exclusive with `repos`), pools and machines.
- **Needed:** [packet MO-13, MO-15].

### 29. Bridge process lifecycle

- **Local: PARTIAL.**
  - One bridge per lease, closed at `end_session` (`adapters/cursor/local.py:968-976`).
  - No `Ping` or `GetVersion` capability gate.
  - No orphan sweep.
  - Owned by the worker process.
- **Cloud: n/a.**
- **Cursor native:** `Ping`, `GetVersion` capabilities, `Shutdown(grace)`, connect mode (S4).
- **Needed:** **CM-05.**

### 30. Windows support

- **Local: ABSENT (refused).**
  - Refusal code: `adapters/cursor/bridge.py:101-119`.
  - Cause: the async bridge spawn needs the Proactor loop.
- **Cloud: WIRED+TESTED.** Runs on any worker.
- **Cursor native:** the bridge ships `win32 x64`; the sync `Popen` launch plus `connect`
  works on any loop.
- **Needed:** **CM-04.**

### 31. Local store and resume

- **Local: PARTIAL.**
  - Default SQLite under the lease `STATE_ROOT`.
  - Options re-supplied on resume (`adapters/cursor/local.py:588-602`).
  - The store dies with the lease.
- **Cloud: n/a.**
- **Cursor native:** `store` `sqlite | jsonl | custom` (custom calls back to the host).
- **Needed:** CM-06 (optional).

### 32. Agent hygiene (archive and orphans)

- **Local: PARTIAL.** `close_agent` at end.
- **Cloud: PARTIAL.**
  - Archives only the current agent at end (`adapters/cursor/cloud.py:1297-1298`).
  - Continuation sources and crashed attempts leak.
- **Cursor native:** `archive`, `unarchive`, `delete`, `list` filtered by `prUrl`.
- **Needed:** **CM-17.**

### 33. Knowledge work with no repo

- **Local: ABSENT.** [packet MO-51]
- **Cloud: ABSENT.** The binding requires `repo_url` (`domain/execution/lanes.py:732-736`).
- **Cursor native:** no-repo cloud agents (S1).
- **Needed:** **CM-22.** This corrects SPEC-03 §3.

## Work items

Item IDs use the `CM-nn` prefix. Sizes: S ≤ 2 days, M ≤ 1 week, L > 1 week. All items:

- keep `qualified=False`;
- run the repo verification rules (`make check`, real PostgreSQL and Temporal for durability
  claims);
- make no paid calls without owner authorization.

### P0: correctness defects

#### CM-10 Parallel Cursor units in one run get distinct workspaces (M)

- **Files:**
  - `adapters/cursor/workspace.py` (`lease_path`, add the holder key)
  - `adapters/cursor/cloud.py` (`run_branch`, change to `mc/<run>/<unit>`; `CURSOR_CLOUD_POLICY` reuse)
  - `adapters/cursor/scm.py`
  - `application/workspaces/policy.py` (if the slot naming changes)
  - tests under `tests/unit/cursor`, `tests/unit/workspaces`
- **Acceptance:**
  - A Stage Graph with two parallel `cursor_local` stages and two parallel `cursor_cloud`
    stages in one run gets four distinct leases and branches.
  - A retry of the same holder reuses its own lease.
  - Existing single-unit tests are unchanged.
  - Reattach finds the per-unit branch.
- **Depends on:** nothing. Align with SPEC-03 §1 and MO-50.

#### CM-09 Cloud declared-output custody and missing outputs (M)

- **Files:**
  - `adapters/cursor/cloud.py` (`end_session`, `closing_facts`)
  - `adapters/cursor/scm.py` (`read_tree` at head for `outputs/`)
  - `application/execution/operations/lane_outputs.py` (no change expected)
  - `tests/unit/cursor/test_cloud_workspace_and_resume.py`
- **Acceptance:**
  - `outputs/*` on the branch head is registered as `workspace-candidate://` refs with
    digests.
  - Closing facts carry `missing_outputs`.
  - With `missing_output_follow_up`, one follow-up run asks for the missing outputs through
    `wait_then_send`.
  - `artifacts/*` is still staged.
  - `prUrl` from the terminal frame is persisted into closing facts before archiving.
- **Depends on:** nothing. Coordinate with MO-51.

#### CM-08 Continuation and fork agent parity on cloud (S)

- **Files:**
  - `adapters/cursor/cloud.py` (`hydrate_agent`, factor `_create_body` shared with `start`)
  - `adapters/cursor/controls.py`
- **Acceptance:**
  - The continuation create carries the same `customSubagents`, `env`, `metadata`, model
    selection and (MO-30) `mcpServers` as `start`.
  - With `env_vars_ref`, it uses the `Idempotency-Key` path.
  - After `complete_handover`, the source agent is archived (idempotent).
  - A test asserts body parity.
- **Depends on:** nothing. MO-30 extends it.

#### CM-18 Refuse unknown staged turn text (S)

- **Files:** `adapters/cursor/local.py:639`, `adapters/cursor/cloud.py:624-626`.
- **Acceptance:**
  - A non-null `instruction_ref` with no staged text raises `NativeTurnLost`. It never
    falls back to `turn_text(operation)`.
  - Turn 1 and a `None` ref are unchanged.
- **Depends on:** nothing.

#### CM-13 One SSE vocabulary per run (S)

- **Files:**
  - `application/frames/kinds.py:139-154`
  - `adapters/cursor/cloud.py` (`_stream_frames`)
  - transcript materializer tests
- **Acceptance:**
  - First, a test that proves whether the transcript currently double-counts text or tool
    calls when both event families arrive.
  - Then persist one family as transcript-bearing (`interaction_update` for fidelity, or the
    simplified events). Keep the other as raw-only frames that never reach transcript or
    usage.
- **Depends on:** nothing.

### P1: settlement and accounting

#### CM-02 Per-run token attribution across all turns (M)

- **Files:**
  - `adapters/cursor/bridge.py` (`usage(agent_id, run_id=)`; map local `runs[].run_id` to
    turns; fall back to `run.usage`)
  - `adapters/cursor/local.py:867-886`
  - `adapters/cursor/cloud.py:1127-1158`
  - `application/execution/harness/lane_turns.py:2286-2307` (sum every turn of the
    execution, including replaced and continuation turns)
  - `domain/execution/lanes.py` `UsageReport` (additive `cache_read_tokens` and
    `cache_write_tokens`)
- **Acceptance:**
  - A cancel-and-replace plus a continuation fixture charges the sum of every run once.
  - Agent totals are never attributed to one run.
  - `unknown` stays unknown.
  - Closes C3 for Cursor.
- **Depends on:** nothing.

#### CM-01 Cloud and local cost settlement (M)

- **Files:**
  - a new `adapters/cursor/cost.py` (SDK `AsyncAgent.get_usage(run_id)` over a connected
    client, cloud not gated)
  - `adapters/temporal/deployment_composition.py:606-639` (compose `cost_reader`)
  - `lane_turns` or a deferred settlement activity
- **Acceptance:**
  - Cost settles from `charged_cents`, held as `estimated` until the provider reports it,
    re-read at a bounded delay because it is eventually consistent.
  - Never zero-filled.
  - The budget charge happens once.
  - Describe `cost: estimated_then_settled` becomes true in production.
- **Depends on:** CM-02 and CM-04 (the connect-mode client works on Windows workers).

#### CM-03 Typed provider error taxonomy (S)

- **Files:**
  - `adapters/cursor/bridge.py` (map `RateLimitError` to `ProviderCapacityLimited` with
    `retry_after`; `AuthenticationError`, `PermissionDeniedError` and
    `IntegrationNotConnectedError` to non-retryable typed errors carrying `help_url`;
    `NetworkError` and `APITimeoutError` to retryable; `agent_archived` to a typed error)
  - `adapters/cursor/cloud_api.py:90-115` (401, 403, 5xx, `agent_archived`)
  - the ADR-0011 classifier wiring
- **Acceptance:**
  - Each class routes to the correct retry counter.
  - `request_id` is recorded.
  - No provider text or keys appear in messages.
- **Depends on:** nothing.

### P1: local lane durability and portability

#### CM-04 cursor_local on Windows workers (M)

- **Files:**
  - `adapters/cursor/bridge.py` (launch through `asyncio.to_thread(Bridge.launch, ...)`
    plus `AsyncClient.connect`; sandbox stays off on Windows)
  - `bootstrap/preflight` `LANE_HOSTS`
  - `host_gate`
  - the kernel hook command (resolved interpreter, not bare `python`)
- **Acceptance:**
  - On a Windows worker with SelectorEventLoop, a fixture bridge launches, creates, sends,
    observes and closes.
  - The host gate allows Windows only behind an explicit setting until drill CD-15 passes.
  - Describe `os` is updated.
- **Depends on:** nothing.

#### CM-05 Detached bridge and live reattach (L)

- **Files:**
  - `adapters/cursor/bridge.py` (sidecar launcher writing a 0600 discovery file under the
    lease state root; `connect` on reattach; `Ping` and `GetVersion` capability gate)
  - `adapters/cursor/local.py` (`_bridge`, `reattach`, `reconcile_dispatch` through
    `list_runs`, newest first, compared with the journal's anchor; `force` on the first
    send after an `in_doubt` resolution)
  - an orphan-bridge sweep at worker start
- **Acceptance:**
  - Killing the worker mid-run and starting a new worker on the same host resumes observing
    the **same live run** from the stored offset, with no duplicate frames.
  - A send lost after the bridge accepted it reconciles `found`.
  - Bridges are terminated at `end_session` and by the sweep.
  - Describe `reattach` stays `emulated` until a drill.
- **Depends on:** CM-04 (shared launcher).

#### CM-06 Local store and conversation fork drill-gated (M, optional)

- **Files:** `adapters/cursor/snapshot.py` (include the bridge store in the snapshot);
  `adapters/cursor/local.py` (`prepare` of a fork restores it and `resume`s the source agent
  id).
- **Acceptance:**
  - After drill CD-09 proves that a copied store resumes in a new cwd, the fork continues
    the conversation.
  - Otherwise the item is closed as unsupported.
- **Depends on:** CM-05 and the CD-09 drill.

#### CM-07 Conversation export for forks and continuations (S)

- **Files:**
  - `adapters/cursor/controls.py`
  - local: the bridge `run.conversation()`
  - cloud: SDK conversation or v0 `/conversation`
- **Acceptance:**
  - A fork or continuation packet carries a bounded, scrubbed transcript excerpt with a
    digest and source.
  - When the excerpt is missing, this is reported, never invented.
- **Depends on:** CM-04 for cloud through the SDK.

### P2: control levers and options

#### CM-11 Model selection with params and validation (S)

- **Files:**
  - additive `model_params` on `mc.cursor_binding.v1` (or the v2 work in MO-31)
  - `application/authoring/cursor_launch.py`
  - `adapters/cursor/bridge.py` and `adapters/cursor/cloud.py`
- **Acceptance:**
  - Launch validates the id and params against `models.list()` or `/v1/models`, refusing
    with `MODEL_UNAVAILABLE`.
  - The params reach the create request.
  - The resolved model is in closing facts.
  - Per-send model override on local only (REST runs take no model).
- **Depends on:** nothing.

#### CM-12 Subagent honesty (S)

- **Files:** `adapters/cursor/cloud.py:469-474`; projection rows.
- **Acceptance:**
  - More than 20 inline subagents is a launch refusal, never a truncation.
  - Built-in name collisions are refused.
  - `subordinate_visibility` stays `unqualified` on cloud.
- **Depends on:** MO-30.

#### CM-15 Plan-then-approve gate (M)

- **Files:**
  - `adapters/cursor/cloud.py` (per-run `mode` in the follow-up body)
  - `adapters/cursor/bridge.py` (`SendOptions(mode=)`)
  - manifest lowering in `application/programs/human_gates`
- **Acceptance:**
  - Turn 1 runs in `plan`.
  - A `workflow_gate` Human Task shows the plan.
  - Approve sends turn 2 in `agent`.
  - Deny ends the unit `not_accepted`.
- **Depends on:** nothing.

#### CM-16 Local approval and question channel through custom tools (M)

- **Files:**
  - a new `adapters/cursor/custom_tools.py` (`mc_request_approval`, `mc_ask`; the execute
    callback opens a Human Task and waits, capped at 600 s as in MP-11)
  - `bridge.py` `_options(custom_tools=)`, re-supplied on resume
  - `qualification.py` `approval_coverage`
- **Acceptance:**
  - A fixture shows the tool blocks, the Human Task resolves, and the result returns to the
    agent.
  - The admission matrix lists `provider_question` as `unqualified` (implemented) for
    `cursor_local`.
  - Cloud stays unsupported.
- **Depends on:** CM-05 (callback server in connect mode).

#### CM-17 Cloud agent hygiene sweep (S)

- **Files:** a new sweep activity in `adapters/temporal/activities`; `adapters/cursor/cloud_api.py`
  (`list_agents`, `unarchive`).
- **Acceptance:**
  - Agents named `mc-*` or carrying `metadata.mc_run_id` with no open harness execution are
    archived.
  - Nothing is deleted.
  - The run is reported in inspection.
- **Depends on:** CM-08.

#### CM-19 Cancel robustness (S)

- **Files:** `adapters/cursor/cloud.py:1109-1125`.
- **Acceptance:**
  - `get_run` after a cancel tolerates `AgentNotFound` (acknowledged, status `unknown`).
  - Cancelling a `CREATING` run is covered.
  - The provider-acknowledged timestamp is set from the cancel response.
- **Depends on:** nothing.

#### CM-20 Follow-up prompt images and mode passthrough (S)

- **Files:** `adapters/cursor/cloud.py:628`, `adapters/cursor/bridge.py:328-336`.
- **Acceptance:** packet image inputs (≤5, 15 MB) and per-turn mode reach the provider.
- **Depends on:** MO-30.

#### CM-22 No-repo cursor_cloud agents for knowledge work (M)

- **Files:**
  - `domain/execution/lanes.py:732-736`
  - `adapters/cursor/cloud.py` (`prepare` skips the branch; the packet goes through the
    prompt plus an ingress fetch)
  - SPEC-03 §3 correction
- **Acceptance:**
  - A knowledge mission with no repo completes.
  - Outputs come back through the artifacts API (CM-09) or ingress.
- **Depends on:** MO-40, MO-51.

#### CM-14 Context occupancy for Cursor (S)

- **Files:** a `context_occupancy` implementation in `local.py` and `cloud.py`.
- **Acceptance:**
  - Occupancy is the last run's input plus cache-read tokens against the model window, where
    the models API exposes it. Otherwise it stays `unknown` with a reason.
  - `summary-completed` is recorded as native compaction observed.
- **Depends on:** CM-02, CM-11.

## Qualification drills (owner-run, paid, finite budget; record under `docs/qualification/lanes/<profile>/`)

Each drill records: scrubbed recordings, the frame transcript, journal rows, and
spent / reserved / unknown units.

| ID | Profile | Drill | Pass criterion |
| --- | --- | --- | --- |
| CD-01 | both | Launch, observe and settle a one-turn task | `run.final` or `RunResult`; patch, outputs and usage recorded; lease released after custody |
| CD-02 | cloud | Kill the worker mid-run; start a fresh worker | Reattach rehydrates; SSE resumes from `Last-Event-ID`; zero duplicate frames |
| CD-03 | local | Same as CD-02, without and then with CM-05 | Without: unit `in_doubt`, no resend. With: same live run observed to completion |
| CD-04 | cloud | Read the stream after retention | One `stream.expired` frame; terminal truth from the run record; retention header value recorded |
| CD-05 | cloud | Follow-up while a run is active | `409 agent_busy`, `busy` journaled, exactly one run after idle |
| CD-06 | both | `interrupt_and_inject` | Old run `CANCELLED`; replacement run on the same agent carries the injected text; a fence that lands mid-drain prevents the replacement |
| CD-07 | both | Immediate cancel | Four timestamps recorded; local Kernel Hook denies after the fence; cloud stops within one API round-trip |
| CD-08 | both | Continuation (`request_continuation`) | New agent; staged prompt is turn 1; subagents and env present (CM-08); source agent archived |
| CD-09 | both | Fork from snapshot | Workspace digests match; conversation export present (CM-07); local store-copy resume (CM-06) recorded either way |
| CD-10 | both | Usage and cost | Per-run tokens sum across replaced turns; cost re-read at +5 and +15 min converges; no zero-fill |
| CD-11 | cloud | Declared outputs and artifacts | `outputs/` registered from the branch; `artifacts/` downloaded within 15 min; missing-output follow-up fires once |
| CD-12 | cloud | `autoCreatePR` on a throwaway repo | PR URL attributed to the run and persisted before archiving |
| CD-13 | both | Model params | `models.list()` choice applied; resolved model in closing facts; an invalid param refused before launch |
| CD-14 | both | Two parallel units in one run (CM-10) | Distinct leases and branches; no fence-out; both settle |
| CD-15 | local | Windows worker in connect mode (CM-04) | Launch, observe, cancel, end on SelectorEventLoop; hooks fire through the resolved interpreter |
| CD-16 | cloud | Idempotency | Replaying `agentId` gives `409 agent_id_conflict` and a reattach; `Idempotency-Key` replay window measured; whether `POST /runs` honours a key is recorded |
| CD-17 | both | Plan gate (CM-15) | Plan turn, then Human Task, then agent turn; deny gives `not_accepted` |
| CD-18 | local | Custom-tool approval (CM-16) | Tool blocks; human answer returns; timeout gives a typed refusal |
| CD-19 | cloud | `429` (only if a rate limit is hit naturally) | `Retry-After` honoured by a Temporal timer; one create afterwards |
| CD-20 | cloud | Headless hook matrix plus v0 interop (Q-C3) | Which of `beforeMCPExecution`, `preCompact` and `stop` fire is recorded; whether a v0 webhook agent accepts v1 runs and streams is recorded |

Drills carried over from the existing READMEs and still open:

- concurrent local `send()`;
- rules without `setting_sources`;
- `run.git`;
- the numeric rate limit;
- `metadata` and `envVars` acceptance;
- `git.branches[]` attribution.
