<!-- BEGIN:sdlc-module id=interfaces.mcp -->
# MCP servers
Coordinator and operator MCP servers and the governed gateway. Tools cover mission, run-control, transcript, selection, human-task, cognition-point and signal operations, inbox and subscriptions; the gateway fronts Mission-Control-owned effect tools.
Entrypoints:
- coordinator_server.py
- operator_server.py — The authenticated operator MCP surface of the configured API
- subscriptions.py — MCP subscriptions: the coordinator inbox tools and the deprecated mission_subscribe
- mission_tools.py — Mission authoring and chain tools on the coordinator MCP server
- governed_gateway.py — Governed MCP gateway for Mission-Control-owned effect tools
- human_task_tools.py — Human Tasks on the coordinator MCP server
- signal_tools.py — signal_emit: the MCP mirror of mc-signal
- coordinator_auth.py
- coordinator_resources.py
- coordinator_prompts.py
Also: cognition_point_tools.py, transcript_tools.py, run_control_tools.py, governed_elicitation.py, coordinator_http_client.py, selection_tools.py, knowledge_review_tools.py, coordinator_bootstrap.py
Tests: tests/unit/coordinator, tests/unit/subscriptions
Explained by (docs/knowledge): authoring, interfaces, coordinator-surface, human-gates, wake-channels, coordinator-attention
Decided by (docs/adr): ADR-0015, ADR-0049, ADR-0040, ADR-0022, ADR-0032
Depends on: application, domain, adapters.postgres, contracts, bootstrap, application.authoring (+9) · Used by: bootstrap
Verify: uv run pytest tests/unit/coordinator tests/unit/subscriptions
Program: docs/specs/coordinator-surface-2026-10/LEDGER.md
<!-- END:sdlc-module -->
