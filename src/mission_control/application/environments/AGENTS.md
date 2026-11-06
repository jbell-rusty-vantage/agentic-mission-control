<!-- BEGIN:sdlc-module id=application.environments -->
# Execution environments
Environment resolution, preparation gate and network projection. Resolves an environment request into mc.environment_binding.v1 and attests it; also owns preparation records, Environment Kits and hosted provider environments.
Entrypoints:
- network.py — Per-lane projection of a resolved network policy
- preparation.py — Environment preparation records and the launch readiness gate
- provider_environments.py — Provider environments of hosted lanes: the committed-file check, sync and bind
- discovery.py — Discovery Proof per lane
- mission_layer.py — The mission layer of a local lane: render, deliver, run and read back
- requirements.py — The readiness each node role of a mission must reach before its session starts
- kits.py — Environment Kits read from the catalog, and the compile-time environment inputs
- resolver.py — Resolve an execution-environment request into mc.environment_binding.v1 and attest…
- bootstrap.py — Per-profile evidence for how mandatory configuration reaches a session before it…
Tests: tests/unit/agentic_components/test_environments.py, tests/unit/agentic_components/test_environment_preparation.py, tests/unit/agentic_components/test_network_policy.py, tests/unit/capability/test_environment_kits.py, tests/integration/postgres/test_environment_preparation.py
Explained by (docs/knowledge): environment-preparation, deep-agents-lane, environments
Decided by (docs/adr): ADR-0005, ADR-0006, ADR-0017, ADR-0042
Depends on: domain.execution, domain, domain.authoring, domain.frames · Used by: adapters.cursor, adapters.temporal, adapters.claude, adapters.codex, adapters, application.authoring (+1)
Verify: uv run pytest tests/unit/agentic_components tests/unit/capability/test_environment_kits.py
Program: docs/specs/provider-consolidation-2026-10/LEDGER.md
<!-- END:sdlc-module -->
