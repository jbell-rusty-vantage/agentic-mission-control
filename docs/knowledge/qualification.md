---
type: Concept
category: qualification
title: Evidence and qualification gates
description: The proof ladder (implemented, tested, integrated, qualified), the test layers, the Sprint OC release gates W0 to W5 with their status by pointer to the live control board, and the per-profile status of the nine lane profiles (only W0 is released, with recorded limitations; Deep Agents is the reference lane); older G0-G7 gates and compute profiles as history.
tags: [mission-control, qualification, evidence, gates, lanes, proof]
aliases: [W0-W5 gates, proof ladder, release gates, lane qualification status, evidence labels, make check, test commands]
questions:
  - What do local tests prove, and what is still unproved?
  - Which commands run the unit tests, lint and the type gates?
  - Which qualification gates have passed and where is the status?
  - Which of the nine lane profiles are live-qualified?
  - What does implemented, tested, integrated and qualified mean here?
updated: 2026-11-01
---

# Evidence and qualification gates

**Labels.** *Implemented* means in source; *tested* means a committed test passes against the stated layer;
*integrated* means exercised through the real composed path against a disposable database or service on one host;
*qualified* is reserved for a released gate against coordinated builds with an independent reviewer. A claim cites a
committed proof (test, `REPORT.md`, `RELEASE-BUNDLE.md` or control-board lines), never a private `.scratch/` path alone.
Engineering release confers no scientific review or knowledge permitted-use authority.

## Test layers and the commands that run them

Pure contract and reducer tests; real PostgreSQL constraints and RLS (`common_db`-marked suites need a disposable
PostgreSQL 17 with pgvector through `MISSION_CONTROL_TEST_ADMIN_DSN` and fail, never skip, without it); Temporal
histories and replay (`tests/integration/temporal/test_replay_histories.py`, `test_lane_replay_histories.py`);
authenticated HTTP-to-runtime acceptance (`tests/acceptance/mission_control/`); the independent two-project suite
(`tests/qualification/two_project/`). Mocks isolate a transport failure but cannot prove database privileges, durable
replay or provider behavior; fixtures prove Mission Control's rules, never provider behavior. `make lane-qualify
PROFILE=...` runs offline lane suites and `LIVE=1` adds the paid owner-run drill. Source moves require renewed lint,
typing, import and acceptance verification.

**Running the checks.** `make check` is the fast gate (lint, format check, `ty`, `deptry`, architecture, unit and lane conformance tests,
skills manifests); `make typecheck` runs mypy, the authoritative type gate; `make test-integration` needs the compose services
(real PostgreSQL and Temporal); Biotech-domain tests need `uv run --group biotech pytest <selection>`. The Makefile targets and tool roles
are in [developer tooling](../DEVELOPMENT.md); the documentation checks (`make docs-check`) are in
[documentation surfaces](../agents/documentation-surfaces.md).

## Sprint OC gates W0 to W5

The matrix is [PROOFS section 2](../specs/provider-consolidation-2026-10/sprint-oc/PROOFS.md); **status lives only in the
live board**, [NEXT-SESSION](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md) lines 119-121 ("W0 is recorded
released; W1 is not released ... Biotech W1 has not run; W2-W4 are unqualified"). This concept does not restate a status.

| Gate | What it proves (PROOFS section 2) | Status pointer and key proof |
| --- | --- | --- |
| W0 | Four-owner schema fit, fresh and repeat install on disposable targets, ordinary trusted interfaces, evaluator credentials, saved settlement, native receipt foundation | released with recorded limitations: [RELEASE-BUNDLE](../specs/provider-consolidation-2026-10/sprint-oc/release/RELEASE-BUNDLE.md) lines 22, 487-498 |
| W1 | One ordinary GoalDirected report with independent judge and auditor, KS seal, use and review, fulfillment, saved settlement, in each app, with a native-write variant | not released; D27-D30 fixes integrated locally, coordinated rerun open (NEXT-SESSION 119-124); [W1 evidence](../specs/provider-consolidation-2026-10/sprint-oc/release/W1-EVIDENCE.md) |
| W2 | Two-stage producer to consumer transfer, exact sealed plan versus what the consumer received | unqualified; WI-02 exact delivery integrated ([output contracts](output-contracts.md)) |
| W3 | Multi-report accumulation, exact current set, per-member assessment, partition closure | unqualified; collections tested ([collections](collections-and-current-sets.md)) |
| W4 | Revision, links, hooks, repair fork, deterministic crash injection | unqualified; exact linked exports 1.10.0-1.11.0 integrated locally |
| W5 | Stage Graph with the Swarm profile, Goal Loop, EO, recursion, async children, real coordinator host wake, both apps | unqualified; async children and wake are tested only ([children](deep-agents-children.md), [attention](coordinator-attention.md)) |

Engineering fixtures that precede these gates and are **not** gate releases: the Qualia StageGraph and AI Engineer
StageGraph fixtures (NEXT-SESSION 25-98): seven-stage Deep Agents graphs with parallel branches, exact transfers, schema
output obligations, independent KS verification with repair, native admission and acknowledged writes with complete
readback, applied queued instructions, interrupt and inject, and a recorded-point fork. They are *integrated, live paid*
for Deep Agents on the disposable targets; the production per-invocation Biotech authority mapping is not qualified.

## The nine lane profiles

`LANE_PROFILES` (`domain/execution/lanes.py:78-88`; ADR-0035, ADR-0050). Only `deep_agents` declares `qualified=True`
(`adapters/deep_agents/describe.py:119`), and that flag means the describe declaration, not a W gate.

| Profile | Implemented and tested | Live evidence | Qualified |
| --- | --- | --- | --- |
| `deep_agents` | reference lane: launch, chains, Human Gates, cognition points, async children, trusted judgment | paid Qualia and AI Engineer fixtures (integrated) | flag only; W1 unreleased |
| `claude_agent_sdk`, `codex` | lanes on Linux and WSL workers against FIXTURE clients ([provider lanes](provider-lanes.md)) | Run 2: one Stage Graph mission each, local Temporal and Temporal Cloud (MR-01/11, MR-02/12) | no |
| `cursor_local` | lane with MP-09 parity, offline | MR-03 blocked by an SDK `observe_run` rejection | no |
| `cursor_cloud` | lane against FIXTURE Cloud API ([cursor lane](cursor-lane.md)) | none | no |
| `claude_cloud`, `codex_cloud` | describe stubs with refusals everywhere | none | no |
| `claude_managed`, `codex_agents` | hosted API lanes ([hosted API lanes](hosted-api-lanes.md)) | none | no |

Run 2 receipts are materialize-and-run proofs, not promotions ([finish disposition](../specs/archive/materialization-observation-2026-10/runs/RUN-2-FINISH-DISPOSITION-2026-10.md));
moving each lane from declared to proven is the [provider consolidation program](../specs/provider-consolidation-2026-10/README.md).
The retrieval measurement for the documentation itself is [documentation retrieval fixtures](documentation-retrieval-fixtures.md).

## History (not current gates)

The 2026-10 expansion packet's G0-G7 gates, the C0-C4 compute profiles and `ProofBudget@1` (a signed live-experiment
budget with exact rational micros) are no longer a delivery plan: no repository document recorded a gate verdict per
letter and `ProofBudget@1` is not built; the paid-spend rule is [budgets and usage](budgets-and-usage.md). The fast-track
packet (release 1.1.0, lane qualification offline), the multi-provider packet (fixture lanes, MP-20 parity, hosted parity
MP-21 blocked) and Run 2 are recorded in [multi-provider release statement](../specs/archive/mc-surfaces-2026-10/docs/qualification/release/multi-provider-2026-10.md),
[MP-20 parity](../specs/archive/mc-surfaces-2026-10/docs/qualification/parity/multi-provider-2026-10-09.md) and the Run 2 disposition. The October 2026 installation
of release 1.0.0 into both Supabase projects is historical ([database component](database-component.md) for current state).

Built / specified / goal: the ladder, layers and the Deep Agents fixtures are implemented and integrated; W0 is the only
released gate; W1 to W5, every other lane's qualification, and the real coordinator-host wake are open goals.

## Citations

- ADR: [0009](../adr/0009-common-release-separate-app-authority.md),
  [0017](../adr/0017-agent-server-runtime-persistence-separate-database.md),
  [0035](../adr/0035-seven-lane-profiles-versioned-provider-contracts-and-mission-v2.md),
  [0050](../adr/0050-nine-lane-profiles-claude-managed-and-codex-agents-and-the-mission-data-class.md).
- Proof: [NEXT-SESSION](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md),
  [PROOFS](../specs/provider-consolidation-2026-10/sprint-oc/PROOFS.md),
  [RELEASE-BUNDLE](../specs/provider-consolidation-2026-10/sprint-oc/release/RELEASE-BUNDLE.md),
  [Run 2 carry-forward](../specs/provider-consolidation-2026-10/RUN-2-CARRY-FORWARD.md),
  [lane qualification](../qualification/lanes/README.md),
  [local profile readiness](../specs/archive/mc-surfaces-2026-10/docs/qualification/local-profiles/README.md),
  [live plan](../specs/archive/mc-surfaces-2026-10/docs/qualification/two-project/LIVE_PLAN.md).
- Code: [lane profiles](../../src/mission_control/domain/execution/lanes.py),
  [Deep Agents describe](../../src/mission_control/adapters/deep_agents/describe.py),
  [dry run](../../scripts/fast_track_dry_run.py).
- Tests: [PostgreSQL runtime parity](../../tests/acceptance/mission_control/test_postgres_runtime_parity.py),
  [authenticated scoped runtime](../../tests/acceptance/mission_control/test_authenticated_scoped_runtime.py),
  [two-project release parity](../../tests/qualification/two_project/test_release_parity.py),
  [lane replay histories](../../tests/integration/temporal/test_lane_replay_histories.py),
  [lane conformance](../../tests/conformance/lanes/README.md),
  [describe honesty](../../tests/unit/harness/test_describe_honesty.py),
  [Sprint OC release 1.9.0](../../tests/integration/postgres/test_sprint_oc_release_190.py).
