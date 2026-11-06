# [LS-03] Codex adapter with WSL host support

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Skills  
**Wave:** A — Start now: foundations and fixes, Cursor P0, local CLI skills, S0 setup, hosted-lane groundwork (remote-session base, conformance suite, profile vocabulary), provider smoke, Temporal Cloud namespace setup  
**Size:** S  
**Sprint:** in — slice LS (Local CLI job skills)  
**Blocked by:** LS-01  
**Specification:** [SPEC-08-local-cli-skills.md](../SPEC-08-local-cli-skills.md)

## Problem

Map the job contract to codex exec.

## Work

- --json events; --output-schema/-o; exec resume; sandbox/approval profiles; stdin closed; forced_login_method chatgpt; host auto→wsl on Windows with path translation.
- --ignore-user-config and explicit -c overrides (owner config defaults to danger-full-access); no -a on exec; --full-auto removed; options before `resume <id> -`; scrub API keys before forced_login_method; launch codex.exe directly; --ephemeral only for single-iteration jobs.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `.agents/skills/coding-cli-jobs/scripts/adapters/codex.py`

## Acceptance

- [ ] argv and event-parsing unit tests; WSL path translation tests.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

SPEC-08 is independent of Mission Control runtime; section 10 CLI corrections override earlier examples. No CLI default may silently weaken the requested job profile.

Extend Codex adapter with exact local CLI configuration identity and unsupported-option refusal using scripts/adapters/codex.py.

**Non-goals:** No Mission Control import/catalog publication, SDK lane, hosted subscription adapter, installation or new auth setup.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `.agents/skills/coding-cli-jobs/`
- `.agents/skills/claude-code-headless/`
- `.agents/skills/codex-exec/`
- `.agents/skills/cursor-agent-headless/`

### Additional acceptance and negative cases

- [ ] Result records actual CLI/version/host, requested model/effort, observed model or unknown, auth route, permission profile and effective configuration sources.
- [ ] Unsupported supplied option fails before CLI spawn; omitted model retains disclosed native default; resume preserves explicit settings and auth route.
- [ ] Subscription jobs scrub API keys before auth guards; unknown usage/cost remains unknown; no mission_control import, secret copying, push/merge/PR or cloud-lane claim.

### Minimum verification (future commands, not executed)

- Offline: use SPEC-08 fake-CLI/schema/argv/env/redaction suite under .agents/skills/coding-cli-jobs/tests/ after it is created; establish exact command in handoff.
- Before tests exist, inspect SPEC-08 section 10 and research/cli-adapters.md; add option refusal, omitted model, resume/config and API-key sentinel cases. No smoke invoked by planning.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small increment within original schema/adapter work.
