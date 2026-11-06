# Temporal execution mechanics

workflows/mission_run.py implements mc.mission_run.v1 using the governed root;
workflows/stagegraph.py and goal_directed.py reconcile family decisions;
workflows/operation.py implements mc.operation.v1 bounded operation execution.
Registration, activities and task queues must remain mutually consistent.

Workflow code must be deterministic. Activities call application services.
Validate family scope/run/ERC/type/epoch against the root before dispatch.
Scoped child IDs cannot collide across installations, applications or tenants.
Linked independent roots preserve admitted parent lineage.

Submission replay verifies actual first-history input before issuing a receipt.
Check tests/unit/mission_control/test_temporal_identities.py and real replay in
tests/acceptance/mission_control. Do not certify historic captures from new-run tests.

<!-- BEGIN:sdlc-module id=adapters.temporal -->
## Temporal execution mechanics
Workflows and activities: mission_run, stagegraph, goal_directed, operation. Also the Temporal client, search attributes, visibility, worker versioning and the production lane composition factories.
Entrypoints:
- workflows/ — Canonical BellLabs Temporal workflow owners
- activities/ — Idempotent application-service adapters used by Temporal workflows
- deployment_composition.py — The deployment WorkerActivityCompositionFactory
- hosted_lane_composition.py — Production hosted lanes: exact projection, durable approvals, scoped signals and…
- provider_lane_composition.py — Production composition of the local provider lanes and their native approvals
- worker.py
- reaction_dispatch.py — Start a reaction's ordinary operation workflow on Temporal
Also: boundary_commands.py, versioning.py, watcher_composition.py, watcher_starter.py, closed_workflow.py, linked_run_workflow.py, coordinator_runtime.py, pending_family_inputs.py, operation_activities.py, search_attributes.py, submission.py, orchestration_activities.py, registration/ (+17)
Tests: tests/unit/temporal, tests/unit/runtime, tests/integration/temporal, tests/acceptance/mission_control
Invariants:
- Workflow code is deterministic; activities call application services.
- Scoped child IDs cannot collide across installations, applications or tenants.
- Submission replay verifies the actual first-history input before issuing a receipt.
Explained by (docs/knowledge): temporal-synthesis, watchers, lanes-and-harness, session-ownership-and-dispatch, provider-batch, context-and-continuation
Decided by (docs/adr): ADR-0004, ADR-0008, ADR-0031, ADR-0041, ADR-0005
Depends on: application, adapters.postgres, domain.programs, domain.execution, domain, bootstrap (+12) · Used by: bootstrap, adapters.postgres
Verify: uv run pytest tests/unit/temporal tests/unit/runtime; uv run pytest tests/integration/temporal (needs real Temporal and PostgreSQL)
<!-- END:sdlc-module -->
