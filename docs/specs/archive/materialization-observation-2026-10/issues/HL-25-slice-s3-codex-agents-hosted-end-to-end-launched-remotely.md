# [HL-25] Slice S3: codex_agents hosted end to end, launched remotely

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** M  
**Sprint:** in — slice S3 (codex_agents hosted, launched remotely)  
**Blocked by:** HL-13, HL-17, HL-24  
**Specification:** [SPRINT.md](../SPRINT.md)

## Problem

Prove codex_agents hosted after claude_managed (R27) on the same remote path.

## Work

- Run the S3 definition of done in SPRINT.md: the same two missions as S2 on codex_agents hosted.
- Exercise: function-tool approval round trip via required_actions, steer and cancel, recovery after killing the AWS task mid-stream (reconcile from items with no duplicate frames), per-turn artifact custody, session DELETE.
- Record transcripts, frames, usage disposition; flip codex_agents openai_hosted to qualified only from this record.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `docs/qualification/hosted/codex-agents/`
- `deployments/hosted-packs/ai-engineer/`

## Acceptance

- [ ] Both missions accepted within the $10 S3 budget; worker-kill recovery shows no duplicate frames.
- [ ] SPEC-06 §9 matrix for codex_agents hosted updated from evidence.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

codex_agents is the hosted Agents API HTTP lane, not Agents SDK. Run 1 S3 paid attempts did not prove accepted approval/recovery; spend/native usage remain unresolved.

Qualify the existing hosted product only after HL-24 and exact OpenAI acceptance/cost prerequisites, with model/configuration and custody evidence.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `docs/qualification/hosted/`
- `deployments/hosted-packs/ai-engineer/`
- `adapters/openai_agents/ (existing seams)`

### Additional acceptance and negative cases

- [ ] Receipt identifies hosted Agents API agents=v1 wire pin, runtime HTTP client build, requested/observed model, exact saved agent/environment/skill/config seals and account scope.
- [ ] Required native shell/file per-command approval refuses; only qualified function-tool approval may satisfy that declared mode.
- [ ] One session/input, accepted durable review plus actual native allow, turn/index visibility and item-recovery dedupe are demonstrated; unknown usage/cost stays unknown.
- [ ] Current-turn path-only artifacts refuse where download is unavailable; registered immutable bytes/version are reviewed and publication remains separate.
- [ ] Prior unknown spend reconciled and cleanup proven before any authorized finite proof; no blind paid retry or inferred qualification from SDK docs.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/openai_agents tests/unit/authoring/test_hosted_launch_bindings.py tests/conformance/lanes -q
- Use retained default-off S3 runner and RUN-1 receipt/reproduction index for later authorized finite proof; remote HL-25 additionally uses normal ingress/AWS path.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small evidence refinement; unresolved native acceptance is a real blocker, not predictable effort.
