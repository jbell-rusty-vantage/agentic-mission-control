# [MO-01] Compose bundle custody into every production capability rows resolver

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** S  
**Sprint:** in — slice F (Foundations and fixes)  
**Blocked by:** None  
**Specification:** [SPEC-02-cognition.md](../SPEC-02-cognition.md)

## Problem

CatalogProjectionRows/CatalogRows are built without custody, so every skill bundle and hook script raises 'custody is not configured' on every lane in production (gap G1, handoff C5).

## Work

- Pass the configured BundleCustody (local FS or Supabase bucket) into all rows resolvers at bootstrap/manifests.py:213, provider_lane_composition.py:103,163, deployment_composition.py:628,672.
- Workers fetch bundles through signed URLs per ADR-0024; cache by digest.
- Fail launch with a typed error when custody is unavailable instead of at materialization time.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `bootstrap/manifests.py`
- `adapters/temporal/provider_lane_composition.py`
- `adapters/temporal/deployment_composition.py`
- `application/capabilities/bundle_custody.py`
- `tests/integration/`

## Acceptance

- [ ] Integration test: one skill bundle and one hook-script pin materialize with matching digests on cursor_local, claude_agent_sdk and codex through production composition.
- [ ] Missing custody is a launch-time typed refusal, not a worker crash.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
