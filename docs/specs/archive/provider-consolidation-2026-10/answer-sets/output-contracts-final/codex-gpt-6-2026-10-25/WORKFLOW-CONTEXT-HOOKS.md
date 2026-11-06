---
type: Implementation Evidence
title: "Workflow context and Deep Agents hooks: detailed interview evidence"
description: "Source findings for GoalDirected, StageGraph dependencies, hook-state access and coordinator output delivery; current behavior, accepted contracts and pending choices remain distinct."
tags: [mission-control, interview, goal-directed, stagegraph, hooks, context-transfer]
date: 2026-10-26
status: active
---

# Workflow context and hooks: evidence for the detailed rounds

OC-D132 in [ANSWERS](ANSWERS.md) expands the interview before final confirmation. This is read-only
source analysis on MC `1863017c`, assisted by GPT 6.1 Sol explorers, **not runtime proof or owner
acceptance of the proposed choices**. No tests, provider calls or runtime edits were performed.
Source paths below are MC-root-relative; [CONTRACTS](CONTRACTS.md) carries accepted shared semantics.

## 1. Distinct mechanisms

| Mechanism | Scope and authority |
| --- | --- |
| Authoritative workflow state | Objective/revision, obligations, accepted current set, findings, blockers, effects and budgets; host-owned. |
| Exact content delivery | Selected output/source revisions under consumer purpose, placement and access; host sealed plan and application custody. |
| Workspace/history restoration | Explicit files/snapshot/journal/checkpoint with lineage, availability and recovery rules. |
| Provider conversation/compaction | Within-invocation messages, summaries and tool results; cannot invent durable acceptance. |
| Hook feedback/preparation | Event-specific observations, guards or bounded context feedback; event and admitted capability determine access/effect. |
| Coordinator observation/retrieval | Durable bounded notices plus exact on-demand reads; notice delivery is not full output loading or use authority. |

## 2. GoalDirected

| Boundary | Accepted contract / current source gap |
| --- | --- |
| First executor | OC-D122 initial admitted task/state/sources, no invented predecessor. `adapters/temporal/workflows/goal_directed.py:449–470` prepares iteration/session/workspace/handoff; `application/context/pack_service.py:1272–1325` renders active objective/tactics/subgoals/coverage. Full new obligation/frontier/profile composition remains work. |
| Executor → verifier | OC-D50/73 require goal-wide current-set assessment and applicable evidence reuse. Workflow `:530–545` currently passes only latest executor output refs; packer `:402–409,431–450` makes those provisional, not mandatory. That is a gap, not a policy revision. |
| Accumulation | `domain/programs/goal_directed.py:280–281` makes a historical ordered union; `:741–754` terminal proposal uses current execution refs. Neither establishes distinct accepted heads/count/coverage. |
| Next executor / repair | Packer `:642–658` builds handoff-derived Loop State; `:682–687` Progress Review is optional/untrusted; `:457–485` uses latest handoff artifact refs. Required canonical findings/current accepted frontier must not depend on producer prose. |
| Dynamic instructions | Packer `:1292–1324` active goal contract is admitted; `:1329–1338` model-authored progress/continuation suggestions are untrusted. Preserve this distinction. |
| Compaction/continuation | Normative typed state, exact refs, pending work/review, cursor, budgets/capabilities/invariants in `mission-control-general/workflow-types/08-CONTINUATION_COMPACTION_AND_TRANSFER.md:80–105` (deleted 2026-11-01; last at `66185d2e`). Domain `goal_directed.py:415–453` rollover rules do not prove every new field survives. |
| Fork | Domain `goal_directed.py:134–175` validates starting positions; full accepted/draft frontier selection, adoption and receiving-authority mapping still need explicit design/proof. |

The Goal Loop journal/Loop State contract is in `mission-control-general/workflow-types/02-GOAL_LOOP.md:43–79` (deleted 2026-11-01; last at `66185d2e`);
typed rejection versus infrastructure retry/wait is at `:191–198`.

**Illustration, not an owner fixture:** goal requires A/B/C reports. Iteration 1 accepts A1, holds B1,
and leaves C missing; iteration 2 repairs B2 and produces C1. Goal verification must account for
A1+B2+C1 and reuse applicable A1 evidence. B1 is selected repair/history, not a second accepted report.
FC-Q22a/b are now accepted as OC-D133/134: three working views with bounded inline state and a
complete exact accessible index; independently runnable work may continue while affected obligations
wait, preserving invocation/global barriers and final goal acceptance. See [CONTRACTS §16.1](CONTRACTS.md#161-goaldirected-working-views-and-independent-progress).

FC-Q22c/d are now accepted as OC-D137/138: require the compact attributed progress note in the
continuing GoalDirected default profile and include selected exact historical drafts/files in the
repair-fork default. These are target profile decisions, not implementation claims. Existing journal
summaries (`02-GOAL_LOOP.md:43–79`) are a foundation; normal-handoff enforcement and crash recovery
must realize the new contract. Exact fork coordinates and receiving authority remain required;
selecting draft bytes cannot itself adopt obligations or transfer effect ownership. See
[CONTRACTS §16.3](CONTRACTS.md#163-goaldirected-progress-notes-and-repair-fork-defaults).

## 3. StageGraph

Normative source: `mission-control-general/workflow-types/01-STAGE_GRAPH.md:31–64,85–167` (deleted 2026-11-01; last at `66185d2e`).

| Case | Current evidence and unresolved detail |
| --- | --- |
| All/any/quorum | Manifest accepts these (`domain/authoring/manifest.py:707–756`); blueprint/interpreter supports ALL/ANY/MINIMUM. Ordinary `manifest_lowering.py:366–398` passes depends_on only; `stagegraph_builder.py:67–100` hardcodes required/all and first producer output. Parsed grammar is not end-to-end support. |
| Edge classes | Required/degradable/optional/advisory in `domain/authoring/contracts.py:317–327,533–599`, interpreter `:163–224`; ordinary builder emits required only. Edge release classes are distinct from output-obligation enforcement. |
| Named inputs | Retained by `mission_definition.py:621–643`, but scheduling builder picks first producer output/from-producer slot. RV-03 run-wide knowledge delivery remains separately unfixed. |
| Ordering/state/evidence/workspace | Normative separate relationships; low-level StageDependency couples producer output and input slot. Ordering alone cannot imply content delivery, workflow state, evidence validity or workspace restoration. |
| Conditional | No general conditional dependency-expression field found in StageJoin/StageDependency. Human/event waits are not the complete typed-predicate/branch contract. |
| Provisional | Binding field exists, but interpreter `:1190–1201` emits provisional=false. No complete early release/taint/invalidation/effect restriction path demonstrated. |
| Fan-out/fan-in | Static join/concurrency foundation exists. Dynamic expansion requires committed template, stable identities and cardinality bounds; ordinary execution not established. Any/quorum needs member cutoff, slow-sibling and late-arrival semantics. |
| Cycles | Structural cycles refused (`contracts.py:917–929`); stage/workflow readmission/invalidation (`interpreter.py:526–604,673–720`) is not proof of normative arbitrary bounded Revisit Region topology. |
| Incremental/revisions | Accepted complete-by-default and explicit incremental release, track/snapshot, distinct identity/coverage remain. Current accepted-result/released-by records do not implement all current-set semantics. |
| Held inputs / siblings | Optional/degradable release does not grant official use. Consumer purpose, exact selection and current eligibility remain separate. `application/knowledge/toolset.py:376` still selects run-wide finalizations. |

FC-Q23 must make operational choices concrete: qualifying members and deterministic any/quorum cutoff,
slow siblings, incremental trigger and immutable receiving snapshot, unknown/impossible conditions,
provisional propagation, running-consumer revision handling, cycles and bounded dynamic expansion.
Retain prior accepted policy; mark any proposed scope revision explicitly.

## 4. Deep Agents executable hooks

Pinned and installed Deep Agents is **0.7.5** (`uv.lock:1012–1013`, installed dist-info METADATA).
These hooks are **MC middleware**, not a claim that stock Deep Agents has the same shell-hook API.
Accepted ADR-0026 specifies the common vocabulary, lane projection and kernel-first execution.

- Admission pins bundle/digest, entrypoint, interpreter, events/matcher, timeout, fail-closed and effect
  class (`domain/authoring/contracts.py:1847–1890`). sh/bash/Python/Node are supported interpreter
  choices (`domain/capabilities/hooks.py:58–62`); .sh alone does not supply a shell on the worker.
- Worker subprocess uses JSON stdin/stdout, scrubbed environment and timeout
  (`adapters/deep_agents/hooks.py:124–180`). Verified files live in a private `mc-hooks-*` directory
  (`materializer.py:554–631`), also the hook cwd/workspace_root. It is **not automatically the agent's
  state-backend or remote sandbox**.
- Input has scope/run/activation/attempt/generation/execution/session, event details, optional tool
  args/result excerpt/error and callback (`contracts/hooks.py:35–77`, `hooks.py:630–651`). Full
  conversation, output ledger, transfer plan and complete agent workspace are not automatically passed.
- Four fixed kernel hooks (stop fence, operation intent, frame capture, usage) precede catalog scripts
  (`domain/capabilities/hooks.py:402–422`, `hooks.py:664–690`). Kernel denial short-circuits.

| Events | Current effect/limit |
| --- | --- |
| session_start, before_prompt, before_model | Pre-model events inferred from message shape; additional_context appends a HumanMessage (`hooks.py:815–848`). |
| after_model, stop, session_end | After response; final-response classification emits stop/session_end. Deny may replace response; additional_context ignored (`:851–888`). Not Temporal operation completion or durable settlement. |
| before_tool, before_shell, before_mcp, subagent_start | Pre-call guard/argument update. Subagent events wrap task tool, not every asynchronous child lifecycle (`:776–795,892–960`). |
| after_tool, after_tool_failure, after_shell, after_file_edit, subagent_stop | Observe completed tool activity; cannot undo committed effects. Tool-path additional_context appends to ToolMessage (`:902–914`). |
| before_compaction, after_compaction | Observations include counts/cutoff/summary digest/path/token estimates; returned HookResult discarded (`adapters/deep_agents/compaction.py:219–220,240–280,297–298,315–316`). No current summary replacement or transfer-plan rewrite through return values. |

Mapped enforceable events: session_start, before_prompt, before_model, after_model, before_tool,
before_shell, before_mcp, subagent_start, stop, session_end. Remaining events above are observe-only
(`domain/capabilities/hooks.py:151–174`). Generic results allow deny/defer/allow, context text and input
updates; merge is deny > defer > allow, concatenated context, last updated_input wins
(`contracts/hooks.py:80–166`). Event-specific consumers determine actual effects. Timeout/malformed
output follows fail_closed; invocation/result frames are retained.

FC-Q24 needs separate choices for in-turn guards/cues versus durable workflow-boundary automations;
bounded state projection/read capability/backend access; attributable preparation outputs versus
requests to alter compaction/transfer; and side-effect/retry/failure policy. Hook text or a written file
cannot silently become accepted output, fulfilled obligation or sealed-transfer authority.

## 5. Coordinator output delivery

OC-D125/126 accept exact on-demand inspection and durable actionable-default notifications. They do
not promise full report bodies automatically entering the coordinator prompt or idle-chat wake-up
without a qualified host path.

`application/subscriptions/coordinator.py:68–96` includes accepted_output and actionable kinds;
`:122` restricts facts to scalar classifications; `:193–244` defines bounded notification/event refs;
`:692` renders reference-only prompts without payload bodies. Persisted notice, wake hint, delivery,
acknowledgment, model-visible wait result and full report retrieval are separate facts. Generic
accepted_output support is not proof all new submission/fulfillment/transfer transitions reach it.
`application/coordinator/coordinator_results.py:61–180` terminal result reads are not the whole
progressive/current-set output inspection surface.

FC-Q25 refines subscribable transitions, exact refs/status/gaps in notices, retrieval of selected full
content, admitted inline alternatives and coordinator context budget/authority. Retain replay/ack and
cancellation. Routine output traffic is batched by default; explicitly configured subscriptions remain
supported. Selecting a coordinator host during fixture integration requires actual wake proof there.

## 6. Linked workflow context: handoff audit

OC-D135 explicitly expands the frontier to linked and intra/inter-workflow transfer. The detailed
[handoff §10](INTERVIEW-HANDOFF-2026-10-26.md#10-linked-workflows-and-nested-composition-explicit-new-frontier-fc-q26)
distinguishes nested ProgramNodes, Child Mission Invocation, linked-run composition, mission chains,
continuation/fork and provider subagents. It retains source anchors and proposed interview topics.

Additional read-only findings at MC `1863017c`:

- `application/chains/packet.py:84–95` uses filename/stem/path matching and can fall back to all
  accepted artifacts for one binding. This falls short of the already accepted exact-selection policy.
- Same `:191–208` does not visibly use the receiving input_name in the binding loop; verify alias
  delivery. Same `:178–197,214` makes provisional supplies nonmandatory, whereas required repair
  inputs must distinguish delivery necessity from acceptance/official-use status.
- `application/programs/linked_runs.py:262–295` independently compiles/admits child configuration;
  `bootstrap/worker.py:565–569` and `adapters/temporal/linked_run_activities.py:69` wire the service.
  Wiring is not full transfer qualification; older no-production-caller language is historical.

No runtime/provider calls were made. FC-Q26 recommendations are not accepted merely by inclusion here.
