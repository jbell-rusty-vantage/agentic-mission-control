---
type: Concept
category: surfaces
title: Signal Ingress
description: "How signals, gates, provider webhooks, artifact uploads and remote launch requests enter Mission Control - five trust tiers verified at the edge, one SECURITY DEFINER call per request into migration 0035's tables, the gate computed in SQL with the intent before allow, the inbox row contract the worker's IngressDrainer consumes (MO-40, proposed ADR-0045), and the Telemetry Hook Pack and signal_emit that send to it from inside an environment (MO-41)."
tags: [mission-control, ingress, observation, security, persistence, implementation]
aliases: [webhooks, trust tiers, ingress inbox, Vercel ingress edge]
questions:
  - How do external signals and webhooks enter Mission Control?
  - Which trust tier verifies this signal and what can it do?
  - Is the Vercel ingress deployed and what is proven?
updated: 2026-11-01
---

# Signal Ingress

Provider VMs, hooks and webhooks use Signal Ingress ([ADR-0045](../adr/0045-signal-ingress-trust-tiers-signals-are-evidence-never-authority.md),
[SPEC-10](../specs/archive/materialization-observation-2026-10/SPEC-10-ingress-on-vercel.md)). The edge verifies
and records; SQL decides; the worker acts. Signals are evidence, never authority.

## Where the code is

Verification (bearer, derived secrets, environment-key HMAC, Standard Webhooks, GitHub and Cursor v0 HMAC)
is `application/signals/verification.py`; provider wakes `wake.py`; ports `ports.py`; routes
`interfaces/http/ingress.py` and `hook_callback.py`; tables, guards, role and functions
`packages/mission-control-db-contract/component/migrations/0035_signal_ingress.sql`.

## Routes and tiers

| Route | Tiers | Reply |
| --- | --- | --- |
| `POST signals` (one `mc.signal.v1` or `{"signals": [...]}`, at most 100) | `run_token`, `provider_oidc`, `environment_key` | 202 `{accepted, duplicates}` |
| `POST signals?gate=1` (`mc.signal_gate.v1`) | `run_token`, `provider_oidc` | 200 `{decision: allow\|deny\|stop, reason}` |
| `POST artifacts:prepare` / `artifacts:commit` | `run_token`, `provider_oidc` | signed quarantine upload slot / 202 |
| `POST provider/anthropic`, `provider/openai`, `provider/cursor/{run_ref}`, `github` | `provider_signed` | 204, also for a duplicate |
| `POST missions:request` / `GET missions:request/{id}` | `launch_token` | 202 `{request_id}` / `queued`, `admitted` or `refused` |

A run or launch token is an `mct_` bearer looked up by digest (ADR-0043). A Cursor JWT names a
`cloud_agent_id` that the worker bound to a run generation at launch
(`PostgresSessionBindings.register`). An environment-key request carries `X-MC-Provider`,
`X-MC-Environment`, `X-MC-Session`, `X-MC-Timestamp` and `X-MC-Signature: v1=<hex>`; the key is
`derive_secret(master, "environment_key", "<app>/<provider>/<environment>")`, and the session is
bound once by the `session.started` signal whose `data.run_nonce` hashes to the registered nonce
digest (the nonce is removed before storage). The Cursor v0 webhook secret registered for a run
is the hex of `derive_secret(master, "cursor_webhook", "<app>/<run_ref>")`. The signature
covers the timestamp and body only, not `X-MC-Session`: anyone holding one environment's
derived key can post observations for any session already bound in that environment. The
tier never gates, uploads or launches, so this is accepted (ADR-0045).

Caps: 256 KiB per signal, gate or launch body, measured as SQL stores it (jsonb text, with a
space after every `:` and `,`), so an oversized payload is 413 `payload_too_large` at the edge
and in SQL; 1 MiB per batch or webhook; an oversized webhook keeps only its scalar top-level
fields. Rate limits are per credential, a fixed 60 s window (`signal_token` 600,
`mission_request` 30, session bindings 600 by default).

## Provider webhooks are wake signals

Managed Agents (`provider/anthropic`) and the Agents API (`provider/openai`) sign deliveries with Standard
Webhooks: HMAC-SHA256 over `webhook-id.webhook-timestamp.body`, any listed `v1,` signature matching, the
timestamp within ±300 s. A verified delivery is stored only as `mc.provider_wake.v1` (`{event_type,
resource_ref, event_id}`); status, URLs and usage are dropped; a missing type or id is 422 `invalid_body`.
Deduplication by `webhook-id` returns 204; forged or stale deliveries are 401 and reach no SQL. The worker
re-reads provider state through `RemoteSessionLane.wake_target`. Signed fixtures:
`tests/fixtures/provider_webhooks.py`; no provider webhook has been registered.

## The gate

`ingress_gate` answers in one transaction: a revoked credential or session answers `stop` (recorded only
within its rate window); under the Stop Fence's per-run advisory lock a covering fence answers `stop` and
records `STOP_FENCED` in `stop_fence_effect_admission`; a tool in the context's `disallowed_tools` answers
`deny`; a credential without `harness_execution_id` and a registered `lane_profile` answers `deny`
(`gate_context_missing`); otherwise `hook_effect_intent` is written before `allow`. A repeated `signal_id`
answers the recorded decision only when the body matches (else `dedupe_conflict`, 409). Each kind dedupes in
its own space (`dedupe_space`). An upload slot's storage key is `<app>/<run uuid>/<sha256 hex>/<upload id>`.

## Inbox row contract (for the IngressDrainer)

- **Wake:** `LISTEN mc_ingress`; the payload is `{"scope", "ingress_id", "kind"}` (scope
  `mc/<installation>/<application>/<tenant or empty>`). Poll every 5 s as the fallback.
- **Claim:** as `mission_control_runtime` under the binding's scope:
  `SELECT ... FROM mission_control.ingress_inbox WHERE state = 'pending' ORDER BY received_at,
  ingress_id FOR UPDATE SKIP LOCKED LIMIT 100`. Provider webhook rows have no tenant
  (`tenant_id IS NULL`) and are visible to every scope of the application.
- **Kinds:** `signal.<type>` and `gate.decision` become provider frames with `provider_key =
  ingress:<credential_ref>:<dedupe_space>:<dedupe_key>` (a replay is a no-op; a key is unique
  only within its space); `webhook.<provider>` wakes the
  lane's reconcile-from-history (`webhook.anthropic` and `webhook.openai` carry a
  `ProviderWake`); `artifact.committed` starts custody (`payload.storage_key`,
  `sha256`, `size_bytes`); `mission_request` is admitted through the API's admission handler
  (`payload.manifest_ref`, `inputs`, `inputs_digest`, `idempotency_key`).
- **Columns:** `trust_tier`, `credential_ref` (`credential:<id>`, `session:<id>`,
  `webhook:<provider>[:<run_ref>]`), `dedupe_space`, `dedupe_key`, `body_sha256` (of the redacted canonical
  payload), `payload`, `seq`, and the bound `run_key`, `unit_key`, `generation` (NULL for
  webhooks and launch requests).
- **Settle:** a `pending` row moves once: `drained` (optional `outcome`; a launch request records
  `{"mission_id": ...}`), `rejected` (`outcome.reason` required) or `dead`; `drained_at` is set
  exactly then. A retried failure only increments `attempts` and sets `last_error`. Nothing else
  changes and nothing is deleted (guard triggers; the runtime role has column-limited UPDATE).

## Telemetry Hook Pack (MO-41)

The senders inside an environment (SPEC-04 §4). `HostProjectors.render(..., telemetry=True)` places
on `cursor_local`, `cursor_cloud`, `codex`, `claude_cloud` and `codex_cloud`
(`application/agentic_components/telemetry.py`): `.mission/hooks/signal` (the stdlib script,
`signal_hook.py`), `.mission/bin/mc-signal` (a POSIX `sh` hand-off), `.mission/signal-policy.json`
and the `mc-signals` skill (`skills/mc-signals`, unless a catalog row places it). Its hook
entries follow §4.2 (`TELEMETRY_EVENTS`): `cursor_cloud` forwards `preToolUse`, `postToolUse`,
`subagentStart`/`Stop`, `afterAgentResponse`, `preCompact` and `stop`; `cursor_local` and `codex`
add `stop`/`subagent_stop` beside their Kernel Hooks (Codex trusts them as `mc.telemetry`);
`claude_cloud` forwards its session, shell and file-edit post-tool, compaction and stop events
asynchronously; `codex_cloud` gets no hooks, only the command, the skill and one advisory line.
`claude_agent_sdk`, Deep Agents and the hosted APIs get no pack. Every entry is fail-open and
follows the lane's Kernel and catalog hooks; on Cursor permission events it prints `allow`, which
never outweighs another hook's `deny` or `ask`. `telemetry=False` removes all of it.

The Python 3.8+ sender retains allowlisted scalar fields, never tool arguments/results. Its locked
`.mission/state/signals/` spool assigns increasing sequence numbers, opening with `session.started`
and `materialization.observed`. Batches have at most 100 signals; opening/terminal/manual events
flush immediately, others at 20 queued or 30 seconds. Backoff fits the 15-second hook timeout.
Invalid batches split; authentication failures retain the spool. Redirects are refused; HTTP is
loopback-only. `mc-signal` is a POSIX shell entrypoint.

`signal_emit` at `/v1/ingress/{app}/mcp` uses the request's own run bearer. The operator MCP
never forwards its bearer into an environment. Production API and local workers mount the
HTTP/MCP services only with an explicitly configured restricted ingress login
(`signal_ingress_secret_ref`); startup rejects privileged or table-reading credentials.
Local child processes receive a per-attempt minted token and trusted loopback URL. Superseded
generations are revoked. `environment.observation.in_environment: false` disables automatic
telemetry projection and delivery. Without configured ingress, local signals stay spooled.

Synchronous gates use `environment.observation.gates` with `before_tool`, `before_shell` or
`before_mcp`; `fail_closed` defaults true. SQL checks the Stop Fence and records the effect intent;
only a digest of tool input crosses ingress. Native deny/stop answers prevent further execution.
Remote gates require an explicit credential-free HTTPS `MISSION_CONTROL_SIGNAL_INGRESS_ORIGIN`,
a pinned egress policy admitting that host, and Cursor's per-run `envVars` create path
(`client_agent_id: false`). The same configured host feeds preflight and launch resolution.

## Deployment state and gaps

The `IngressDrainer` (`application/signals/drainer.py`) is composed in the worker
(`bootstrap/worker_ingress.py:168`; PostgreSQL proof
`tests/integration/postgres/test_run2_ingress_drainer_postgres.py`), the `missions:request` remote launch
route exists (`interfaces/http/ingress.py:130`), and the optional quarantine upload adapter is
`adapters/supabase_storage/ingress.py`. The edge is a separate Vercel project
(`deployments/ingress-vercel`) whose README records the repaired Run 2 deployment live, with startup,
liveness and unauthenticated refusal passing; accepted launches, callbacks, latency, artifact custody and
provider webhook registration are unqualified and need the owner's separate approval
([deployment](deployment.md)). Cursor OIDC acquisition needs deployment bindings.

Built / specified / goal: implemented and tested locally (PostgreSQL, loopback HTTP); edge deployed and
liveness-checked only; qualified: no.

## Citations

- History: [SPEC-10](../specs/archive/materialization-observation-2026-10/SPEC-10-ingress-on-vercel.md), [SPEC-06 §3](../specs/archive/materialization-observation-2026-10/SPEC-06-hosted-api-lanes.md), [HL-17](../specs/archive/materialization-observation-2026-10/issues/HL-17-provider-webhooks-into-signal-ingress-as-wake-signals.md), [SPEC-04 §3](../specs/archive/materialization-observation-2026-10/SPEC-04-watchers-and-callbacks.md), [MO-40](../specs/archive/materialization-observation-2026-10/issues/MO-40-signal-ingress-service-sql-functions-and-migration-0035.md), [research/vercel-ingress.md](../specs/archive/materialization-observation-2026-10/research/vercel-ingress.md); ADRs [0043](../adr/0043-secret-broker-per-lane-delivery-minted-signal-credentials-never-commit-secrets.md), [0045](../adr/0045-signal-ingress-trust-tiers-signals-are-evidence-never-authority.md).
- Code: [service](../../src/mission_control/application/signals/service.py), [verification](../../src/mission_control/application/signals/verification.py), [PostgreSQL store](../../src/mission_control/adapters/postgres/ingress.py), [Cursor OIDC](../../src/mission_control/adapters/auth/provider_oidc.py), [routes](../../src/mission_control/interfaces/http/ingress.py), [migration 0035](../../packages/mission-control-db-contract/component/migrations/0035_signal_ingress.sql).
- Tests: [unit](../../tests/unit/signals/test_ingress_service.py), [provider wakes](../../tests/unit/signals/test_provider_wake.py), [verification](../../tests/unit/signals/test_verification.py), [OIDC](../../tests/unit/signals/test_provider_oidc.py), [PostgreSQL and loopback HTTP](../../tests/integration/postgres/test_signal_ingress_postgres.py), [drainer](../../tests/integration/postgres/test_run2_ingress_drainer_postgres.py), [non-superuser owner](../../packages/mission-control-db-contract/tests/test_signal_ingress_definer.py).

- Telemetry Hook Pack: [pack table](../../src/mission_control/application/agentic_components/telemetry.py), [script](../../src/mission_control/application/agentic_components/signal_hook.py), [signal_emit](../../src/mission_control/interfaces/mcp/signal_tools.py), [skill](../../skills/mc-signals/SKILL.md); tests [script](../../tests/unit/agentic_components/test_signal_hook.py), [projection](../../tests/unit/agentic_components/test_telemetry_pack.py), [tool](../../tests/unit/signals/test_signal_emit_tool.py), [PostgreSQL](../../tests/integration/postgres/test_telemetry_pack_ingress_postgres.py), [cursor_cloud fixture drill on Temporal](../../tests/integration/cursor/test_cursor_cloud_telemetry_drill_real_services.py).
