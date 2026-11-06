<!-- BEGIN:sdlc-module id=interfaces.http -->
# HTTP routes
Typed application-scoped HTTP operations. Covers mission manifest verbs, run control and forks, runtime inspection, transcript and artifacts, catalog, subscriptions, signal ingress, human tasks, selection and model profiles.
Entrypoints:
- ingress.py — Signal Ingress routes /v1/ingress/{app}/...
- coordinator_inbox.py — Coordinator inbox over HTTP
- run_control.py
- mission_control.py — Application-scoped Mission Control HTTP transport
- cognition_points.py — Cognition points over HTTP
- artifacts.py — Artifact and frame-body download over HTTP
- output_inspection.py — Exact output, fulfillment and transfer inspection over HTTP
- transcript.py — Run Transcript over HTTP
- run_forks.py — /run-control/v1: safe macro snapshots and semantic forks
- missions.py — Mission Manifest verbs over HTTP
Also: catalog.py, subscriptions.py, human_tasks.py, run_evidence.py, knowledge_reviews.py, lanes.py, hook_callback.py, chains.py, models.py, selection.py, stop_fence.py, control_plane.py, runtime_inspection.py, graph_runtime_schemas.py, continuation.py, middleware/, dependencies.py
Tests: tests/unit/mission_control/test_public_interfaces.py, tests/unit/mission_control/test_runtime_interfaces.py, tests/unit/frames, tests/unit/run_control
Invariants:
- Keep replay response semantics and structured rejection codes explicit.
Explained by (docs/knowledge): interfaces, coordinator-attention, events-and-commands, provider-frames-and-transcript, budgets-and-usage, capabilities
Decided by (docs/adr): ADR-0054, ADR-0004, ADR-0008, ADR-0011, ADR-0013
Depends on: application, domain, adapters.postgres, contracts, domain.execution, application.authoring (+9) · Used by: bootstrap, adapters.agent_server, interfaces.mcp
Verify: uv run pytest tests/unit/mission_control
<!-- END:sdlc-module -->
