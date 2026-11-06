<!-- BEGIN:sdlc-module id=domain.authoring -->
# Authoring domain
Mission Manifest, MissionDefinition@1, Environment Kits and the compiler. Covers manifest v1 and v2 (YAML) lowered to immutable definitions; the package root re-exports lazily so a leaf module does not load the compiler.
Entrypoints:
- contracts.py
- manifest_lowering.py — Lowering MissionDefinition@1 onto the existing compiler inputs
- manifest.py — Mission Manifest v1: the YAML authoring surface
- manifest_v2.py — Mission Manifest v2: the multi-provider authoring surface
- mission_definition.py — MissionDefinition@1: the typed definition a Mission Manifest lowers to
- graph_routes.py — Compiled Stage Graph routes, named release groups and typed stage facts
- compiler.py
- mission_environment.py — The mission/v2 environment additions: Environment Kit pin, variables, secrets…
- environment_kits.py — Environment Kits and the mission layer they render
- mission_watchers.py — A mission's watchers: controls.watchers, controls.notifications and event_wait…
Also: provider_options.py, stagegraph_builder.py, canonical.py, nested_lowering.py, fixtures.py, nested_bodies.py, extensions.py, errors.py, identity.py
Tests: tests/unit/authoring, tests/unit/chains, tests/unit/control_plane
Invariants:
- Definitions are immutable once compiled; identifiers derive from the parts that identify a record.
Explained by (docs/knowledge): mission-manifest, environments, stage-graph, evaluator-optimizer, parallel-swarm, revisions
Decided by (docs/adr): ADR-0068, ADR-0010, ADR-0022, ADR-0034, ADR-0063
Depends on: domain.programs, domain.execution · Used by: application, application.authoring, adapters.postgres, application.programs, adapters.deep_agents, domain.execution (+16)
Verify: uv run pytest tests/unit/authoring tests/unit/chains
<!-- END:sdlc-module -->
