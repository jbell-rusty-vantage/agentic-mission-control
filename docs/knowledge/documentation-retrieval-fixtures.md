---
type: Concept
category: qualification
title: Documentation retrieval fixtures
description: How documentation retrieval is measured and gated for Mission Control (the Agentic SDLC bench): query fixtures and task fixtures, the screening, held-out and negative partitions, the critical flag, expected sets of concepts, modules, research and hidden facts, the recorded-baseline rule, the first task fixture T001, and what is specified versus built.
tags: [mission-control, retrieval, fixtures, bench, documentation, sdlc, qualification]
aliases: [retrieval fixture, bench gate, recall@3, task fixture, queries.json]
questions:
  - How is documentation retrieval measured and gated here?
  - What is a task fixture and how does it differ from a query fixture?
  - When may a fixture or its baseline change?
  - Which fixtures are critical and what passes?
updated: 2026-11-01
---

# Documentation retrieval fixtures

An agent with no context should reach the correct, current fact in one or two hops. This concept is the
measurement of that goal for the documentation itself: not product search quality (that is
[selection workspace](selection-workspace.md)) and not runtime qualification ([qualification](qualification.md)).
It is the model the Agentic SDLC program (ADR-0064, SPEC-01) copies from the Knowledge Services benchmark.

## Status: specified, partly built

| Piece | State |
| --- | --- |
| Model to copy: KS `.agent-docs/fixtures/ks-context-v1` (18 positive screening cases, 6 positive and 4 negative held-out cases, `retrieval-benchmark.mjs`, recall@3) | built in `platform/knowledge-services`, tested there |
| Mission Control search: `docs/tools/okf_search.py` (BM25 over weighted fields incl. aliases and questions, module guides, research notes) | built; scored by the fixtures below |
| `.sdlc/fixtures/retrieval/` (`queries.json`, `baseline-before.json`, `baseline.json`, README) and `docs/tools/bench_retrieval.py [--gate]` | **built and run** by the truth pass (OVE-206); `check_docs.py --bench` runs the gate; the vendored `bench` CLI of slice S1 replaces the Python runner |
| First task fixture T001 | in `queries.json` verbatim (one concept renamed, `async-children` to `deep-agents-children`); run before and after the refactor |

## Fixture kinds

A case is `{id, kind: "query"|"task", partition: "screening"|"heldout"|"negative", query|task, expect: {concepts[],
modules[], research[], facts[]}, critical}`.

- **Query fixture.** A natural question an agent would ask ("How do I fork a Stage Graph at a recorded point?")
  with the concepts that answer it. The author of a concept writes at least three (they seed `questions` in its
  frontmatter); the retrieval audit adds one per miss (34 candidate cases in the
  [audit baseline](../specs/agentic-sdlc-2026-11/RETRIEVAL-AUDIT-BASELINE-2026-11.md)).
- **Task fixture (AS-D32).** A real engineering task with the expected *set* of concepts, code entrypoints (module
  `AGENTS.md` blocks), research notes and the hidden gap facts a correct answer must surface. It is measured by set
  recall, not by one top hit, because a task needs several documents at once. Cases are named by id (T001 is
  the owner's first example); their text lives only in `queries.json`.
- **No concept quotes a fixture.** A concept that repeats a case's words ranks first for that case and hides
  the real answer (observed 2026-11-01: this concept outranked every T001 answer while it quoted the task).

## Partitions, the critical flag and the baseline rule

- **screening** cases are the regression gate and may guide tuning; **heldout** cases are reported separately and,
  once observed, are retired from tuning (future tuning needs new unseen cases); **negative** cases expect an
  abstention or an out-of-corpus answer, so the engine cannot win by always returning something.
- **critical** cases must pass individually; a failed critical case fails the gate regardless of the mean. Failed
  cases stay in the report.
- **Baseline.** `baseline.json` holds the metrics per partition measured before the documentation refactor and
  after it. `bench --gate` fails on any drop against the recorded baseline; a baseline moves only in the same pull
  request as the concept change that justifies it (recommended policy, SPEC-01 open item 5), and thresholds change by
  ADR plus a `hold` PR. Fixtures pin concept digests, so a stale snapshot is detected rather than silently passing.
- **Acceptance of the first bench** (REFACTOR-PLAN section 5): T001 concept recall@10 at least 0.7 and module recall at
  least 0.5 (modules are reachable only through module `AGENTS.md` files until the CLI indexes them; the T001 case
  text asks 0.75 and reports honestly), screening recall@3 reported before and after, every critical case listed
  with pass or fail.

## First run, 2026-11-01 (the baseline for the next round)

`queries.json` holds 39 query cases (23 screening, 16 held-out), 3 negative cases and 8 task cases (T001-T004 screening, T005-T008
held-out); 15 are critical. Run through `okf_search.py` before the refactor (commit `66185d2e`) and after it
(`.sdlc/fixtures/retrieval/baseline-before.json`, `baseline.json`); the cases were written before either run and were not changed after.

| Partition | recall@3 before / after | recall@10 before / after | MRR before / after |
| --- | --- | --- | --- |
| screening queries (23) | 0.478 / 0.913 | 0.609 / 1.000 | 0.366 / 0.881 |
| held-out queries (16) | 0.625 / 0.938 | 0.812 / 1.000 | 0.527 / 0.891 |

Task set recall (screening, 4 tasks) before / after: concepts 0.286 / 0.521, modules 0.0 / 0.0, research 0.0 / 0.0, facts 0.875 / 1.0;
held-out tasks: concepts 0.25 / 0.625, modules 0.0 / 0.208, research 0.0 / 1.0, facts 0.75 / 1.0. Negative cases that return nothing: 1 of 3
before and after (search never abstains; "style React checkout buttons" and the Kubernetes query still return documents). Critical cases
passing: 7 of 15 before, 10 of 15 after. **T001 does not meet the acceptance targets**: concept set recall at 10 is 0.14 before and 0.29
after (target 0.7), module recall 0 (target 0.5), facts 2 of 2 (the substring probes are weak).

Still failing after the refactor: critical S07 (an exact transfer between stages ranks `output-contracts` eighth), S21 (running tests and
type checks: `qualification` now says how, but `selection-workspace` and a module guide outrank it), and the critical tasks T001-T003. Causes,
in the order to fix them: (1) a long task is not decomposed into facets (lane, configuration, environment, workflow systems, tests), so
generic words win and this concept, which quotes T001, ranks first for it; (2) module guides are generic (13 guides, none per
`domain/execution` or `application/authoring`), so the module sets cannot be reached until S1 generates per-module blocks with
`Entrypoints:`; (3) no abstention floor; (4) the facts are probed by substring, not read. The next round enhances the documentation against
these cases without editing them.

## T001 as the worked example

The ground truth, the first run and the hidden facts are recorded outside the search corpus in
[TASK-FIXTURE-T001](../specs/agentic-sdlc-2026-11/truth-pass/mission-control/TASK-FIXTURE-T001-SANDBOX-PROVIDER.md),
so the case is not answered by its own description.

## Why this lives under qualification

The documentation is qualified the way code is: a committed proof, a recorded baseline and a gate. A concept that is
fresh in prose but unreachable by search fails the same goal as a wrong concept.

Built / specified / goal: the KS bench is built; Mission Control's fixtures, `bench` and the gate are specified; reaching
recall thresholds on tasks across all four workflow systems (scheduling, output obligations, context transfer,
configuration) is the goal ([goals](goals.md#goal-workflow-mechanics-completely-known)).

## Citations

- Decision and design: [ADR-0064](../adr/0064-one-vendored-sdlc-toolchain-per-repository.md),
  [SPEC-01](../specs/agentic-sdlc-2026-11/SPEC-01-AGENTIC-SDLC.md),
  [REFACTOR-PLAN](../specs/agentic-sdlc-2026-11/truth-pass/mission-control/REFACTOR-PLAN.md),
  [answers AS-D32](../specs/agentic-sdlc-2026-11/answers/AGENTIC-SDLC-SITTING-II-2026-11-02-ANSWERS.md).
- Measurements: [retrieval audit baseline](../specs/agentic-sdlc-2026-11/RETRIEVAL-AUDIT-BASELINE-2026-11.md),
  [T001](../specs/agentic-sdlc-2026-11/truth-pass/mission-control/TASK-FIXTURE-T001-SANDBOX-PROVIDER.md).
- Code: [okf_search](../tools/okf_search.py),
  [sandbox contract](../../src/mission_control/domain/execution/contracts.py),
  [materializer](../../src/mission_control/adapters/deep_agents/materializer.py).
- Model: Knowledge Services `.agent-docs/fixtures/ks-context-v1/README.md` and `.agent-docs/retrieval-benchmark.mjs`
  (`../../../knowledge-services/.agent-docs/fixtures/ks-context-v1/README.md`).
- Tests: [retrieval default-corpus test](../../tests/unit/test_documentation_retrieval.py).
