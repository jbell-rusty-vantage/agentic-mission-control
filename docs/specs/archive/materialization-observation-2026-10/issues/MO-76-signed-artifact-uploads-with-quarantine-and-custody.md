# [MO-76] Signed artifact uploads with quarantine and custody

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Events  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** M  
**Sprint:** in — slice S1 (cursor_cloud end-to-end with materialization and observation)  
**Blocked by:** MO-40, MO-75  
**Specification:** [SPEC-10-ingress-on-vercel.md](../SPEC-10-ingress-on-vercel.md)

## Problem

Vercel caps bodies at 4.5 MB; outputs must still reach custody verified.

## Work

- artifacts:prepare issues a signed upload to a quarantine bucket; commit records digest; drainer verifies and moves into custody (ADR-0024); quarantine cleanup.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `application/signals/artifacts.py`
- `adapters/supabase_storage/`

## Acceptance

- [ ] A >4.5 MB artifact arrives, is digest-verified and lands in custody; tampered upload rejected.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

Signed upload quarantine is distinct from durable artifact promotion; edge acknowledgement must not become acceptance.

Verify uploaded bytes and promote immutable scoped evidence before registration/review/cleanup.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Use the existing deps/wave. Shared contracts/composition belong to the integrator; satisfy dependencies with integrated source evidence, not assumed live readiness.

### Affected interfaces (existing seams unless explicitly proposed)

- `application/signals/artifacts.py`
- `adapters/supabase_storage/`
- `application/artifacts/artifact_promotion.py (reuse)`

### Additional acceptance and negative cases

- [ ] Existing >4.5 MB requirement remains; actual size/digest and scoped credential are verified before custody.
- [ ] Mismatch, cross-scope, expired/revoked token and duplicate/conflicting commit cannot create accepted artifacts.
- [ ] Review references registered immutable output/version/digest; publication is separate; quarantine cleanup/retention is recorded and large bytes bypass edge.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/workspaces/test_artifact_promotion.py tests/unit/human_tasks/test_human_gate_rules.py tests/unit/signals -q
- Future disposable PostgreSQL/store fixture covers signed upload->commit->drain->promotion, corrupted bytes and replay.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small-medium evidence join within planned upload implementation.
