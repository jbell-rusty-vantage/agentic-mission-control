# [MO-72] Slice S0 end-to-end: local harness path from all three tools

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** B — S0 end to end and Temporal Cloud; Secret Broker; Signal Ingress (SQL, Vercel, drainer) and the remote launch route; lane-only worker and the AWS thin worker; claude_managed prepare, lifecycle, approvals and publication; provider webhooks; data class; Cursor accounting and durability  
**Size:** M  
**Sprint:** in — slice S0 (Local harness path)  
**Blocked by:** MO-08, MO-43, MO-04, MO-05, MO-65, MO-66, MO-68, MO-69, MO-70, MO-71  
**Specification:** [SPEC-09-local-harness-path.md](../SPEC-09-local-harness-path.md)

## Problem

Prove the local programmatic harness path (owner decision R13).

## Work

- Run SPEC-09 §8 runbook: nine runs (three lanes x three launching tools) with wait, inject, cancel/complete and cleanup; record transcripts, frames and usage disposition (owner-authorized spend).

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `docs/qualification/lanes/claude_agent_sdk/`
- `docs/qualification/lanes/codex/`
- `docs/qualification/lanes/cursor_local/`

## Acceptance

- [ ] SPEC-09 §9 acceptance met on local Temporal; records saved.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

Run 1 integrates local env, allocator, discovery and SessionStore seams; it does not qualify the exact WSL placement or the nine caller/lane runs.

Execute S0 only after offline proofs and authorization; carry exact Anthropic configuration, enforcement and custody evidence through normal launch.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `docs/qualification/lanes/`
- `deployments/ (S0 probes)`
- `adapters/claude/harness.py (existing seam)`

### Additional acceptance and negative cases

- [ ] All originally required caller/lane runs and controls remain required; label partial progress without blanket qualification.
- [ ] Claude SDK receipt includes actual SDK/bundled CLI/host/model/auth, repo-file digests, selected skill loading/invocation, tool deny/allow, inject/cancel and immutable output.
- [ ] Resume/reattach retains admitted configuration; stale config/approval fails, child-env sentinels stay redacted and cleanup follows custody.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/claude tests/unit/agentic_components/test_discovery_proof.py tests/conformance/lanes -q
- Future disposable-stack run: use SPEC-09 runbook and RUN-1 reproduction commands with isolated queues; record exact launch/wait/inject/cancel commands.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small incremental evidence additions; original end-to-end qualification is still medium.
