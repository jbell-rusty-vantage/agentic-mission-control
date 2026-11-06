# [MO-10] mission/v2 environment additions with validation and binding population

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-01  
**Specification:** [SPEC-01-environments.md](../SPEC-01-environments.md)

## Problem

The manifest cannot express variables, secrets, kits, network, git write or provider environment strategy (gap G2).

## Work

- Add kit, variables, secrets, network, git, provider_environment to EnvironmentV2 with inheritance rules (no widening).
- Compile-time check of kit requires vs declared variables/secrets/egress; secret names only in bindings.
- Populate EnvironmentBinding.setup_pin, secret_refs, network_policy_ref, observed_config_digest, readiness.
- Relax repo requirement per profile (SPEC-03 §4 correction).

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `domain/authoring/manifest_v2.py`
- `domain/execution/bindings.py`
- `application/authoring/manifest_launch_inputs.py`
- `contracts/schemas/`

## Acceptance

- [ ] One manifest compiles offline for all profiles; mismatches are validation errors with JSON pointers; regenerated schemas reproducible.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
