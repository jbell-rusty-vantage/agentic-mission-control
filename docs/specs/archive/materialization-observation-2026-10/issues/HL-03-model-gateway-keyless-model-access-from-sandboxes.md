# [HL-03] Model Gateway: keyless model access from sandboxes

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)  
**Size:** M  
**Sprint:** in — slice S4 (Funding-gated: self-hosted placements and real harnesses on Sandbox Host)  
**Blocked by:** MO-11, HL-02, MO-74  
**Gate:** funding — start only when the owner releases slice S4 (DECISIONS R31)  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

Claude CLI or Codex inside a sandbox would otherwise need the organisation API key.

## Work

- Gateway per SPEC-06 §12.2: /v1/messages?beta=true (+count_tokens) only; byte-for-byte body and anthropic-* headers; unbuffered SSE with pings; retry-after/x-should-retry passthrough; per-run token → x-api-key; per-run usage and hard 429 on budget.
- Sandbox env contract (ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST=1, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1, CLAUDE_CODE_SKIP_FAST_MODE_NETWORK_ERRORS=1, skipWebFetchPreflight).
- Two placements sharing one module (R16, R17): the worker host for Docker on WSL2 (host.docker.internal), and gateway routes in the Vercel ingress project served from its *.vercel.app host for Daytona Tier 1/2. On Vercel: per-run token checked in Postgres (ingress_credential, purpose model_gateway); org keys only as Production sensitive env vars; maxDuration 800 s for streams; the 4.5 MB request cap returns a typed 413 with the size; data class internal or lower only.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `interfaces/http/model_gateway.py`
- `application/secrets/`
- `deployments/ingress-vercel/ (gateway routes; leased from the integrator)`

## Acceptance

- [ ] Sentinel test: no org key in any sandbox env or file.
- [ ] Claude CLI in Docker completes a turn through the worker-host gateway, and through the Vercel gateway from a Daytona sandbox on the current tier.
- [ ] A request over budget gets the hard 429; usage per run is recorded.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
