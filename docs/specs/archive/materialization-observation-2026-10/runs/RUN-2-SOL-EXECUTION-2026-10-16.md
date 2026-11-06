---
type: Agent Configuration
title: "GPT 6.1 Sol-only Run 2 completion instructions"
description: "Reusable low-concurrency implementation launch prompt, exact file leases, review contracts and stop/go boundaries; requires separate owner authorization to execute."
---

# Sol-only execution instructions

**This file does not authorize implementation.** Use after the owner separately approves the proposed [completion work packages](RUN-2-COMPLETION-PLAN-2026-10-16.md). The current assessment is planning only. This prompt supersedes historical Astra/many-worker model/concurrency instructions for the requested team; accepted sprint criteria and operational authority remain in force.

Select **`gpt-6.1-sol`** for the lead in the actual task UI/CLI before starting. Prompt text does not select a model. Verify available tools/models and report the actual assignment. Every worker, reviewer and replacement uses exactly `gpt-6.1-sol`; if unavailable, stop that assignment and report the blocker. Do not silently substitute another model or use a provider experiment as a worker. Do not change global model/configuration settings.

## Copy-paste lead prompt

```text
Complete only the currently authorized Mission Control Run 2 work packages. You and every
worker/reviewer must use gpt-6.1-sol. Verify/report actual model assignments; no fallback.
First read the current direct owner authorization. If implementation has not separately
been authorized, remain read-only and refine planning only.

Canonical repo: C:/Users/Pinda/Proyectos/BellLabs/platform/mission-control.
Read workspace/repository and scoped AGENTS, then the exact SESSION-END-2026-10-16
MISSION-HANDOFF and MULTI-PROVIDER-SURVEY under the ignored run2/resumed directory.
Read RUN-2-COMPLETION-ASSESSMENT/FINDINGS/PLAN-2026-10-16 and this Sol execution file.
Then accepted general spec/runtime annex, SPRINT/DECISIONS/PLAN/TEAM-WORKSPACE,
assigned Spec07..11, issues.json deps/run2_plan and exact issue Markdown.
Older reports and kickoff have superseded factual statements; do not execute their baseline.

Establish actual branch/HEAD/status/source hashes and concurrent work. Assessment base was
a8d69c5b48506c6babcd7f3f74f0b92716423091, mo/run2-integration. Preserve unrelated dirty
knowledge/index.md, RUN-2-REPORT.md, issues/bash.exe.stackdump, all ignored receipts,
environments/native stores/worktrees/volumes and running sessions. No fetch/reset/clean/stash.
An existing checkout name is not proof of the correct base. An isolated worktree from HEAD
omits uncommitted planning: pin/copy only reviewed planning bytes, never secrets or dirty code.

Run W0 first. Never submit/start the latest Cursor public run
60f44a50-c0e4-5edb-ac13-0fb0436aaedb again; retain its claimed global once-only fence.
Its native FINISHED/926070 receipt is not durable settlement/custody/cost proof.
Do not execute the unfinished scratch controller. Review exact hashes offline.
Do not repeat Full3 human approval/account setup or settled recovery attempts.

Use lead plus one active Sol worker by default. One heavy test/fixture/build/native process
total. A second disjoint read-only worker is optional only after fresh resource measurement.
No nested delegation. Never kill another session or stop a shared service for resources.
Explicit fresh-context worker brief, exact writable file lease, dependency evidence and
bounded checks are mandatory. Shared contracts/domain/describe/bootstrap/SQL/release/locks,
public schemas and index are integrator-only unless expressly leased.

Implement only demonstrated missing/broken criteria. W1 controller/ownership and W2 Cursor
accounting precede new inference; W3 proves production/recovery/caller joins. W4 verifies
current data/ingress/release, W5 closes independent CLI jobs. Native W6 S0, W7 remote R/S1,
W8 S2 and W9 S3 need their exact stop/go gates. S1 is independent; HL-24 precedes HL-25.
Keep all 18 S0 cells and both hosted mission contracts unless owner amends them explicitly.

Temporal schedules; reducers own acceptance/settlement. Keep command accepted/delivered/
applied, native done, process exit, usage/cost settlement, review and publication distinct.
Preserve dispatch-before-effect, idempotency/native identities, generation/revision/owner
fences, immutable bindings/approval seals and custody-before-cleanup. Never retry ambiguous
native work blindly or use webhooks as authority. Missing counters/cost remain unknown.

AI Engineer lock and retained apply receipts are 1.4.2, not the old unapplied 1.4.0 baseline.
Recheck current installed fingerprint/roles/seeds; do not repeat migration. Applied release,
seed and migration bytes stay immutable; new schema work requires integrator design, new
slot, disposable fresh/upgrade/repeat/refusal proof, recovery plan and specific live authority.
No manual accounting inserts or fabricated legacy/native identity backfill.

Managed budget-control production callers already exist; qualify their composition and
native boundary rather than reimplementing the service. Keep pause declarations conservative.
OpenAI codex_agents is hosted Agents API custom HTTP, not Agents SDK, direct Responses or
subscription Codex cloud. Current vendor docs do not repin active bindings. No new capability
evolution registry, maintenance/batch/direct-model/new-provider/UI scope, broad Deep Agents,
deferred CM/SC work, cross-lane forks or S4 funding promotion.

Before every live inference/deploy/secret/webhook/migration/resource/production action,
prepare the reviewed exact target/script/build/config, current prerequisites, remaining
allowance after unknown-spend reconciliation, native capture and cleanup plan. Check trusted
current owner authority; old ceilings are not funds or new permission. Keep runners default-off.
Do not assume authorization for different provider/model/account/region/size or publication.
Commit/push/main merge, Linear and production namespace actions remain separately gated.

Use small deterministic regressions before isolated PG/Temporal proof; no real provider or
shared database tests. No implicit install. One process at a time, bounded outer deadlines,
tracing off and safe temp roots. Run authoritative mypy, Ruff/ty/deptry, architecture and
required release checks once at the final integrated base; do not hide missing Biotech SDL.
Repeat checks only after relevant new changes/failure/concern. Preserve failed evidence.

Independent Sol reviewer is read-only and reviews exact submitted hashes/diff/criteria.
Integrator verifies joins before adopting a patch. Disjoint passing units do not qualify the
integrated product. Hand off criterion/source/test/live evidence, commands/dispositions,
cost/privacy/cleanup liabilities and smallest next step. Report progress at least every 60s.
Finish with exact changed paths, integrated revision/overlay, gates passed/failed/blocked/unrun,
qualification coverage and remaining authority decisions. Do not claim sprint complete if a
required cell or liability is unresolved.
```

## Worker contract

```text
Model: gpt-6.1-sol (verified via actual assignment). No nested agents.
Outcome/package/issues: <bounded result and acceptance criteria>.
Checkout/branch/HEAD + approved planning overlay hashes: <exact>.
Dependency evidence: <source/test/receipt; no generic “done”>.
Writable lease: <individual paths>; everything else read-only.
Already implemented criteria: <inspect first; do not duplicate>.
Proposed smallest change: <behavior, preserved invariants, exclusions>.
Checks: <exact safe commands, outer bounds, fixture/temp identity, resource class>.
Authority: <offline only unless separately specified; no paid/shared runtime/Git action>.
Deliver: patch/hash set, criterion evidence, original failures, checks passed/failed/blocked/
unrun, exact model/runtime/config, unknown cost/native state and cleanup liabilities.
Stop and report if lease/base changes, ambiguity, scope/contract changes or resource pressure.
```

## Reviewer contract

Review only the submitted diff and pinned planning overlay, read-only, with `gpt-6.1-sol`. Trace production callers and tests against exact criteria. Distinguish a code defect from missing proof and a historical claim. Check source/native identity, idempotency/replay, generation/owner fences, old canonical bytes and approval seals, actual artifact custody, unknown usage/cost and control semantics. Test equal-value duplicate fixtures do not hide mixed-source accounting. Do not invoke live providers or change files. Report severity, file:line, minimal correction and uncertainty; a changed patch invalidates its previous review.
