<!-- BEGIN:sdlc-module id=interfaces.cli -->
# missionctl CLI
missionctl: a thin authenticated client, never a second lifecycle authority. Works over the public HTTP surface; includes wait and inbox, outputs, selection, knowledge review, setup and token helpers.
Entrypoints:
- main.py — missionctl: a thin authenticated client, never a second lifecycle authority
- wait.py — missionctl wait and missionctl inbox: the W1 wake channel
- outputs.py — missionctl outputs: exact output, fulfillment and transfer inspection
- exits.py — missionctl exit codes: 0 success, 2 invalid, 3 denied, 4 conflict, 5 unavailable…
- setup.py — Render the repository wizard pattern; credentials remain in provider/broker UIs
- selection.py — missionctl search and missionctl workspace check: the Selection Workspace
- knowledge.py — missionctl knowledge review: an operator's review of one exact KS use decision
- token.py — Local token helper
Tests: tests/unit/run_control/test_cli_command_cancel.py, tests/unit/capability/test_catalog_cli.py, tests/unit/prerequisites/test_bootstrap_cli.py
Invariants:
- Credentials are written to a new file, never to standard output.
Explained by (docs/knowledge): coordinator-surface, interfaces, coordinator-attention, precise-fork, wake-channels
Decided by (docs/adr): ADR-0049, ADR-0015, ADR-0040, ADR-0032, ADR-0033
Depends on: domain, adapters, application, contracts, adapters.agent_server, domain.authoring
Verify: uv run pytest tests/unit/run_control/test_cli_command_cancel.py tests/unit/capability/test_catalog_cli.py
<!-- END:sdlc-module -->
