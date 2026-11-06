---
type: Concept
category: execution
title: Hosted API lanes
description: Managed Agents and Codex Agents projection, durable tool approvals, artifact custody and governed publication, with explicit qualification limits.
tags: [mission-control, lanes, harness, hosted, approvals, implementation]
aliases: [claude_managed, codex_agents, Managed Agents, hosted agent APIs]
questions:
  - What do the hosted Managed Agents and Codex lanes support?
  - How are hosted tool approvals and artifact publication governed?
  - What qualification limits apply to the hosted API lanes?
updated: 2026-11-01
---

# Hosted API lanes

The `claude_managed` and `codex_agents` profiles use provider session APIs.
Their production composition differs from [local provider lanes](provider-lanes.md).

## Hosted native approvals and bundle publication (HL-09)

Managed Agents permission and custom-tool calls pass a Stop Fence and durable Operation Intent keyed by session, turn and native call. Human Task timeouts leave provider requests pending; reviewer argument edits are denied because the provider confirmation cannot apply them. Readiness requires the Mission Layer setup commands to have succeeded before env.prepared.

Both hosted observers retry durable pending actions while the provider stream is quiet. A late human decision therefore resumes the original native call without another provider event. Approval context is sealed to the operation's effective configuration digest, matching the persisted lane session and PostgreSQL approval probe.

Code publication downloads the session-scoped mc.bundle into artifact custody before review. The isolated Git publisher verifies the sealed base and the exact mission branch, scans every new commit message and tree for secrets, and pushes only that branch. A separate governed repo_pr call creates the PR. No repository write credential enters the provider sandbox. Cancellation observes closing frames before settlement and retention. The opt-in local Temporal/provider drill labels its local PR host as a fixture; live GitHub publication and qualification remain separate evidence.

## Hosted projection and production composition (HL-21)

The reviewed deployment providers.claude_managed and providers.codex_agents entries carry inline hosted_projection snapshots, exact API wire pins, model/auth routes and provider environments. Catalog skills and HTTPS MCP rows project through the MO-30 API targets. Selected catalog callbacks and subagent programs without a trusted executor are refused before provider calls. The migration helper preserves the original pack resource keys; unchanged fake syncs create no new resources.

Hosted code launch requires repository_commits[repo-url#ref], an explicitly reviewed immutable base SHA, and provider_workspace. Snapshot control stays unsupported. Operation authority/instruction segments use the native session instruction override, leaving reusable agent resources unchanged. Bound network policies shape provider environments. Bound secret references use the shared Secret Broker and provider vault; known org-key sources are refused. Repository credentials require current exact trusted readonly evidence before sync; an unconfigured proof fails closed. Publication credentials stay in the worker.

Opt-in production workers register both API profiles, scoped custom signals, durable approvals and maintenance deleters. The restricted ingress service and installation identity come from the actual Application Binding; no fallback identity authorizes hosted execution. Codex function-tool dispatch is the separate HL-13 integration.

## Codex function tools (HL-13)

Root-turn required_actions are the only custom function handles the worker answers. Native (session, turn, call) keys pass the Stop Fence and persist an Operation Intent before handling; a pending Human Task or timeout leaves the request pending. Result submission is idempotent and rechecks the current provider handle. Subagent handles are ignored. Turn recovery reads `/agents/sessions/{session}/turns/{turn}/items`; the session-wide Items route does not accept a turn_id filter. Built-in shell and patch remain ungated.

mc_upload_artifact stages bounded bytes into scoped content-addressed custody and records a governed upload receipt. The provider can download session artifacts only after completed turns, so a current-turn path-only upload returns an explicit completion/retry requirement; bounded content_base64 can hand current bytes to custody. mc_publish accepts only an upload intent of the same run, execution generation and session, verifies the immutable bundle, and pushes the sealed mission branch through the worker credential. mc_open_pr uses the existing governed PR gateway; mc_comment reconciles an intent marker on that mission PR. These external effects require Human Task approval.

Controlled Mission Layer setup is offered through mc_prepare. env.prepared is accepted only after provider command records show the exact setup commands completed successfully. The production source now requires the current exact readonly prerequisite proof before vault sync. Output custody and custom-tool approval suspension are implemented as emulated features; qualification remains false and native cost unknown.

After creating an agent or environment template, preparation waits at most ten seconds for its exact ID and immutable readback to appear in the native index. Missing or changed readback fails preparation rather than returning a receipt that an immediate second sync cannot reuse. For a first dispatch from an idle session with empty root history, one pending action can identify the turn only after direct retrieval proves the same session, root ownership and active status. Ambiguous and later-turn cases retain normal reconciliation.

Codex readiness may reuse a completed root turn's exact setup proof in the same session. Failed or subagent turns and changed effective configuration, provider binding or setup commands cannot supply that proof.

Built / specified / goal: both hosted profiles implemented and tested offline against fakes (`tests/unit/openai_agents/test_tools.py`); qualification false and native cost unknown; live GitHub publication and a governed Managed Agents budget pause are unproven. Placement in the lane family and the Agents API versus SDK distinction: [lanes and harness](lanes-and-harness.md).

## Citations

- [Hosted lane specification](../specs/archive/materialization-observation-2026-10/SPEC-06-hosted-api-lanes.md).
- [Hosted composition](../../src/mission_control/adapters/temporal/hosted_lane_composition.py),
  [Codex function tools](../../src/mission_control/adapters/openai_agents/tools.py),
  [artifact custody](../../src/mission_control/adapters/remote_session/function_custody.py).
- [Function tool tests](../../tests/unit/openai_agents/test_tools.py),
  [run integration report](../specs/archive/materialization-observation-2026-10/runs/RUN-1-REPORT.md).
