<!-- BEGIN:sdlc-module id=domain.programs -->
# Workflow family interpretation
Pure Stage Graph and GoalDirected interpretation; interpreters propose only. Covers routes, dependencies, payload bounds, completion evidence, watchers, Human Gates and recursive composition rules; they never terminalize a run.
Entrypoints:
- contracts.py
- interpreter.py
- goal_directed.py
- human_review.py — GoalDirected human review: a bounded review control action after verified completion
- watchers.py — Watchers: declared, bounded, deterministic reactions to observed facts
- human_gate.py — Human Gate control activations over the common Human Task rows
- goal_directed_runtime.py
- watcher_conditions.py — Watcher conditions: the closed expression AST of ADR-0010 over observed facts
- nested.py — Recursive composition at runtime: activation, exact export and control lineage
- routing.py — Pure evaluation of explicit Stage Graph routes and named release groups
Also: stagegraph_bounds.py, dependencies.py, search_attributes.py, bindings.py, family_failure.py, runtime_units.py, completion.py
Tests: tests/unit/orchestration, tests/unit/watchers, tests/unit/run_control
Invariants:
- Do not turn an interpreter proposal into an authoritative lifecycle change.
- Deterministic and free of I/O imports.
Explained by (docs/knowledge): goal-loop, stage-graph, workflow-systems, evaluator-optimizer, human-gates, parallel-swarm
Decided by (docs/adr): ADR-0068, ADR-0010, ADR-0011, ADR-0029, ADR-0038
Depends on: domain.authoring, domain.execution, contracts · Used by: adapters.temporal, application.programs, application, adapters.postgres, application.authoring, domain.authoring (+8)
Verify: uv run pytest tests/unit/orchestration tests/unit/watchers tests/architecture
<!-- END:sdlc-module -->
