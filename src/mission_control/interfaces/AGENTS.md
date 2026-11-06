# Public transport

http exposes typed application-scoped operations; cli uses the public client;
mcp exposes bounded transport capabilities. Interfaces call application handlers
rather than implementing a second lifecycle reducer or scheduler.

Authenticate before resolving scoped services. Verify service scope against the
trusted installation/application/tenant. Request fields and user-editable token
metadata cannot select pools, grants, bootstrap factories or provider credentials.
Keep replay response semantics and structured rejection codes explicit.

Start with tests/unit/mission_control/test_public_interfaces.py and
test_authentication.py; authenticated runtime proof is
tests/acceptance/mission_control/test_authenticated_scoped_runtime.py.

<!-- BEGIN:sdlc-module id=interfaces -->
## Public transport
Transport only: http, cli, mcp and socketio. They call application handlers and never implement a second lifecycle reducer or scheduler.
Entrypoints:
- http/ — HTTP adapters
- mcp/
- cli/ — Scoped HTTP client for the Mission Control facade
- socketio/
Tests: tests/unit/mission_control/test_public_interfaces.py, tests/unit/mission_control/test_authentication.py, tests/acceptance/mission_control/test_authenticated_scoped_runtime.py
Invariants:
- Authenticate before resolving scoped services; verify scope against the trusted installation, application and tenant.
- Request fields and token metadata cannot select pools, grants, bootstrap factories or provider credentials.
Explained by (docs/knowledge): mission-stream
Decided by (docs/adr): ADR-0036, ADR-0040
Depends on: application, contracts, domain, application.missions, domain.programs · Used by: bootstrap
Verify: uv run pytest tests/unit/mission_control
<!-- END:sdlc-module -->
