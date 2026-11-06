<!-- BEGIN:sdlc-module id=adapters.claude -->
# Claude Agent SDK lane
The local claude_agent_sdk lane. Covers the single session stream owner, the SDK client factory, message-to-frame mapping, Kernel Hooks as in-process callbacks, permission bindings to the approval broker, workspace and continuation.
Entrypoints:
- harness.py — The claude_agent_sdk Lane Profile: the Python Claude Agent SDK on the worker
- time_travel.py — Claude Agent SDK time travel: read_as_of, seed_fork and collect_points over…
- describe.py — The Claude lane family's declared describe matrices and declarations
- continuation.py — claude_agent_sdk continuation: workspace snapshots and the fresh-session hydrator
- approvals.py — PermissionBindingPort over MP-11's durable ApprovalBroker
- session.py — One live Claude Agent SDK session: the single stream owner and its frame log
- workspace.py — The leased workspace and the local session state root of a Claude session
- transport.py — The production client factory: ClaudeSDKClient over an explicit child environment
- permissions.py — Native permission requests bound to mc.approval_binding.v1
Also: cognition_points.py, hooks.py, frames.py, host_files.py, compose.py, host.py, hook_output.py, discovery.py, lane.py
Tests: tests/unit/claude, tests/integration/claude, tests/unit/harness
Invariants:
- Exports load lazily so the describe aggregator can read describe without importing the harness.
Explained by (docs/knowledge): provider-lanes, cross-provider-control, instruction-layering
Decided by (docs/adr): ADR-0035, ADR-0038, ADR-0041, ADR-0044, ADR-0069
Depends on: application, domain.execution, domain, domain.frames, application.environments, domain.authoring (+1) · Used by: adapters.temporal, bootstrap, application
Verify: uv run pytest tests/unit/claude tests/unit/harness; uv run pytest tests/integration/claude (paid provider calls need authorization)
Program: docs/specs/provider-consolidation-2026-10/LEDGER.md
<!-- END:sdlc-module -->
