# [HL-01] Daytona qualification on the current tier

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Environment  
**Wave:** D — Workspaces and fan-out, external signal sources; funding-gated S4 (Daytona, SandboxHost, Model Gateway, self-hosted placements, harnesses on Sandbox Host)  
**Size:** S  
**Sprint:** in — slice S4 (Funding-gated: self-hosted placements and real harnesses on Sandbox Host)  
**Blocked by:** None  
**Gate:** funding — start only when the owner releases slice S4 (DECISIONS R31)  
**Specification:** [SPEC-06-hosted-api-lanes.md](../SPEC-06-hosted-api-lanes.md)

## Problem

Daytona is chosen (R9) and runs on the current tier (R16); stdin, log streaming, preview-URL headers and the essential-services egress must be confirmed before adapters depend on them.

## Work

- Record the observed tier (dashboard limits page); the design must work on Tier 1/2 (R16). Confirm a sandbox reaches the Vercel project's *.vercel.app host, api.anthropic.com, api.openai.com, *.chatgpt.com, GitHub, PyPI and npm, and that an arbitrary host is blocked.
- One authorized low-cost smoke (inside the S4 budget and the $200 free credit): create from image, session exec with suppress_input_echo and text-line stdin, log WebSocket streaming, signed preview URL with bearer header pass-through, snapshot/restore, terminate.
- Record results in research/daytona.md.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `docs/specs/archive/materialization-observation-2026-10/research/`

## Acceptance

- [ ] Each SandboxHost method's Daytona behaviour confirmed or its gap recorded with a workaround.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).
