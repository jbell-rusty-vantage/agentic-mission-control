<!-- BEGIN:sdlc-module id=application.programs -->
# Family orchestration use cases
Stage Graph and GoalDirected orchestration use cases over persisted authority. Covers the orchestration service, named-output settlement, completion validation, linked runs, nested bodies, Human Gate wiring and fork templates.
Entrypoints:
- goal_directed.py
- fork_templates.py — Derive a fork's StageGraph operation templates from the source run's
- service.py
- human_gates.py — Human Gate wiring for the program families
- goal_context.py — Validate host-selected Goal subjects and deliver complete persisted verifier…
- linked_context.py — Freeze released linked exports in the ordinary provider-neutral operation binding
- linked_runs.py
- nested_launch.py — Production composition of recursive composition: the launcher and its adapters
- nested_bodies.py — Recursive composition use cases: activate, settle and control nested bodies
- artifact_validation.py — Bounded, offline validation of captured output bytes against frozen schemas
Also: completion_validation.py, orchestration_routing.py, named_outputs.py, route_facts.py, orchestration_binding_repository.py, control_admission.py, stage_inputs.py
Tests: tests/unit/orchestration, tests/unit/run_control, tests/unit/outputs, tests/integration/postgres
Explained by (docs/knowledge): goal-loop, stage-graph, completion, evaluator-optimizer, human-gates, mission-chains
Decided by (docs/adr): ADR-0010, ADR-0004, ADR-0029, ADR-0034, ADR-0038
Depends on: domain, domain.programs, domain.authoring, domain.execution, application.authoring · Used by: adapters.temporal, bootstrap, application.authoring, adapters.postgres, application.missions, application.recovery
Verify: uv run pytest tests/unit/orchestration tests/unit/run_control
<!-- END:sdlc-module -->
