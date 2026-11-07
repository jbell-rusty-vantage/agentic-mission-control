# Trusted composition and startup

api.py is the configured FastAPI factory; worker.py selects the app-bound Temporal
worker; preflight.py performs read-only readiness; common_installation.py verifies
the installed common release; composition.py wires actual repositories and
application services. technical_api.py retains optional lower-level
authoring/control/realtime proof surfaces; api.py remains the configured public
entrypoint. Both use the same handlers and engine. application_profiles.py loads the
installation's `deployments/<app>/application.toml` (OC-R4); bootstrap passes the application
id explicitly and never discovers profiles or names an application in code.

Validate binding digests, actual persisted installation identity, the attested
release and fingerprint, restricted roles and configured queues before readiness. Startup never invents
catalog definitions or policy grants, migrates schema or fetches token-supplied keys.
MISSION_CONTROL_HOME defaults to the current working directory for operator assets;
do not resolve deployment secrets from the installed wheel location.

storage_mode is production_common only; missing or mismatched evidence fails
closed with no transitional fallback. Test real startup with restricted PostgreSQL
pools and signed identity. Operator guide: docs/MISSION_CONTROL_LOCAL_API.md.

<!-- BEGIN:sdlc-module id=bootstrap -->
## Trusted composition and startup
Trusted startup and composition. Covers the API and worker factories, read-only preflight, the common-release check and the wiring of repositories and services; bootstrap passes the application id explicitly and never discovers profiles.
Entrypoints:
- api.py — Configured scoped API: uvicorn mission_control.bootstrap.api:create_app --factory…
- realtime.py — Public API plus the /missions Socket.IO namespace
- preflight.py — Read-only validation of the configured Mission Control installation
- settings.py
- composition.py — Concrete per-installation PostgreSQL composition over the common component
- manifests.py — Composition of the Mission Manifest service
Also: common_installation.py, subscriptions.py, worker.py, ingress_drainer.py, owner_probe.py, technical_api.py, trusted_judgment.py, application_profiles.py, provider_auth.py, hosted_readonly.py, resolution.py, model_profiles.py, selection.py, session_time_travel.py, host_preflight.py, runners/ (+23)
Tests: tests/unit/mission_control, tests/unit/prerequisites, tests/integration/postgres/test_mission_control_composition_postgres.py
Invariants:
- storage_mode is production_common only; missing or mismatched evidence fails closed with no transitional fallback.
- Startup never migrates schema, invents catalog definitions or policy grants, or fetches token-supplied keys.
Explained by (docs/knowledge): operations, interfaces, application-profile, owner-probe-bootstrap, persistence, wake-channels
Decided by (docs/adr): ADR-0002, ADR-0003, ADR-0009, ADR-0015, ADR-0017
Depends on: application, adapters.postgres, adapters.temporal, adapters, interfaces.http, adapters.deep_agents (+17) · Used by: adapters.temporal, interfaces.mcp, adapters, adapters.agent_server, interfaces.http, adapters.capabilities (+1)
Verify: uv run pytest tests/unit/mission_control; make preflight (read-only installation check)
<!-- END:sdlc-module -->
