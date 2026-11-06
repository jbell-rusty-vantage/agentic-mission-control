# [HL-24] Slice S2: claude_managed cloud end to end, launched remotely

Status: ready-for-agent — subject to blockers (not published to Linear)

**Owner:** Integrator  
**Wave:** C — S2 claude_managed drill, then S3 codex_agents; S1 cursor_cloud end to end; full cognition projection; preflight; signals, gates and watchers  
**Size:** M  
**Sprint:** in — slice S2 (claude_managed cloud, launched remotely)  
**Blocked by:** HL-09, HL-17, HL-18, HL-23, MO-74, MO-77, MO-79  
**Specification:** [SPRINT.md](../SPRINT.md)

## Problem

Prove claude_managed cloud as the first remote lane (R27) before any other hosted lane qualifies.

## Work

- Run the S2 definition of done in SPRINT.md: a knowledge mission and an SDLC mission, both requested through the launch route and orchestrated by the AWS worker.
- Exercise: provider webhook wake through the ingress, one always_ask approval round trip, interrupt_and_inject, budget-gate pause and resume, mc_publish bundle → verified push → draft PR, usage settled from list_cost, session deleted after custody.
- Record transcripts, frames, usage disposition and the describe matrix observed; flip claude_managed cloud to qualified only from this record.

## Source ownership

Paths are relative to `src/mission_control` unless they begin with `tests/`, `docs/`, `skills/`, `.agents/`, `packages/`, `scripts/` or a root filename. New paths are proposed.

- `docs/qualification/hosted/claude-managed/`
- `deployments/hosted-packs/ai-engineer/`

## Acceptance

- [ ] Both missions accepted by their Completion Contracts within the $10 S2 budget, with the owner's machine not running the base worker.
- [ ] SPEC-06 §9 matrix for claude_managed cloud updated from evidence.

## Validation and handoff

Run `make check` (or ruff, `uv run mypy`, relevant pytest selections). Persistence and runtime claims need real local PostgreSQL and Temporal. Report passed, failed, blocked and unrun checks separately. No commits, pushes, deployments or paid provider drills without owner authorization. Do not flip `qualified` from fake evidence.

## Provenance

- Owner briefs 2026-10-12 (environment/cognition/observation; API billing approval, hosted API lanes, local CLI skills; remote operation and the AWS thin worker).
- Packet: `docs/specs/archive/materialization-observation-2026-10/` (README, SPRINT, DECISIONS, SPEC-01..11, MANAGED-AGENTS-REMOTE-PATH, research/).
- Baseline: the 2026-10-12 checkpoint on `origin/main` (R19); sharpened the same day (DECISIONS R27-R33).

## Run 2 approved refinements (2026-10-14)

Approved acceptance refinement; no live execution authorization. [Shared rules and escalation](../runs/RUN-2-PLANNING-AMENDMENTS.md). Inspection base: `a2527f6f3c385a7f55272c41d90e6860b44781d0`.

### Current baseline and concrete outcome

Managed Agents adapter/config read-back and local HL-09 approval/publication exist; remote S2 and full owner-selected HL21 are not blanket-qualified. Budget hold/release has no production workflow caller; describe pause is unsupported.

Qualify remote Anthropic knowledge and SDLC missions with exact selected tools/configuration, custody, approval and explicit pause blocker.

**Non-goals:** No new lane, model catalog, generic configuration schema or deferred feature.

**Sequencing:** Existing deps HL-09/17/18/23 + MO-74/77/79 remain. Carry HL21 owner-binding/config evidence; escalate pause wiring to integrator before qualification. No new implementation issue or permission is silently created.

### Affected interfaces (existing seams unless explicitly proposed)

- `docs/qualification/hosted/claude-managed/`
- `deployments/hosted-packs/ai-engineer/`
- `adapters/anthropic_managed/discovery.py (existing seam)`
- `application/execution/harness/describe.py (integrator-only)`

### Additional acceptance and negative cases

- [ ] Both original Completion Contracts, laptop-off remote path and budget/cleanup requirements remain; report each blocked cell separately.
- [ ] Pin actual agent/version, skill/version, MCP/toolset/permission policy, instructions, network/env and configuration seals. Read-back is not invocation proof.
- [ ] Required unsupported enforcement refuses before create; native approval deny/allow/timeout binds the exact effective config, never webhook authority.
- [ ] Budget-gate pause/resume remains blocked until governed production wiring and actual budget-boundary receipt exist; demonstrated boundary hold is separate and cannot replace it. Do not mark native/hard pause.
- [ ] Immutable output/version is reviewed; publication is a separately granted verified effect; settled list_cost and cleanup receipts are required.

### Minimum verification (future commands, not executed)

- uv run pytest tests/unit/anthropic_managed tests/unit/agentic_components/test_discovery_proof.py tests/unit/human_tasks/test_human_gate_rules.py tests/conformance/lanes -q
- Live runners remain default-off: tests/integration/anthropic_managed/test_approval_publication_live.py and test_session_lifecycle_live.py are historical local seams, not remote HL-24 proof. Remote proof uses normal ingress/AWS launch after exact authorization.

**Live:** Unrun until exact prerequisite/configuration/placement and action-specific authorization are established. Use the assigned spec/drill; fixture success never sets qualified. Retain default-off paid runners.

**Compatibility/security/cost:** Preserve old canonical bytes, admitted model/options, approval configuration seals and scoped grants across retry, reattach, continuation and fork. See RUN-2 shared acceptance rules. Apply shared redaction, explicit unknown-cost and action-specific authorization rules. No fake evidence in production.

**Evidence and failure conditions:** Map every criterion to exact source revision, test/receipt, evidence level and disposition; record requested versus observed identity, usage uncertainty, resource custody and cleanup. Apply RUN-2 shared escalation rules.

**Incremental effort:** Small-medium offline refinement; pause wiring is an unresolved implementation boundary.
