---
type: Concept
category: execution
title: Cursor lane
description: "The cursor_local and cursor_cloud lane profiles as built: bridge and Cloud Agents API harnesses, workspace leases and branch control, Kernel Hook callback, frame mapping, emulated snapshot, fork and continuation, the MP-09 v2 describes, dispatch reconciliation and Cursor launch author, and why both profiles are still unqualified."
tags: [mission-control, cursor, lanes, harness, implementation, qualification]
aliases: [cursor_local, cursor_cloud, Cloud Agents API, Cursor bridge]
questions:
  - How do the Cursor Local and Cursor Cloud lanes run and fork?
  - Why are both Cursor profiles still unqualified?
  - How does a Cursor Local fork restore a workspace?
  - What does a Cursor Cloud fork still lack?
updated: 2026-11-01
---

# Cursor lane

Cursor is one [Lane](../../GLOSSARY.md) with two [Lane Profiles](../../GLOSSARY.md), `cursor_local`
and `cursor_cloud` (ADR-0030). Both implement the protocol in [lanes and
harness](lanes-and-harness.md), run through the `lane.turn` segment loop (whatever
`MISSION_CONTROL_LANE_SEGMENT_LOOP` says), and write Provider Frames that the reducer turns into
mission events ([events and commands](events-and-commands.md)). The package is `adapters/cursor/`;
importing it imports no SDK (the SDK loads lazily in `bridge.py`).

## Implemented

**Binding.** A Cursor execution binding carries a `mc.cursor_binding.v2`
(`domain/execution/lanes.py`: SDK, bridge, protocol and Cloud API pins, workspace with
`repo_url`, `base_ref`, `lease_root`, `branch_prefix` default `mc/`, sandbox and agent options,
and pins for skills, MCP servers, subagents, hook scripts and plugins; v1 still reads; MO-31).
It names native identity only, never a credential; the API key is passed in agent options,
never in the bridge's allowlisted environment (`bridge.py`, `bridge_spawn.py`, MO-04). The
operation request carries it sealed as its one `lane_binding` (schema id `mc.cursor_binding.v2`)
with a `lane_dispatch` stating its task queue and wall-clock bound; the Cursor harnesses unseal
it (`CursorExecutionBinding.carried_by`), the core never does (OC-R2).

**`cursor_local`** (`local.py::CursorLocalHarness`). `prepare` leases a git worktree at the base
ref under the binding's workspace policy ([recovery](recovery.md)), or an initialized repository
for research missions (`workspace.py`, `application/execution/harness/leases.py`; leases persist in
`mission_control.workspace_lease`; `GitWorktreeLeaser` delegates to the provider-neutral `WorkspaceAllocator` in
`application/workspaces/`), places the Host Projection and the Context Packet (`placement.py` in
`application/agentic_components/`: `.cursor/rules/mc-mission.mdc`, `.cursor/skills`,
`.cursor/agents`, `.cursor/mcp.json`, `.cursor/hooks.json` with Kernel Hooks first, `.mission/`,
`inputs/`) over the repository's own files ([instruction layering](instruction-layering.md)), and
refuses `CAPABILITY_DRIFT` when projection digests differ from the pins, `MATERIALIZATION_CONFLICT`
on a refused conflict or `UNSUPPORTED_BEHAVIOR` for a sandbox on a host without one. `start`
launches `cursor-sdk==1.0.37` through the `CursorBridgeLauncher` port with a pinned state root and
creates the agent with `setting_sources=["project"]`; `send_turn` uses idempotency key
`<execution>:<generation>:turn:<n>`; frames are keyed by bridge offset (`frames.py`). Kernel Hooks
run as `.mission/hooks/kernel.py` (`kernel_hook_script.py`), fail-closed on permission events, and
call the worker back on a loopback listener (`MISSION_CONTROL_HOOK_CALLBACK_PORT`, default 47555)
with a task token minted at `start`, stored only as a digest and bound to scope, run, attempt,
generation and execution (`application/execution/harness/hook_callbacks.py`, `interfaces/http/hook_callback.py`). The callback
consults the Stop Fence and writes the Operation Intent before answering `allow`;
`hooks_callback.py` maps Cursor events (`preToolUse`, `beforeShellExecution`, `beforeMCPExecution`,
`subagentStart`) to `mc.hook_input.v1`.

**`cursor_cloud`** (`cloud.py::CursorCloudHarness` on the ADR-0052 base
`adapters/remote_session/`). Cloud Agents API v1 over `httpx`. Because v1 has no branch-name field,
`prepare` creates and pushes a distinct branch for each execution unit under `mc/<run_id>/`,
carrying the Host Projection and Context Packet. The bounded readable unit hint and identity
hash are produced by [mission_branch](../../src/mission_control/application/workspaces/cloud_branches.py);
generations of that unit may reattach to its branch. It uses the worker's reviewed git
configuration, and the agent works on that branch; `end_session` fetches the
branch and takes the diff as the patch artifact. MCP servers travel inline (`mcpServers`, every
create and run; cloud ignores `.cursor/mcp.json`) and subagents as `customSubagents` (MO-30).
Create uses a client `agentId` (`409 agent_id_conflict` means reattach); a busy agent's follow-up
is `busy` (`wait_then_send`); SSE resumes with `Last-Event-ID`; artifacts and usage come from the
API.

**Controls.** Both profiles declare `pause: unsupported` (refused mid-run, applied at the run
boundary only), `queue_instruction` and `resume` as `wait_then_send`, `interrupt_and_inject` as
`cancel_and_replace` (uncertain effects must settle before a replacement turn runs,
`application/execution/harness/inject.py`, `controls.py`), `snapshot`, `fork` and
`request_continuation` as `emulated`. `snapshot.py` freezes a lease as `mc.cursor_snapshot.v1`
(binary patch against the base commit including untracked files, packet roots, native refs) named
`cursor-snapshot:<manifest ref>`; `end_session` records that ref on the released lease so a fork's
workspace item can restore it (readiness commit `37d7deb`). `controls.py` holds
`CursorWorkspaceSnapshots` and `CursorSessionHydrator`: a continuation always creates a new agent
in the same lease and stages the hydration prompt as the next turn ([context and
continuation](context-and-continuation.md)).

**Honesty about hooks.** Cloud runs fire no `sessionStart`, `sessionEnd` or MCP hooks, and the
cloud VM cannot reach the worker's loopback callback, so `cursor_cloud` declares
`fail_closed=False`; only catalog command hooks run there and the Stop Fence reaches a cloud run
through the API cancel. Usage tokens are `settled_per_turn`, cost `estimated_then_settled`.

## MP-09 parity (integrated 2026-10-09)

- **Describe v2.** Both profiles publish implemented `mc.lane_describe.v2` matrices (v1 kept as
  `CURSOR_*_DESCRIBE_V1`): `approval_modes = (workflow_gate,)`, `compaction_control = unsupported`
  (`preCompact` is observe-only), `cursor_cloud` `approval_suspension` and MCP enforcement
  unsupported. `cursor-sdk 1.0.37` exposes `SDKRequestMessage(request_id)` but no API that answers
  it, so `provider_permission` is refused at admission (`adapters/cursor/qualification.py`).
- **Dispatch.** Both harnesses implement `reconcile_dispatch` (MP-06): local answers `found` only
  from this process's memory, otherwise `unknown` (parks `in_doubt`); cloud reconciles a create by
  the client `agentId` (`404` is an authoritative `not_received`) and a send by `latestRunId`.
  `reattach` re-supplies the pinned local agent options (`rehydrated`).
- **Cloud workspace.** `prepare` records a provider workspace lease through
  `WorkspaceAllocator.allocate_provider_workspace`; `snapshot` records `branch:<branch>@<sha>` on
  the lease, so a cloud fork can restore it. `GitBranchPublisher.publish` (`scm.py`) commits a
  retry on top of that unit's branch head. This cloud unit isolation already exists; CM-10's
  local workspace isolation is a separate check, not another cloud allocator.
  `429` with `Retry-After` becomes
  `ProviderCapacityLimited`; `410 stream_expired` reconciles terminal truth from the run record.
- **Host gate.** `bridge.host_gate()` refuses `cursor_local` on Windows (`LANE_UNSUPPORTED_OS`) in
  `prepare`, `start` and the launcher, matching preflight's `LANE_HOSTS`.
  This records the MP-09 baseline. Run 2's opt-in Windows bridge work must be checked against
  the final integrated build; offline transport tests do not qualify the Windows sandbox.
- **Launch.** `application/authoring/cursor_launch.py` seals `mc.cursor_binding.v2` for Cursor
  stages and Goal Loop roles from mission/v1 and v2 (`providers.cursor_*` of the v2 launch
  bindings) with the digests `RenderedProjectionSource` re-renders from `projected_pins()` at
  `prepare` (a plugin is pinned whole; another expansion is `CAPABILITY_DRIFT`). Executors and
  model settings are refused at their pointer, so Missions 2 and 3 launch once their Deep Agents
  verifiers move onto the Cursor lane and Mission 3 drops its two executors (MO-31).

## Qualification and known limits

Both profiles are `qualified=False`. Offline evidence (`make lane-qualify PROFILE=...`,
`tests/unit/cursor`) and the MP-20 parity rows (Stage Graph, Goal Loop and chain on real PostgreSQL
and Temporal with FIXTURE bridge and API responders) never flip it; the paid drill (OVE-55) is
owner-run and has not run ([cursor_local](../qualification/lanes/cursor_local/README.md),
[cursor_cloud](../qualification/lanes/cursor_cloud/README.md)).

**Run 2 finish (2026-10-20).** MR-03 ran `cursor_local` once on a WSL 2 worker (run
`7132d2de…`) and is **blocked**. Compile, preflight and C9/M4 attestation passed and the SDK bridge
started (peak 199 MB, so memory is not the blocker). Six seconds into the first turn the SDK's
`observe_run` raised a configuration error, which the adapter maps to
`ProviderConfigurationRejected` without provider text. The operation failed while the native agent
ran on unobserved. The run is parked `cancelling` on an unsettled usage reservation, and MR-13
(Cloud) did not run. Both move to the Cursor provider sprint
([finish disposition](../specs/archive/materialization-observation-2026-10/runs/RUN-2-FINISH-DISPOSITION-2026-10.md), [carry-forward register](../specs/provider-consolidation-2026-10/RUN-2-CARRY-FORWARD.md)).

Open: a Linux or WSL 2 worker for
`cursor_local`; the Windows sandbox; governed tools on Cursor; the `UNVERIFIED` items the drill
settles (cloud idempotency window, concurrent local `send()`, rules without `setting_sources`,
`run.git`, stream retention, numeric rate limit).

The audit's missing cloud workspace/environment composition is superseded by [deployment composition](../../src/mission_control/adapters/temporal/deployment_composition.py)
(`SecretEnvVarsResolver`, the provider workspace allocator, environment provisioning, optional remote signal delivery); delivery is still distinct from provider read-back and exercised controls.
Vendor facts (SDK 1.0.31, Cloud Agents API v1): [Cursor SDK facts](../research/cursor/sdk-facts.md).

Built / specified / goal: both profiles implemented and tested offline (FIXTURE bridge and API); `cursor_local` run live once and blocked (MR-03); unqualified; a `cursor_cloud` fork restore is not built.

## Citations

- Spec: [SPEC-07](../specs/archive/fast-track-2026-10/SPEC-07-harness-and-cursor-lane.md); [Cursor platform research](../specs/archive/fast-track-2026-10/research/cursor-platform.md); [00-ARCHITECTURE](../specs/archive/fast-track-2026-10/00-ARCHITECTURE.md) (lane matrix).
- ADRs: [0018](../adr/0018-coding-agents-are-execution-lanes.md), [0019](../adr/0019-coding-lanes-worker-hosted-local-first.md), [0030](../adr/0030-cursor-lane-two-profiles-reducer-from-frames-hydrated-fork.md), [0031](../adr/0031-temporal-lifecycle-synthesis-observe-activity-updates-seeded-forks.md),
  [0052](../adr/0052-remote-session-lane-base-shared-machinery-for-provider-session-apis.md).
- Qualification: [lane qualification README](../qualification/lanes/README.md), [owner runbook](../specs/archive/fast-track-2026-10/OWNER-FIXTURE-RUNBOOK.md).
- Code: [local lane](../../src/mission_control/adapters/cursor/local.py), [cloud lane](../../src/mission_control/adapters/cursor/cloud.py), [Cloud API client](../../src/mission_control/adapters/cursor/cloud_api.py), [Remote Session Lane base](../../src/mission_control/adapters/remote_session/lane.py),
  [bridge](../../src/mission_control/adapters/cursor/bridge.py), [frame mapper](../../src/mission_control/adapters/cursor/frames.py), [projection digests](../../src/mission_control/adapters/cursor/projection.py), [workspace leases](../../src/mission_control/adapters/cursor/workspace.py),
  [SCM branch control](../../src/mission_control/adapters/cursor/scm.py), [snapshot](../../src/mission_control/adapters/cursor/snapshot.py), [controls and hydrator](../../src/mission_control/adapters/cursor/controls.py), [hook payload mapper](../../src/mission_control/adapters/cursor/hooks_callback.py),
  [kernel hook script](../../src/mission_control/adapters/cursor/kernel_hook_script.py), [hook callback service](../../src/mission_control/application/execution/harness/hook_callbacks.py), [hook callback route](../../src/mission_control/interfaces/http/hook_callback.py),
  [interrupt and inject](../../src/mission_control/application/execution/harness/inject.py), [lane controls](../../src/mission_control/application/execution/harness/controls.py), [describe matrices](../../src/mission_control/application/execution/harness/describe.py), [lane contracts](../../src/mission_control/domain/execution/lanes.py),
  [approval coverage and proposed describe](../../src/mission_control/adapters/cursor/qualification.py), [Cursor launch author](../../src/mission_control/application/authoring/cursor_launch.py).
- Tests: [local lane](../../tests/unit/harness/test_cursor_local.py), [cloud lane](../../tests/unit/harness/test_cursor_cloud.py), [controls](../../tests/unit/harness/test_cursor_controls.py), [hook callback](../../tests/unit/harness/test_hook_callback.py), [Cursor describe cells](../../tests/unit/harness/test_describe_honesty.py),
  [lane conformance suite](../../tests/conformance/lanes/README.md), [local fixtures](../../tests/integration/cursor/test_cursor_local_fixtures.py), [cloud fixtures](../../tests/integration/cursor/test_cursor_cloud_fixtures.py), [kernel hook round trip](../../tests/integration/cursor/test_kernel_hook_roundtrip.py),
  [lane controls in PostgreSQL](../../tests/integration/postgres/test_ft_g4_lane_controls_postgres.py), [workspace lease](../../tests/integration/postgres/test_workspace_lease.py), [cloud reconcile](../../tests/unit/cursor/test_cloud_reconcile.py), [cloud workspace and resume](../../tests/unit/cursor/test_cloud_workspace_and_resume.py),
  [host gate](../../tests/unit/cursor/test_host_gate.py), [Cursor launch](../../tests/unit/authoring/test_manifest_cursor_launch.py), [cloud segment loop on real services](../../tests/integration/cursor/test_mp09_cloud_segment_loop_real_services.py).
