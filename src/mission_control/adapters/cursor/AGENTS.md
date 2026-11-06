<!-- BEGIN:sdlc-module id=adapters.cursor -->
# Cursor lane family
Cursor lane family (ADR-0030): cursor_local and cursor_cloud. Local uses the pinned SDK bridge, git worktree leases and fail-closed Kernel Hooks; cloud uses Cloud Agents API v1 with SCM branches; both map frames and reconcile billed cost.
Entrypoints:
- cloud.py — The cursor_cloud Lane Profile: Cursor Cloud Agents API v1
- local.py — The cursor_local Lane Profile: Cursor's Python SDK bridge on the worker
- controls.py — Cursor continuation: workspace snapshots and the fresh-agent hydrators
- snapshot.py — Emulated snapshot and its restore for cursor_local
- time_travel.py — Cursor time travel: read_as_of, seed_fork and collect_points over the persisted…
- bridge.py — The Cursor local bridge behind a port
Also: environments.py, workspace.py, hooks_callback.py, qualification.py, scm.py, cloud_api.py, frames.py, kernel_hook_script.py, projection.py, describe.py, bridge_spawn.py, cognition_points.py, secrets.py, cost.py, host_files.py, bridge_recovery.py, costs.py, usage.py, discovery.py (+4)
Tests: tests/unit/cursor, tests/integration/cursor, tests/unit/harness
Invariants:
- Importing this package imports no SDK; the SDK loads lazily inside the bridge adapter.
Explained by (docs/knowledge): cursor-lane, instruction-layering, context-and-continuation, cross-provider-control, environment-preparation, recovery
Decided by (docs/adr): ADR-0007, ADR-0018, ADR-0019, ADR-0027, ADR-0030
Depends on: application, domain.execution, domain, application.environments, domain.authoring, domain.frames (+1) · Used by: adapters.temporal, bootstrap, adapters.codex, adapters.postgres, adapters.claude, adapters.deep_agents (+1)
Verify: uv run pytest tests/unit/cursor tests/unit/harness; uv run pytest tests/integration/cursor (paid provider calls need authorization)
Program: docs/specs/provider-consolidation-2026-10/LEDGER.md
<!-- END:sdlc-module -->
