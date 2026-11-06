<!-- BEGIN:sdlc-module id=adapters.agent_server -->
# Agent Server hosting
Hosts the bounded LangGraph graphs of the Agent Server (ADR-0006). Covers the graph registry, entrypoints for subordinate and async child graphs, deployment-selected topology, authentication, health and tracing.
Entrypoints:
- async_subagents/ — Hosted async subagent graphs for the dedicated BellLabs Agent Server
- deployment_auth.py — One authentication entrypoint; scoped credentials never choose server topology
- block_c_qualification/ — Disposable pre-Stage-3 Block C Agent Server qualification package
- client.py
- auth.py
- http_app.py
- reducers.py
- bootstrap.py
- tracing.py
- common_state.py — Compact graph checkpoint state; durable bodies remain behind references
Also: deployment.py, context.py, health.py, hosting.py, entrypoints.py, graph_factory.py, runtime_composition.py, common.py, qualification/, graphs.py, operations/
Tests: tests/unit/agent_server, tests/integration/agent_server
Invariants:
- Entrypoints are bounded graphs; Temporal alone schedules missions.
- Topology is selected by the server deployment, never by a request.
Explained by (docs/knowledge): deep-agents-children
Decided by (docs/adr): ADR-0006, ADR-0058
Depends on: domain, domain.execution, adapters.deep_agents, application.recovery, bootstrap, adapters.postgres (+3) · Used by: interfaces.http, adapters.deep_agents, interfaces.cli
Verify: uv run pytest tests/unit/agent_server; uv run pytest tests/integration/agent_server (needs the local Agent Server)
<!-- END:sdlc-module -->
