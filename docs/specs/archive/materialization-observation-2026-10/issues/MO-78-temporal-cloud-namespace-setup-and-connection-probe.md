# [MO-78] Temporal Cloud namespace setup and connection probe

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** S  
**Sprint:** in — slice R (Remote operation: thin Temporal worker on AWS and remote launch)  
**Blocked by:** None  
**Specification:** [SPEC-11-remote-worker-on-aws.md](../SPEC-11-remote-worker-on-aws.md)

## Problem

Temporal Cloud has never been exercised by this code (R20). Both the S0 Cloud run (MO-67) and the AWS worker (MO-77) need the namespace prepared first, and neither should own that setup.

## Work

- Register the custom search attributes the code uses on mission-control-dev.ih0e7 (Cloud UI or tcld; removal is unsupported, so list them first and get the integrator's sign-off).
- Decide and document Worker Deployment versioning on Cloud: TEMPORAL_PROMOTE_ON_START behaviour, build id = package version plus git sha, and the rule of one base worker per (namespace, application).
- A read-only connection probe script (no secrets printed): connect with TEMPORAL_TARGET=cloud and the API key, describe the namespace, list search attributes, start and complete one no-op workflow on a probe task queue with a throwaway in-process worker.
- Document the exact env contract (TEMPORAL_TARGET, TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE, TEMPORAL_CLOUD_API_KEY) in the operator guide.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `docs/MISSION_CONTROL_LOCAL_API.md`
- `bootstrap/settings.py`
- `scripts/temporal_cloud/`

## Acceptance

- [ ] The probe completes against mission-control-dev.ih0e7 and its output is recorded; mission-control-prod.ih0e7 is untouched.
- [ ] Search attributes and the versioning rule are documented; MO-67 and MO-77 reference them instead of repeating setup.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
