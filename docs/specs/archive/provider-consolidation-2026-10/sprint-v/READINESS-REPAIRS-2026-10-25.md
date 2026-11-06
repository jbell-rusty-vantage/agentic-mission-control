---
type: Implementation Evidence
title: "Sprint V readiness repairs before the final interview"
description: "Bounded fixes for report collection assessment and aggregate report-file delivery bytes, with regression evidence and the remaining interview decisions."
tags: [mission-control, sprint-v, readiness, output-contracts, context-transfer]
date: 2026-10-25
status: active
---

# Readiness repairs before IQ-07

Follow-up to [the independent review](ADVERSARIAL-READINESS-2026-10-25.md), requested by the owner
on 2026-10-25. The review remains the historical diagnosis. These are local changes over MC
`fa1f778a`; the reviewer’s existing uncommitted interview/briefing edits were preserved.
This follow-up does not record interview answers, certify the full workflow, or reopen the real-work gate.

## Repairs and how to use them

| Finding / tracker | Change | Bound that remains |
| --- | --- | --- |
| RV-02 / [OVE-160](https://linear.app/overtonbell/issue/OVE-160) | A selection containing a report must contain exactly that one member. Multiple reports, duplicate reports and mixed report/path selections are refused before storage, including revision attempts. Finalization validates the latest stored selections too, so a pre-repair collection cannot acquire a new assessed finalization. | This is the review's temporary restriction option, not per-member assessment or collection aggregation. Historical finalizations are not rewritten. |
| RV-05 / [OVE-161](https://linear.app/overtonbell/issue/OVE-161) | Resolve and represent all selected reports against one decreasing receiver file-byte allowance before staging any files. An oversized aggregate returns `BUDGET_EXCEEDED`, no inputs, and no new delivery plans. Each per-report plan retains its allocated remaining byte allowance. | Partial closure only. No unified sealed prompt/token plan, model file-permission qualification, or official-use eligibility check is claimed. |

For `submit_output`, send one exact report handle plus digest in `items` for an obligation. A report
collection receives a structured `SCHEMA_UNSUPPORTED` refusal; its stable tool-call key is not
consumed. A corrected single-report selection can be submitted afterwards. Non-report collections
remain supported as submission coverage, with no report assessment inferred for them. Separate
obligations can select separate reports; that does not create an accepted collection rule.

Both the tool's capability description and its `items` schema description disclose this bound.
The tool schema digest consequently changes: author/resolve new exact bindings against the running
catalog; old immutable bindings are not rewritten. A pre-repair unsupported collection can be
superseded by a valid revision before finalization. Failed attempts retain their existing
`attempt_failed` recording path.

The delivery limit counts the UTF-8 bytes of every body, ledger and manifest returned to one
`deliver_inputs` call. Exact equality is allowed. Retrying delivery rechecks the aggregate even when
per-report plans already exist, so cached plans cannot bypass a smaller current allowance.
The existing delivery layer may re-stage identical bytes on retry; this limit is delivered content
size, not cumulative I/O or a prompt-token budget. Run-wide selection remains RV-03.

## Finished parts in reading order

1. `SubmitArgs` and `TOOL_DESCRIPTIONS` → `KnowledgeToolset._submit` →
   `SubmissionService.submit` / `_selection_report` → submission store. Finalization checks the latest
   revision before assessment or finalization persistence. Regression tests:
   `tests/unit/knowledge/test_submission_assessment.py` and the structured-refusal test in
   `tests/unit/knowledge/test_knowledge_tools.py`.
2. `KnowledgeToolset.deliver_inputs` → `ContentResolutionService` → `ReportRepresentation` →
   aggregate preflight → existing `DeliveryPlanner` staging/readback/receipts → `InputDelivery`.
   Regression: `test_receiver_report_budget_is_aggregate_before_any_staging` covers individually
   fitting packages, a total one byte over budget, exact-limit success and retry with a reduced limit.

No provider-specific lifecycle or domain adapter was changed. No new persistent state is required for
these two bounds: MC's existing selections and transfer-plan byte fields suffice. KS common SQL,
AI Engineer domain SQL and Biotech graph contracts are unchanged because neither repair adds a
domain entity or authority. This is a no-migration finding for this slice, not for the next sprint.

## Remaining diagnosis and interview decisions

| Finding | Next decision/proof; existing interview question |
| --- | --- |
| RV-01 — open, highest-priority prerequisite | The adapter still discards blocked completion. A simple exception would not supply durable reconciliation or prevent a cognition retry. Define the persisted post-execution wait, its reconciler/wakeup owner, cancellation/timeout/repair behavior, and saved provider result. Prove late acknowledgment and worker restart without repeating the write; FC-Q12/13/21. |
| RV-02 — bounded repair implemented | Decide per-member identities, revision frontier and collection aggregation before enabling multi-report selections; FC-Q1/4/7/9. |
| RV-03 — open | Compile exact predecessor/output selectors, attempt/generation frontier, and independent-verifier exclusions. Do not infer dependencies from run-wide finalizations; FC-Q5/6/8. |
| RV-04 — open | Choose the semantic judge/census host and authenticated KS-owned seal/decision/review route. An in-memory MC decision cache has no production populator; swapping it for a database alone cannot compose admission. Prove ordinary launches for both apps; FC-Q16/17. |
| RV-05 — partial repair | Integrate file bytes, prompt tokens, tool/skill overhead and reserved generation into one effective receiver plan, then prove actual backend readability; FC-Q18/19. |
| RV-06 — open | Crash after native commit but before K01 protocol receipt persistence, restart and reconstruct/recover by the same effect identity. Prove no duplicate native write; FC-Q17/21. |
| RV-07 — reviewer corrections preserved | Read this delta alongside the corrected briefing. Do not relabel historical proofs or mutate release locks. |
| RV-08 — open | Explicit operational-review versus official-use selectors; current native eligibility and revocation checks for official use, while permitting authorized draft/held review; FC-Q6/17/21. |

Recommendations above are engineering inputs, not owner answers. The final interview still launches
the full runtime sprint and its issue decomposition. OVE-160/161 cover only these bounded repairs.

## Validation

Passed on the installed local runtime:

- `.venv/Scripts/python.exe -m pytest tests/unit/knowledge tests/unit/domain/knowledge tests/conformance/test_knowledge_protocol_golden.py tests/conformance/test_knowledge_protocol_negative.py tests/architecture -q --tb=short`: **226 passed**, one upstream LangSmith deprecation warning.
- `.venv/Scripts/python.exe -m mypy`: **894 source files**, no issues.
- `.venv/Scripts/python.exe -m ruff check .`: passed; changed Python files also pass format checking.
- `git diff --check`: passed.
- `.venv/Scripts/python.exe docs/tools/check_docs.py`: **all seven checks passed**.

The RV-02 tests first reproduced the defect (seven failures because collections were accepted),
then passed with the restriction. These are isolated service/tool tests with in-memory fixtures,
not a fresh PostgreSQL, Temporal, KS executor or backend qualification run. Those integrations
were **not run** for this slice. Full unit suite and end-to-end fixtures were not run.

Documentation validation initially found the knowledge concept exceeded its 160-line limit;
the explanation was condensed before the final rerun.
No paid model calls, deployments, native writes or database migrations are part of this repair pass.

## Provenance

- Owner request in this Codex chat, 2026-10-25: diagnose, fix and enhance readiness findings before IQ-07.
- [Adversarial review](ADVERSARIAL-READINESS-2026-10-25.md), RV-01..08, over the supplied four repository commits.
- [Final interview](../interview-instructions/INTERVIEW-OUTPUT-CONTRACTS-CONTEXT-TRANSFER-FINAL-2026-10-24.md), unchanged question identifiers.
- Linear issues created before implementation under the repository's BellLabs method.
