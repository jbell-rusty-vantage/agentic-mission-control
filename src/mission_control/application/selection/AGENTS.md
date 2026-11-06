<!-- BEGIN:sdlc-module id=application.selection -->
# Selection Workspace
The Selection Workspace: faceted search and read-only draft check. One search and one read-only check of a draft lane, model and capability selection.
Entrypoints:
- workspace.py — The Selection Workspace: one search and one read-only check over a draft selection
Tests: tests/unit/selection
Invariants:
- The check is read-only; it never writes selection state.
Explained by (docs/knowledge): selection-workspace
Decided by (docs/adr): ADR-0013, ADR-0025, ADR-0063
Depends on: domain, domain.execution, application.authoring, domain.authoring · Used by: bootstrap, interfaces.http, interfaces.mcp
Verify: uv run pytest tests/unit/selection
Program: docs/specs/provider-consolidation-2026-10/LEDGER.md
<!-- END:sdlc-module -->
