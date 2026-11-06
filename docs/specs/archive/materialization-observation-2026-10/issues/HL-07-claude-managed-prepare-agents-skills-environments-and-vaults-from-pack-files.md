# [HL-07] claude_managed prepare: agents, skills, environments and vaults from pack files

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Hosted  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice S2 (claude_managed cloud, launched remotely)  
**Blocked by:** HL-06, HL-23  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

Cognition and environment must be projected through the Managed Agents API. To start S2 before the S1 foundations (R30), the first prepare reads checked-in pack files; HL-21 later swaps in the general projection.

## Work

- Pack files under deployments/hosted-packs/<app>/claude_managed/: agent (model, system overlay, tools with permission policies, MCP servers, skills directories, metadata), environment (packages, limited networking with explicit allowed_hosts including the ingress host), vault credential names (values from the worker env at sync time, never from files).
- Sync keyed by digest: agent per materialization digest (optimistic version), skills uploaded by bundle digest, environment per kit digest (new digest means new environment), vault per secret-set digest.
- Render repo AGENTS.md into system; record API read-back digests as discovery proof.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `adapters/anthropic_managed/prepare.py`
- `adapters/anthropic_managed/client.py`

## Acceptance

- [ ] Fake-API tests; a live sync creates resources once and reuses them on the second run (owner-authorized, inside the S2 budget).

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
