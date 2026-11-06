---
type: Research
title: "Final interview source recheck and question dispositions, 2026-10-26"
description: "Fresh local source and primary-source research before the capped final interview; identifies implementation consequences, corrects candidate wording and preserves unaccepted policy choices."
tags: [mission-control, research, interview, workflows, context-transfer]
date: 2026-10-26
status: active
---

# Final interview research

Prepared before beginning questions in the new final-interview chat. Read the
[handoff](FINAL-INTERVIEW-HANDOFF-2026-10-26.md), [instrument](FINAL-INTERVIEW-20-QUESTIONS-2026-10-26.md)
and [accepted record](ANSWERS.md) together. This is evidence and recommendation, not new owner acceptance.

## Scope and method

The owner requests the first major coherent version of Stage Graph, GoalDirected, linked workflows,
effective run configurations, output contracts/submission/fulfillment, workflow-specific transfer,
and selected coordinator tools/notifications. The coordinator is an agent system using MC and KS;
its conversation is not the execution program. All four canonical workflow systems remain required.

Three read-only exploration agents inspected graph/contracts, workflow composition, and hooks/coordinator
surfaces. The primary agent reconciled their findings with the owner record, MC specification, KS
contracts, and public primary sources. Source snapshots: MC main at
`1863017c779a1b138951c19a0abfcadc4f839a84`; shared KS main at
`b45adf5ac517510c14842d8fd2909fca95ce1e24`. MC has one registered checkout.
Existing dirty/untracked documentation was preserved. No runtime tests, provider experiments, database
inspection/migration, real fixtures, commits, pushes or tracker mutations were performed.

This is source inspection, not runtime qualification. Earlier AIDB/BKS installation claims were not
freshly verified. Four-owner schema-fit review remains required during implementation.

## Corrections and required engineering work

Paths in this section are MC-root-relative unless prefixed KS.

| Finding | Fresh evidence | Consequence |
| --- | --- | --- |
| Effective configuration already exists | `src/mission_control/domain/authoring/contracts.py:2247–2270`; `compiler.py:704–725` | Extend the existing exact compilation/authority-intersection path with the accepted obligations/transfer model. Do not invent another configuration authority. |
| Named data binding is not faithfully lowered | `domain/authoring/stagegraph_builder.py:67–100` chooses first output and required/all; `application/programs/stage_inputs.py:28–35` requires depends_on | Repair exact named source selection and separate content dependencies from ordering. No owner question is needed. Code paths are under src/mission_control. |
| Tests encode some old limits | `tests/unit/operations/test_mp20_authored_stage_inputs.py:111–140`; `tests/unit/authoring/test_manifest_compile.py:204–222` | Existing green tests would not prove the accepted target: add conformance for named input without redundant ordering and actual nested execution. |
| Recursive workflow execution remains incomplete | `domain/authoring/manifest.py:793–804`; `manifest_lowering.py:317–326,424–436`; `domain/programs/contracts.py:46` | Swarm/EO syntax exists, but runtime family is StageGraph or GoalDirected; nested Goal Loop is flattened with a warning. Prove real family behavior and recursion, not merely parser acceptance or context builders. |
| Completion and current-set semantics need repair | `manifest_lowering.py:303–313`; `adapters/temporal/workflows/goal_directed.py:530–545`; `application/outputs/submission_service.py:477–483` | Replace last-stage goal approximation, latest-executor-only verification and collection refusal with explicit coverage, exact accepted sets, per-member assessment and distinct fulfillment/finalization. |
| Transfer selection has competing paths | `application/knowledge/toolset.py:365–387`; `application/chains/packet.py:84–95,192` | Run-wide reports and filename/stem/all-artifact fallback must yield to one sealed named-source plan. Test exclusion of unrelated siblings and correct receiver alias. |
| Scale is not established by concurrency | `domain/programs/interpreter.py:229–259`; `adapters/temporal/workflows/stagegraph.py:1010–1014` | Durable inventory/windows need paging, history, fairness and resource proof; no invented numerical workload target. |
| Preflight already exists | `application/authoring/manifest_service.py:1738–1757`; `application/coordinator/coordinator_launch.py:365–454` | F20-19 concerns extending existing preflight with the new contract/input/resource/revision-impact view, not adding a second preflight subsystem. |
| Hook result fields are not universally consumed | `adapters/deep_agents/hooks.py:838–854,905–914`; `compaction.py:211–221,294–316` | Pre-model context is consumed; post-model context is ignored; compaction results are discarded. Specify event-by-event effects, trust, accounting and recovery. |
| Script cwd is not agent sandbox | `adapters/deep_agents/materializer.py:554–560,613–631` | Scoped reads, staged preparation files and direct effects are separate capabilities requiring the selected contract. |
| Wake transport proof is narrower than host proof | `tests/acceptance/mission_control/test_wake_channels.py:1–11,56–143` | Existing acceptance covers a separate missionctl process and deterministic cognition, not an actual external coordinator agent waking. Retain real selected-host qualification. |
| KS owns exact-use authority | KS `packages/research-core/src/records/decision.ts:15–43`; `packages/knowledge-operation-protocol/src/capability.ts:17–43` | Exact report/use/audience/effect/policy/revocation bindings and qualified capability receipts cannot be replaced by MC fulfillment, a notification or hook access. |

The source-relative abbreviations above follow the cited file's owning directory. No change to the
normative contracts is inferred from an implementation defect.

## Workflow distinctions to retain in the integrated version

- Stage Graph uses declared dependencies and exact selected inputs. Ordinary direct transfer needs
  no reducer or partition. Accepted unfinished-branch default is continue within budget.
- Goal Loop adaptively selects permitted actions and carries the accepted-set index, actionable repair
  view and required progress note. Independent work can proceed while affected obligations wait.
- Swarm isolates members; convergence receives its qualifying set. Quorum releases immediately,
  best-effort waits for terminal members, and surplus defaults to cancellation.
  Evidence: `mission-control-general/workflow-types/03-PARALLEL_SWARM.md:74,87–89,112,159` (deleted 2026-11-01; last at `66185d2e`).
- Evaluator Optimizer preserves independent producer/evaluator identities, exact candidates/findings,
  round bounds and hard acceptance gates. Evidence:
  `mission-control-general/workflow-types/04-EVALUATOR_OPTIMIZER.md:55–70,117,135–152` (deleted 2026-11-01; last at `66185d2e`).
- Linked missions retain their own goals, grants, budgets and acceptance. Launch readiness is distinct
  from result readiness. Child Portal remains a bounded reference/status/blocker/budget projection.
  Evidence: `mission-control-general/workflow-types/06-MISSION_INVOCATION.md:24,73,90–98` (deleted 2026-11-01; last at `66185d2e`).

## Question dispositions

All retained recommendations remain unaccepted until answered. Wire naming and source-discoverable
facts do not consume the twenty-question budget.

| Slot | Disposition before questioning |
| --- | --- |
| F20-01 | Keep explicit conditional multiplicity choice. Unknown/else behavior is already settled. |
| F20-02 | Keep explicit dataset population policy; distinguish it from workflow any/all/quorum release. Use source/retrieval receipts as an illustration, not a required mission. |
| F20-03 | Keep semantic preservation/coverage across partitions or summaries. Permit justified independence, reconciliation or explicitly limited claims; do not demand universal factual completeness. |
| F20-04 | Skip as settled by OC-D34/47. Reconcile early eligible exports with final composite acceptance in the specification. |
| F20-05 | Keep. Invocation annex §9 prohibits provisional cross-mission supply; general repair access does not silently repeal it. Chain execution_complete/provisional behavior is baseline inconsistency, not qualified exception. Required repair input must stay required even when held. |
| F20-06 | Keep as a deliberate change from current cancel_downstream default. Retain spawned-child cancellation and attached-child detachment as separately settled rules. Evidence: `domain/composition/chain.py:142`; `application/chains/reducer.py:219–236`; `tests/unit/chains/test_chain_reducer.py:330`. |
| F20-07 | Keep qualification boundary: both applications independently versus additional cross-application links. Shared contracts do not establish receiving authority. |
| F20-08 | Keep initiator of bounded successor partition plans. Preserve success, atomic groups and explicit lineage; changed inputs are not a retry. |
| F20-09 | Tighten: favor ready consumers only when this demonstrably relieves constrained intermediate capacity. Consuming immutable evidence need not delete or free retained bytes. |
| F20-10 | Tighten recommendation to defer automatic same-run memoization specifically. Required idempotency, recovery, selective carry-forward and explicit reuse remain. |
| F20-11 | Keep durable transition reactions as ordinary admitted executions; Temporal remains scheduler. |
| F20-12 | Decide scoped backend reads after the hook model is established. |
| F20-13 | Decide staged local preparation/install versus scoped direct sandbox mutation; distinguish external effects. |
| F20-14 | Keep ordinary admitted operations versus directly effectful scripts as an additional execution surface. |
| F20-15 | Conditional skip: persistent attributed notes may follow directly from F20-11..14. Do not spend a question on an already selected output path. |
| F20-16 | Keep validated compaction-preservation proposals; current callbacks only observe. Keep in-session compaction distinct from continuation. |
| F20-17 | Keep optional automatic selected content; inspection and actionable wake defaults already accepted. Keep notice, transport, host wake, model delivery, ack and content read distinct. |
| F20-18 | Keep explicit disposition of specialized code integration engine; generic code outputs/checks remain regardless. Low priority if a more consequential clarification needs the slot. |
| F20-19 | Correct baseline and ask only about an integrated extension of existing preflight. Broad coordinator redesign stays deferred. |
| F20-20 | Reserve integrated confirmation after concrete contracts, work/proof matrix and dispositions are drafted. |

ADR-0049 remains proposed (`docs/adr/0049-deprecate-mission-subscribe-push-in-favour-of-inbox-wait-channels.md:6,13`).
ADR-0026 is accepted but its broad deny claim requires an event-specific disposition:
a post-effect hook cannot undo the effect (`docs/adr/0026-hook-scripts-one-event-vocabulary-projected-per-lane.md:23`;
`src/mission_control/domain/capabilities/hooks.py:158–175`).

## External primary-source cross-check

Sources read on 2026-10-26 through Firecrawl; architecture evidence, not a proposal to adopt either engine.

- Apache Beam documents that its distributed CombineFn requires associative/commutative combination,
  allowing partial aggregates. This supports the already accepted restriction that automatic tree
  optimization needs qualified equivalence; it does not justify automatic semantic summarization trees.
  [Apache Beam Combine](https://beam.apache.org/documentation/transforms/java/aggregation/combine/).
- Ray Data describes streamed blocks, readiness/resource/backpressure scheduling and throttling when
  buffered data grows. This supports considering explicit backpressure independently of concurrency.
  It does not prove that consuming MC's retained reports frees durable storage or model context.
  [Ray Data internals](https://docs.ray.io/en/latest/data/data-internals.html).

These are analogies used to challenge the proposal. MC retains Temporal scheduling and its own
obligation, exact selection, custody and retention contracts.

## Next action

**Historical pre-question instruction.** The interview has since recorded OC-D162–176; 17 questions
asked, 15 answered, with F20-18/19 pending. The live instrument owns accounting. In the original
wording below, “cross-application” meant coverage of both application implementations; OC-D167
explicitly leaves links between applications unadopted. It must not become a transfer requirement.

Begin with F20-01..03, three independent consequential decisions. Preserve exact answers in IA-09,
starting OC-D162. Continue linked/composition questions, then selected optimization/hooks/coordinator
scope. Keep the final model and proof matrix cross-workflow and cross-application; do not reduce them
to a single discovery example. Real owner fixtures arrive after the interview.

## Integrated-draft review, 2026-10-26

Three read-only reviewers checked the current graph/workflow, hook/coordinator and historical-document
folds. Corrections applied before final confirmation:

- Retain admitted provisional synthesis of held content while the illustrated official-use consumer
  blocks. Keep the narrower linked-mission repair/review exception distinct.
- Remove a circular qualification dependency: exact generic delivery/evaluator isolation enables
  trusted assessment; protected-use success is then proved with that authority. Saved-result
  settlement proves no cognition redispatch; native no-duplicate-application belongs to effect recovery.
- Add the integrated direct/nested/collection/reduction/Swarm/EO/link/hook/coordinator walkthrough,
  exact historical repair-fork proof and an explicit eight-form conformance map.
- Separate local hook preparation from durable-transition reaction dispatch. Add causal-loop limits,
  concurrent candidate installation and crash/source/grant-change cases. Preservation proof requires
  proposals actually reach post-compaction model-visible context, not merely that pressure occurred.
- Keep OVE-75/78 baseline machinery distinct from new preservation/content/inspection deltas. Read
  incoming native dependencies and parent, then preserve them. Actual host unavailability/dead-letter,
  transport, resume, model visibility, acknowledgment and retrieval remain separate evidence.
- Fold dated current rules at conflicting locations in the older output/provenance/coordinator
  documents while preserving original owner quotations and recommendations. ADR-0049 stays proposed.

The parent specification and 22 per-slice issue drafts are local only. F20-18/19 and final confirmation
remain pending. No runtime implementation, fixtures, migration, tracker mutation, commit or push occurred.

