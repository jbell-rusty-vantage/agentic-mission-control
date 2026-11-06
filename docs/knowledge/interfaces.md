---
type: Concept
category: surfaces
title: Public interfaces
description: The HTTP routers mounted by the configured API (all nineteen, including ingress, cognition points and closures, artifacts, run evidence, coordinator inbox, output inspection and knowledge reviews), the /missions Socket.IO entrypoint, missionctl command groups, the coordinator and operator MCP tool families, the implemented scope and error vocabulary and the OAuth rule; what is not built.
tags: [mission-control, interfaces, http, cli, mcp, implementation]
aliases: [public API, HTTP routers, missionctl groups, MCP tools]
questions:
  - Which HTTP routes, CLI verbs and MCP tools exist today?
  - Which prefix does a given route live under and who may call it?
  - Why did the API answer unauthorized, stale_version or installation_unavailable?
  - Which surfaces are specified but not built?
updated: 2026-11-01
---

# Public interfaces

Every surface is transport only: it parses and authorizes, then calls the same application handlers
([mission control](mission-control.md)). The scoped prefix is `/v1/applications/{application_id}`; the
tenant scope comes from the verified token and other applications are refused (`APPLICATION_FORBIDDEN`).
How agents drive these surfaces (the skill router, `missionctl` grammar, MCP onboarding) is
[coordinator surface](coordinator-surface.md); startup and authentication are [operations](operations.md).

## HTTP routers mounted by the configured API

`bootstrap/api.py:964-982` includes nineteen routers (`create_app`); `GET /health/live` and
`GET /health/ready` (503 `installation_unavailable`) are on the app itself. All paths are under the
scoped prefix unless stated.

| Router (`interfaces/http/`) | Routes |
| --- | --- |
| `mission_control` | `GET runs/{id}/inspection`, `runs/{id}/commands`; `POST runs/{id}/commands`, `snapshots`, `forks`, `reconcile-unit`, `launch`; `GET runs/{id}/snapshots/{snapshot_id}`; `POST run-requests` |
| `ingress` (prefix `/v1/ingress/{application_id}`) | `POST signals`, `artifacts:prepare`, `artifacts:commit`, `provider/cursor/{run_ref}`, `provider/{provider}`, `github`, `missions:request`; `GET missions:request/{request_id}` ([signal ingress](signal-ingress.md)) |
| `catalog` (`/catalog`) | `GET definitions`, `pins/{pin}`; `POST resolve`, `search`, `discover`, `inspect`, `components/search`, `publish:prepare`, `publish:complete`, `pin`, `render` ([capabilities](capabilities.md)) |
| `lanes`, `models` | `/lanes` list and `{lane_profile}`; `/models` list and `{profile}` with every lane's route verdict ([model catalog](model-catalog.md)) |
| `selection` (`/selection`) | `POST search`, `POST check` ([selection workspace](selection-workspace.md)) |
| `stop_fence`, `continuation` | `GET runs/{id}/stop-fence`; `GET runs/{id}/checkpoints[/{checkpoint_id}]` |
| `transcript` | `GET runs/{id}/transcript`, `frames/tail`, `runs`, `runs/{id}/transcript/search` ([transcript](provider-frames-and-transcript.md)) |
| `cognition_points` | `GET runs/{id}/points`, `points/{point_id}`, `state-as-of`, `closure`, `frames`, `replay`; `GET runs/{id}/closures`; `POST runs/{id}/points:reconcile` ([joinability](unit-and-point-joinability.md), [workspace closure](workspace-closure.md)) |
| `artifacts` | `GET runs/{id}/artifacts/{ref:path}` (`frame-body://`, `closure-body://`, `artifact://`) |
| `run_evidence` | `GET runs/{id}/evidence`, `inputs`, `completion-evidence`, `goal-completion-evidence` |
| `subscriptions` | `POST` and `GET /subscriptions`, `DELETE /subscriptions/{id}`, `POST .../resume`, `GET missions/{id}/events` (SSE) |
| `chains`, `missions` | `GET chains/{id}`, `chains?mission_id=`; `POST missions:compile`, `missions:submit`, `missions:start`, `missions/{id}/runs` |
| `human_tasks` | `GET human-tasks[/{id}]`, `POST human-tasks/{id}/resolutions` |
| `coordinator_inbox` | `POST/GET /coordinator-inboxes`, `GET .../{sub}/notifications`, `attention`, `POST .../acks`, `notifications/{n}/commands\|observations\|content`, `DELETE` ([wake channels](wake-channels.md), [coordinator attention](coordinator-attention.md)) |
| `output_inspection` | `GET runs/{id}/outputs`, `outputs/{obligation_key}/revisions`, `output-events`, `transfer-plans`; `GET transfer-plans/{plan_id}` ([output contracts](output-contracts.md)) |
| `knowledge_reviews` | `POST runs/{id}/knowledge-reviews`, `POST runs/{id}/evaluator-attempt-resets` ([trusted judgment](trusted-judgment.md), [evaluator attempts](evaluator-attempts.md)) |

Mounted only by the proof facade `bootstrap/technical_api.py` (not primary startup): `/control-plane/v1`,
`/run-control/v1` (run-requests, launch, commands, budget, effects, outbox, snapshots and forks via
`run_forks.py`) and `/v2/graph-runtime/schemas`. The Agent Server app also mounts the graph-runtime
schema router. The worker-only Kernel Hook callback `POST /v1/applications/{app}/internal/hook-callback`
(`hook_callback.py`) is served on the worker's loopback listener, never the public API.
`bootstrap.realtime:create_asgi_app` serves the same API plus the `/missions` Socket.IO namespace
([mission stream](mission-stream.md)). `missions:start` answers `409 start_unavailable` with a manifest
pointer until the operator's launch bindings bind every node ([mission manifest](mission-manifest.md)).

## missionctl

`interfaces/cli/main.py` is an argparse client over the scoped prefix; extra modules add groups.

| Group | Verbs |
| --- | --- |
| `run` | `inspect`, `admit`, `snapshot`, `fork` (`--instruction-file`), `reconcile`, `start`, `transcript`, `frames --tail`, `list`, `search`, `checkpoint`, `points`, `state-as-of`, `artifact`, `closure`, `replay --dry-run` |
| `command` | `send`, `list`, `queue`, `inject`, `cancel --urgency` |
| `mission`, `chain` | `schema`, `compile --offline`, `submit`, `start`; `chain inspect` |
| `subscribe`, `events`, `wait`, `inbox` | `create\|list\|close`; `watch --after-seq`; `wait`; `inbox list\|ack\|observe\|content\|attention` |
| `lane`, `model`, `catalog` | `list`, `describe`, `async-graphs`; `catalog list\|resolve\|search\|discover\|inspect\|components\|pin\|render\|publish` |
| `search`, `workspace check` | [selection workspace](selection-workspace.md) |
| `outputs`, `knowledge` | `outputs show\|revisions\|events\|plans\|plan`; `knowledge review` |
| `setup`, `prereq`, `preflight`, `token` | [owner prerequisites](owner-prerequisites.md), [operations](operations.md); `token mint` writes a file, never stdout |

Flags `--application`, `--url`, `--json`, `--wait` and `--request-file` may precede or follow
subcommands; `MISSION_CONTROL_APPLICATION_ID`, `MISSION_CONTROL_URL` and `MISSION_CONTROL_TOKEN` are the
inputs; HTTP is allowed only to loopback. Exit codes (`cli/exits.py`): 0 success, 2 invalid
(400/404/413/422), 3 denied (401/403), 4 conflict, 5 unavailable, 6 wait timeout or blocked terminal result.

## MCP

Two servers share one tool family (`register_scoped_tools`, `mcp/coordinator_server.py:574`).

- **Coordinator server** (`coordinator_server.py`, FastMCP Streamable HTTP, local runner `__main__.py`):
  catalog and launch facade (`coordinator_bootstrap`, `search_capabilities`, `get_capability`,
  `discover_mcp_servers`, `discover_agent_skills`, `inspect_external_candidate`, `validate_workflow_design`,
  `prepare_workflow_launch`, `launch_workflow`, `get_workflow_result`) plus the scoped tools.
- **Operator server** (`operator_server.py`, `/v1/applications/{application_id}/mcp` on the configured API):
  the scoped tools without the catalog facade or `mission_subscribe`.
- **Scoped tool families:** manifests and chains (`mission_preflight`, `mission_manifest_compile\|submit`,
  `mission_run_start`, `mission_chain_inspect`); run control (`mission_command_send`, `mission_run_inspect`,
  `mission_run_fork`); transcript (`mission_run_transcript\|search\|list`); cognition points
  (`mission_run_points`, `mission_run_state_as_of`, `mission_run_points_reconcile`, `mission_run_point_frames`,
  `mission_run_replay`); selection (`mission_search`, `selection_check`); human tasks
  (`mission_human_task_list\|get\|resolve`); governed effects (`mission_governed_prepare\|execute\|status`,
  `mission_approval_resolve`); inbox and outputs (`coordinator_inbox_*`, `mission_run_outputs`,
  `mission_run_output_revisions\|events`, `mission_transfer_plan`); `knowledge_review`; `signal_emit` on the
  Signal Ingress. Resources use `belllabs://` and `mc://applications/{application_id}/...`.
- `coordinator_auth.py` derives the principal only from FastMCP's verified token; ADR-0015 requires
  resource-bound OAuth with PKCE and forbids forwarding application JWTs, but no authorization-server
  discovery or OAuth adapter exists in `interfaces/mcp`: the server trusts the token FastMCP presents.

## Scopes and errors

Implemented grants are `workflow_run.*` names (`admit`, `start`, `read`, `pause`, `resume`, `cancel`,
`admin`, `reconcile_unit`, `relay`, budget and effect actions; `ROLE_PERMISSIONS` in
`interfaces/http/run_control.py`) plus `catalog.read`. Manifest submit accepts `workflow_run.admit` or
`mission.author`; start accepts `workflow_run.start` or `mission.start`; subscribing needs
`workflow_run.read`. HTTP errors are FastAPI `detail: {code, message}` with lower-case codes
(`unauthorized`, `stale_version`, `stale_generation`, `resource_not_found`, `request_conflict`,
`idempotency_key_mismatch`, `unsupported_control`, `installation_unavailable`) mapped to 403, 409, 404, 422
and 503 in `interfaces/http/mission_control.py`; the coordinator uses upper-case codes
(`domain/coordinator/errors.py`) and the socket uses `mc.stream_subscription.v1` codes.

## Not built

`GET /system` and `system describe`, `POST /context:select`, mission drafting and proposals
(`mission_create`, `mission_proposal_create`, `mission_revision_activate`), interviews and stream
tickets, `auth login`, `run retry|replay` (apart from `replay --dry-run`), `recovery get`, `--tenant`,
and a single unified error envelope (the cross-surface error contract is the parked fault-tolerance
proposal, `docs/specs/fault-tolerance-2026-10/`). The HTTP inventory is hand-maintained; generating it
from `bootstrap/api.py` is scheduled with the SDLC navigation slices.

Built / specified / goal: all routers, CLI groups and MCP tools above are implemented; the inventory is
tested (`tests/unit/mission_control/test_public_interfaces.py`) and the authenticated scoped runtime is
integrated locally; OAuth for remote MCP and the dashboard control plane are goals.

## Citations

- ADR: [0015](../adr/0015-remote-mcp-oauth-no-jwt-forwarding.md).
- Code: [configured API](../../src/mission_control/bootstrap/api.py),
  [technical facade](../../src/mission_control/bootstrap/technical_api.py),
  [scoped router](../../src/mission_control/interfaces/http/mission_control.py),
  [ingress](../../src/mission_control/interfaces/http/ingress.py),
  [cognition points](../../src/mission_control/interfaces/http/cognition_points.py),
  [artifacts](../../src/mission_control/interfaces/http/artifacts.py),
  [run evidence](../../src/mission_control/interfaces/http/run_evidence.py),
  [coordinator inbox](../../src/mission_control/interfaces/http/coordinator_inbox.py),
  [output inspection](../../src/mission_control/interfaces/http/output_inspection.py),
  [knowledge reviews](../../src/mission_control/interfaces/http/knowledge_reviews.py),
  [run control grants](../../src/mission_control/interfaces/http/run_control.py),
  [CLI](../../src/mission_control/interfaces/cli/main.py), [exit codes](../../src/mission_control/interfaces/cli/exits.py),
  [coordinator MCP](../../src/mission_control/interfaces/mcp/coordinator_server.py),
  [operator MCP](../../src/mission_control/interfaces/mcp/operator_server.py),
  [MCP auth](../../src/mission_control/interfaces/mcp/coordinator_auth.py),
  [realtime entrypoint](../../src/mission_control/bootstrap/realtime.py).
- Tests: [public interfaces](../../tests/unit/mission_control/test_public_interfaces.py),
  [manifest interfaces](../../tests/unit/authoring/test_manifest_interfaces.py),
  [chain interfaces](../../tests/unit/chains/test_chain_interfaces.py),
  [transcript interfaces](../../tests/unit/frames/test_transcript_interfaces.py),
  [catalog CLI](../../tests/unit/capability/test_catalog_cli.py),
  [Human Task interfaces](../../tests/unit/human_tasks/test_human_task_interfaces.py),
  [MCP HTTP deployment](../../tests/unit/coordinator/test_coordinator_mcp_http_deployment.py),
  [authenticated scoped runtime](../../tests/acceptance/mission_control/test_authenticated_scoped_runtime.py).
- History: [fast-track SPEC-05](../specs/archive/fast-track-2026-10/SPEC-05-mission-manifest.md),
  [SPEC-06](../specs/archive/fast-track-2026-10/SPEC-06-interventions-inspection-subscriptions.md).
