<!-- BEGIN:sdlc-module id=agent_server_deployment -->
# Agent Server deployment config
LangGraph Agent Server deployment config. langgraph.json maps graph ids to mission_control.adapters.agent_server entrypoints and names the auth and http app; runtime.env carries the server environment. The code lives in src/mission_control/adapters/agent_server.
Entrypoints:
- runtime.env
- langgraph.json
Tests: tests/unit/agent_server/test_canonical_deployment.py, tests/integration/agent_server
Verify: uv run pytest tests/unit/agent_server/test_canonical_deployment.py
<!-- END:sdlc-module -->
