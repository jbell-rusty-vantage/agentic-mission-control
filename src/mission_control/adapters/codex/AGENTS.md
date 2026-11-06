<!-- BEGIN:sdlc-module id=adapters.codex -->
# Codex lane
The codex lane: Codex app-server over stdio on a worker. Covers the typed JSON-RPC protocol subset, transport, subprocess launcher, approvals over the broker, frame mapping, hook trust and continuation.
Entrypoints:
- harness.py — The codex Lane Profile: Codex app-server threads, turns and items on the worker
- time_travel.py — Codex time travel: read_as_of, seed_fork and collect_points over thread_item points
- approvals.py — Codex approval and user-input server requests over MP-11's ApprovalBroker
- describe.py — The Codex lane family's declared describe matrices and declarations
- launcher.py — Launching codex app-server as a worker subprocess with an allowlisted environment
- continuation.py — codex continuation: workspace snapshots and the fresh-thread hydrator
- protocol.py — The typed subset of the Codex app-server protocol v2 the lane speaks
- frames.py — App-server events to LaneFrames and closing facts
- transport.py — JSON-RPC connection to a Codex app-server with separated correlation
- cognition_points.py — Codex cognition points: one thread_item point per step boundary of a native turn
Also: host_files.py, hook_trust.py, usage.py, hooks_callback.py, compose.py, discovery.py, hook_output.py, auth_preflight.py, lane.py
Tests: tests/unit/codex, tests/integration/codex, tests/unit/harness
Invariants:
- Nothing here logs in, starts a model turn on its own or reads a credential value.
Explained by (docs/knowledge): provider-lanes, cross-provider-control, instruction-layering
Decided by (docs/adr): ADR-0035, ADR-0038, ADR-0041, ADR-0044, ADR-0069
Depends on: application, domain.execution, domain, domain.frames, application.environments, adapters.cursor (+2) · Used by: adapters.temporal, bootstrap, application
Verify: uv run pytest tests/unit/codex tests/unit/harness; uv run pytest tests/integration/codex (paid provider calls need authorization)
Program: docs/specs/provider-consolidation-2026-10/LEDGER.md
<!-- END:sdlc-module -->
