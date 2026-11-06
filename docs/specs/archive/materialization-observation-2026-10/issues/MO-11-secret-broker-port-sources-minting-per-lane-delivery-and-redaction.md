# [MO-11] Secret Broker port, sources, minting, per-lane delivery and redaction

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** L  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-04  
**Specification:** [SPEC-01-environments.md](../SPEC-01-environments.md)

## Problem

Secrets resolve only from the worker env; keyring/secret refs are accepted but never resolved; no minted per-run credentials.

## Work

- Port with keyring/file source and Supabase Vault adapter; provider_held verification.
- mint:signal_token bound to scope/run/unit/generation, digest stored, expiry.
- Delivery adapters: process env allowlist, Cursor env/team secrets API and launch envVars, provider vaults (Anthropic, OpenAI).
- Exact-match redaction for frames/logs/receipts; pre-commit scan of every Mission Control commit to mission branches.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `application/secrets/`
- `adapters/secrets/`
- `bootstrap/`
- `adapters/cursor/`
- `adapters/claude/`
- `adapters/codex/`

## Acceptance

- [ ] Sentinel secret appears in no commit, frame, log or binding.
- [ ] Minted token expires and is bound; wrong-run use rejected.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
