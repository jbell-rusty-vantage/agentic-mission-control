---
type: Specification Supplement
title: "Human review gates and steering: what the owner can do at a review point, how it is modelled, how it joins output contracts and Mission State Transfer, and the interviews to run before building"
description: "Supplement to SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md (P1 deep_agents, revision 2). Answers the owner's 2026-10-22 questions about a human-in-the-loop review node inside a workflow and between linked workflows: the exact capability set (one verdict plus typed riders: feedback, context injection at unit, downstream and mission scope, deliverable amendment, configuration amendment, revise from the finished point), the boundary law that decides what needs a revision, the review assistant the owner talks to, persistence and events, the coordinator authoring and search surface, a worked Stage 3 / Stage 4 example, the amendments to the output-contracts specification, decisions HG-D1..HG-D24, the build order and proofs, and nine interview rounds plus two rehearsals to hold before implementation. Written 2026-10-22 from a read-only audit of platform/mission-control; nothing in mission-control was changed."
tags: [mission-control, human-gate, human-task, review, steering, human-in-the-loop, output-contracts, context-transfer, revisions, mission-chains, coordinator, supplement, proposal]
companion: docs/specs/archive/provider-consolidation-2026-10/specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md
---

# Human review gates and steering

**Status.** Proposal, 2026-10-22, for the owner to settle through the interviews in §12. Nothing
is decided and nothing was built. This file is written at the root of `platform/` because
Mission Control is being worked on in another session. It is meant to move into
`mission-control/docs/specs/provider-consolidation-2026-10/providers/deep_agents/` beside its
companion when that session is done. Paths without a prefix are under
`mission-control/src/mission_control/`.

**Companion.** [SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md](../archive/provider-consolidation-2026-10/specs/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md)
is cited as **OC §x** (decisions OC-D1..D26). The owner interview
[OWNER-INTERVIEW-2026-10-22.md](../archive/provider-consolidation-2026-10/interview-instructions/OWNER-INTERVIEW-2026-10-22.md)
is cited as **INT Rx**. The coordinator-surface proposal is cited as **CS §x**. This supplement
uses the companion's vocabulary unchanged: obligation, deliverable, fulfillment, Mission State
Transfer (MST), depth layers, transfer tier, release kind, transfer points T1-T10. It covers
transfer point **T10 (human review)**, which the companion names in one table row (OC §4.0,
§4.3, INT R1b) and does not design. It also adds review between linked missions (T9 plus T10).

**Labels.** **[T]** a named test exists. **[I]** implemented, unproven live. **[D]** documented
or specified only. **[P]** proposed here.

## 0. The owner's request (verbatim, 2026-10-22)

> *"We need to architect the special human in the loop checkpoint program node that can be part
> of a workflow. It could also work between workflows. We should be able to link workflows
> through this Human in the loop program node so that I could review and then approve or reject
> with feedback and also I could inject context (agent context and mission context). I want to
> also be able to speak to an agent at this review point so that it can help me supply the
> results. I will be telling the coordinator agent explicitly that I want these checkpoints in
> the mission or linked missions."*

> *"Stage 3 results in some report and this is a checkpoint for my interaction. Let's say Stage 4
> is blocked. What can I do? First off I have an agent to help me. [...] The agent will have
> mission control skills and can fulfill my request. [...] I can simply approve with feedback and
> this unlocks the next stage (or finishes the workflow) and passes my review as extra context.
> Can I add capabilities and edit the context of the next stage besides my feedback? Now what
> about rejections or commands to try again? What if I reject with feedback? Can I edit the
> configuration of the stage or goal directed iteration that will go again? That stage doesn't
> start from scratch it starts from its finished point + my feedback + a new configuration
> right?"*

> *"This is so important for me to part of the process and to guide these missions. How should
> we model this? How do we make configurable and searchable for the coordinator agent so it is
> easy and comprehensible to create these special checkpoint nodes?"*

---

## 1. The answer in brief

### 1.1 What you can do when Stage 3's report is waiting and Stage 4 is blocked

A review point gives you **one verdict** and any number of **riders**. The verdict decides what
the graph does next. The riders decide what the next unit receives and how it is configured.
Your assistant agent can draft all of it. You submit it, and the submission is attributed to
you.

| You want to | Verdict + riders | Needs a revision? | What happens |
| --- | --- | --- | --- |
| Accept the report as it is | `approve` | no | Stage 4 is released with Stage 3's deliverables and the approval fact |
| Accept and tell Stage 4 something | `approve` + `feedback` | no | Your note reaches Stage 4 inline and mandatory, in an "Owner review" section, attributed to you |
| Accept and add context for Stage 4 | `approve` + `inject{scope: unit:S4}` | no | Instructions, files you attach, or any run artifact, point or transcript excerpt are added to Stage 4's packet |
| Set guidance for the rest of the mission | `approve` + `inject{scope: mission}` | no | A **Mission Note**: every later unit receives it, including Goal iterations and subagents that inherit state |
| Pass on a corrected report | `approve` + `amend_deliverable` | no | Your edited version (or the assistant's draft that you adopt) replaces the binding; the original stays in lineage |
| Change Stage 4 itself: objective, obligations, model, skills, MCP servers, lane features, model tools, subagents, budget, transfer | `approve` + `amend{target: S4}` | **yes**, compiled and validated before the resolution commits | Stage 4 is released from the new scheduling head |
| Send Stage 3 back with feedback | `revise{target: S3}` + `feedback` | no (yes if you also amend) | Stage 3 runs again **from its finished point**: same conversation, your feedback as the next message, its files and outputs in place. The gate reopens on the new result |
| Send it back with a new configuration | `revise{target: S3}` + `amend{target: S3}` | **yes** | The same, under the amended configuration (§4.6 lists the limits: a lane change or a model-provider change cannot continue the same thread) |
| Rewind to before it went wrong | `revise{target: S3, resume: from_point}` | as above | Stage 3 continues from an earlier cognition point that you choose |
| Fix the cause upstream | `revise{target: S2}` (or a region `[S2, S3]`) | as above | S2 re-runs, S3 re-runs after it, and the gate reopens |
| Stop this line of work | `reject` + `feedback` | no | The gate is `not_accepted` and the authored `on_reject` applies: fail the run (default), skip the dependents, or route to a fallback |
| Pick one of several options | `select{option}` | no | Only the branch you chose is released |
| Decide later, or have someone else decide | no resolution, or `escalate`, `reassign` | no | The gate keeps waiting. A timeout is never an approval |
| Change what the mission means | not a steering action | successor mission | The gate offers "conclude and launch a successor/fork" (§4.4, class M) |

### 1.2 The three short answers

1. **Can I add capabilities and edit the next stage's context, beyond feedback?** Yes. Adding
   context is a command (no revision). Editing the configuration is an **amendment**. An
   amendment compiles into a Revision Proposal that must validate and activate in the same
   transaction as your resolution. Your authority bounds what you can add. A Mission Control
   rule already requires this: *"Instructions and Artifact attachments may remain Commands when
   they do not expand authority"*, while adding a skill or an MCP server *"requires a Revision
   Proposal and admission validation"*
   ([revisions](../../knowledge/revisions.md); the annex `workflow-types/07` §6.1 was deleted with the spec pack, last at commit 66185d2e).
2. **Reject with feedback and try again: does the stage start from its finished point plus my
   feedback plus a new configuration?** That should be the default, and it is **not** what
   happens today. Today the re-run stage's objective is *replaced* by a text built from your
   feedback (`domain/programs/human_gate.py:719-731`, `next_objective:
   feedback_instruction(outcome)`). The re-run receives only that string, with no prior state
   (OC §1 fact 6, observed live in Stage 2). This proposal makes `revise` continue from the
   stage's result cognition point. It seeds the new activation's thread from that point, with
   your feedback as the injected message. The precise fork already supports this
   (`ForkSeedRequest.message`, `.files`, `application/execution/harness/time_travel.py:51-67`).
   The original objective, your feedback, the prior fulfillment report and the amended
   configuration are delivered beside it.
3. **How should we model it?** It is not a new kind of node. It is the existing **Human Gate**
   durable control of task kind `REVIEW`, which this document calls a **Review Gate**, given a
   typed **Steering Resolution** (one verdict plus riders) in place of today's
   `approve | deny | request_changes` plus a comment. The coordinator authors it with a
   `review:` block or a catalog **review template**, and the compiler always makes the gate
   explicit (§4.1, §8).

---

## 2. What exists today (audited read-only, 2026-10-22)

| Piece | State | Label |
| --- | --- | --- |
| Human Gate rules | `domain/programs/human_gate.py`: `HumanGateSpec` (`gate_key`, `task_kind` APPROVAL, QUESTION, SELECTION, REVIEW, POLICY_OVERRIDE; prompt; reviewers; packet sources; `timeout_seconds`; `on_timeout` keep_waiting, escalate, default_answer, stop; `remediation_target`; `max_review_rounds` ≤ 20). The decisions are `approve`, `deny` and `request_changes`. `request_changes` needs a remediation target and a round left. The refusals are typed: `already_resolved`, `not_reviewer`, `stale_version`, `packet_digest_mismatch`, `feedback_required`, and others | [T] `tests/unit/human_tasks/test_human_gate_rules.py` |
| The control activation | `adapters/temporal/workflows/human_gate.py` (`mc.human_gate.v1`). It waits on a signal hint or a 300 s poll and holds no cognition slot. Each activation and round gets one uuid5 task id | [T] `tests/integration/temporal/test_mp10_human_gate_restart.py` |
| Stage Graph gate | A stage named in `StageGraphRunInput.human_gates` runs as the gate (patch `mp10-stagegraph-human-gate`). `accepted` completes the stage with `output_refs: [resolution_ref]`. `changes_requested` completes it with `evaluation: cycle`, `invalidation_frontier: [remediation_target]` and `next_objective: feedback_instruction(...)`. Anything else fails the stage, and a denial fails the run (`stagegraph_gate_result`, `human_gate.py:695-740`) | [T] |
| Goal Loop review | With `GoalDirectedRunInput.human_review`, a verified completion proposal opens one review. It is synthesized as `goal-review`, with the `owner` reviewer and remediation target `goal/executor` (`application/programs/human_gates.py:78-103`). `request_changes` continues the loop with the feedback as an `UNTRUSTED_CONTENT` executor prompt segment (`application/programs/goal_directed.py:1539-1558`), and the counters carry on. A rejection fails the run (`domain/programs/human_review.py`) | [T] `tests/unit/human_tasks/test_goal_review.py` |
| Gate lowering and packet | A manifest gate becomes a Stage Graph stage with a pre-satisfied wait (`domain/authoring/manifest_lowering.py:329-332`) and the implicit output `resolution` (`application/authoring/manifest_service.py:237-238`). Its review packet is the declared `packet`, otherwise the producer's outputs (`adapters/temporal/workflows/stagegraph.py:1507-1539`). Review rounds are capped at the blueprint's `max_cycles + 1` (`stagegraph.py:1499-1502`). A waiting gate holds no budget: its reservation is released against zero usage | [T] |
| Cycle re-run mechanics | `stage_invalidation` **requires a `next_objective` different from the current one** (`domain/programs/interpreter.py:580-583`). Each cycle visit gets a new unit key at generation 1 (`domain/execution/cognition_points.py:173-174`); the prior attempt is lineage only (`StageContinuesFrom`, a `cycle_start` point parent). So a re-run is a fresh start | [T] |
| Edited approvals (tool calls only) | Approval-origin tasks already admit `approve_edited` with edited arguments, answers and elicitation content (`application/execution/approvals.py:606-622`). This is the precedent for "approve with edits", but it does not exist for workflow gates | [T] |
| Feedback form | `feedback_artifact_refs` (artifact refs) plus a `comment`. The comment is rendered `"Reviewer comment (untrusted content): ..."` (`human_gate.py:619-633`) | [T] |
| Manifest | `HumanGateNode{behavior: human_gate, task: HumanTaskSpec{kind, prompt, reviewers, packet: [OutputRef], timeout, on_timeout}}` (`domain/authoring/manifest.py:841-852`). It cannot express a remediation target or a default answer, so a manifest gate admits only `approve` and `deny`. `request_changes` is a typed refusal (MP-20 V09, `docs/knowledge/human-gates.md` "Gaps") | [T] |
| Transports | One `HumanTaskService` (`application/human_tasks/service.py`). HTTP `GET/POST /human-tasks...`, the Socket.IO `resolve_human_task`, and MCP `mission_human_task_list\|get\|resolve`. **No `missionctl human-task` group.** The technical coordinator mount has no tenant-scoped Human Task service | [T] / gap |
| Tables | `human_task` and `human_resolution` (migration 0005): typed request packet, `kind`, `assignee_scope`, `deadline_at`, `on_timeout`, and an `answer` JSON with digest, `actor_ref` and `expected_task_version`, exactly once per task | [T] |
| Events | `human_task.opened` (alias of `created`), `resolved`, `expired`, `cancelled`, `escalated`. Inbox kinds `review_required` and `review_closed` wake a coordinator (`domain/subscriptions/significance.py:12-27`) | [T] |
| Revisions | Tables exist (`0002_authoring.sql`: `revision_proposal`, `mission_revision`, `compiled_program`; `0003_execution.sql`: `run_revision_transition`). **No proposal, validation, activation, transition-impact or carry-forward service exists in `src/`** (`docs/knowledge/revisions.md` "Implemented today") | [D] |
| Mailbox | `queue_instruction` and `add_context` deliver mandatory `queued_instruction` packet items at the next family boundary. An entry with a `node_key` is delivered at that stage's next Stage Graph admission (`domain/policies/mailbox.py:233-258`) and folded into its sealed Context Packet (`application/programs/service.py:1764-1785`). **This is already a working carrier for a unit-scoped inject into a stage that has not started** | [T] |
| Pending-stage configuration | Stage templates are frozen per semantic input binding (`application/programs/service.py:1732-1737`), so a pending stage's objective, capabilities, skills or model cannot change mid-run. The closest mechanism is a **fork**: it can patch `stage_objectives.<stage>` (`application/programs/fork_templates.py`), and the family fork policy admits changes to `input_manifest` and `effective_configuration_digest`, which invalidate every unit (`domain/policies/forks.py:1009-1030`). That is a new run, not a revision | [T] |
| Catalog search | Coordinator MCP `search_capabilities`, `pin_capability`, `get_capability` (`interfaces/mcp/coordinator_server.py:344-419`) over hybrid search with lexical fallback (`application/capabilities/capability_search.py`). `DefinitionKind` (`domain/authoring/contracts.py:67-91`) has no template or review kind. A new kind needs the enum, the `asset_version.kind` constraint (migration 0025) and the search projection. The **operator** MCP has the Human Task and fork tools but **no catalog tools** | [T] |
| Fork from a point | `seed_fork` copies the source thread's root lineage up to a point into a derived namespace. It supports an injected `message` and `files` (`adapters/deep_agents/time_travel.py:274-…`). It requires the point to carry `belllabs_binding_digest` and `belllabs_state_schema_digest`. The request's `binding_digest` is optional and is "known at launch, not at fork time" | [T] |
| Chains | `ReleaseCondition` = `goal_accepted`, `mission_accepted` or `execution_complete`. A `supplies` link waits for accepted output evidence. The chain packet (`purpose: chain_link`) carries supplied artifacts, disposition, final checkpoint and transcript retrieval (`docs/knowledge/mission-chains.md`). **No human gate on a link** | [T] |
| A reviewer's assistant | None. The coordinator can reach Human Tasks only through the development MCP server. There is no review-session concept and no draft resolution | — |

**What this means for the owner's three questions:** you can approve and reject now. On the
Stage Graph from a manifest, you cannot send work back (V09). Your feedback is labelled
untrusted. When you do send work back (from a non-manifest launch or on the Goal Loop), the
re-run stage loses its objective and its prior state. You cannot inject scoped context at the
gate, and you cannot amend configuration, because no revision service exists. Nothing exists
between linked missions. Nobody is there to talk to.

---

## 3. Vocabulary

The glossary already decides the most important naming question. It lists **Human Gate** with
*"Avoid: approval node, checkpoint (the LangGraph word)"* (`GLOSSARY.md:185-187`). **Checkpoint**
is taken by Continuation Checkpoint (`GLOSSARY.md:442-444`), and the LangGraph saver and the
cognition points sit nearby. The owner's word "checkpoint" therefore stays the product word, for
example in a dashboard ("review checkpoint"). The kernel terms are:

| Term | Meaning |
| --- | --- |
| **Review Gate** | A Human Gate whose task kind is `REVIEW` and which declares a **steering policy**. It is a durable control program node: it waits, does no work, and holds no cognition slot. It reviews named **subjects** (one or more units' deliverables, or a whole mission at a chain link) and blocks the **dependents** that depend on it. |
| **Review Packet** | The frozen, digest-addressed bundle the reviewer sees (§4.2). It extends today's `HumanGateActivation` packet. |
| **Steering Resolution** | `mc.steering_resolution.v1`: exactly one **verdict** plus zero or more **riders**, attributed to one principal, bound to the task version and packet digest. It is the `answer` of the existing `human_resolution` row. |
| **Verdict** | `approve`, `revise`, `reject` or `select`. The Human Task still resolves `review_accept` or `review_reject` (ADR-0038, `05` §6.3); the verdict is the payload and does not create a second state machine. |
| **Rider** | A typed addition to a verdict: `feedback`, `inject`, `attach`, `amend_deliverable`, `amend`, `transfer`, `budget`, `fork`. Each rider has a **change class** (§4.4). |
| **Steering Effect** | The recorded application of one rider (an applied or refused row), written in the resolution transaction. The transfer policy reads these rows. |
| **Mission Note** | A context item an owner writes at `mission` or `chain` scope. It is inline and mandatory for every later unit until superseded. It is evidence, not authority. |
| **Review Assistant** | The agent the owner talks to at a review gate. It reads, explains, checks, drafts and previews. It never resolves on its own (§5). |
| **Review Draft** | A versioned, unsubmitted Steering Resolution that the owner and the assistant edit together. It is what a dashboard will show later. |
| **Review Round** | One opening of the gate on one packet. A `revise` verdict closes a round and the re-run opens the next one (today's `review_round`, at most `max_review_rounds`). |

**Agent context versus mission context** (the owner's two scopes). Agent context is an `inject`
whose scope names a unit (`unit:S4`, `units:[S4,S5]`, `role:executor`). It reaches that unit's
packet once. Mission context is an `inject` with scope `mission` or `chain`, which creates a
Mission Note that persists. Both are owner-attributed instructions, not untrusted content and not
grants (§4.8).

---

## 4. The model

### 4.1 Where a Review Gate can sit

Every form below compiles into an **explicit** Human Gate node in the compiled program. The
spec forbids hidden waits (`01-STAGE_GRAPH.md` §6; `05` §6). The forms differ only in how they
are authored.

| Form | Authored as | Subjects | Blocks | Today |
| --- | --- | --- | --- | --- |
| G1 Explicit node | a `behavior: human_gate` node with `task.kind: REVIEW` and a `steering:` block; dependents `depends_on` it | the units its `reviews:` lists | its dependents | node exists, steering absent |
| G2 After a stage (sugar) | `review:` on a stage | that stage | that stage's dependents, which the compiler rewires to the synthesized `<stage>.review` gate | absent |
| G3 Obligation verification | `verify: human` on an obligation (OC-D25) | that deliverable | `gate` mode blocks the producer's acceptance; `annotate` records a finding and blocks nothing | absent (OC-D25 open) |
| G4 Goal Loop | `review:` on the goal: `at: completion` (exists as `human_review`), `every: N iterations`, `on: verifier_reject \| no_progress` | the iteration's deliverables, verdict and handoff | the next iteration or completion | `at: completion` only |
| G5 Escalation | `on_cap: human_review` (OC §4.4), `on_failure: human_review`, `on_budget: {at: 80%, review}` | the stage or loop that hit the limit | the same | absent |
| G6 Chain link | `review:` on a `links:` entry | the upstream mission's supplied deliverables and disposition | the downstream mission's start | absent |
| G7 Ad hoc hold | `missionctl run hold RUN --before S4` at runtime | what S4 would receive | S4 | absent; this is an **added node**, so it is a Revision Proposal (§4.4) |

Independent branches keep running while a gate waits (`01-STAGE_GRAPH.md` §7: *"A failed required
Stage does not automatically fail the graph. Independent branches continue."*). A gate may
declare `hold: run` to pause everything at the next boundary instead. Its default is
`hold: dependents`.

### 4.2 The Review Packet: what you and the assistant see

The packet is a transfer of its own. Its consumers are the reviewer and the assistant, so it
uses the companion's depth layers. Its new `purpose` is `review_open`.

| Layer | Content | Tier |
| --- | --- | --- |
| Deliverables | the subjects' fulfilled obligations as promoted `artifact` rows (OC §3.5), downloadable | reference with summary, materialized into the assistant's workspace |
| State | per subject: the fulfillment report, verifier verdicts and typed findings, unmet obligations, budget used and remaining, cycle and round ordinals; **the next-up set**: each dependent's current configuration, obligations and the transfer plan it would receive now (a dry-run `plan_transfer`, OC §4.2); the **permits** (what this gate allows, §8.3); prior rounds' resolutions | inline |
| History | the subjects' transcripts (`missionctl run transcript --by stage`), cognition points, the upstream lineage | reference with working handles |

The packet is frozen at gate open (`packet_digest`, as today). A resolution against an older
digest is refused `packet_digest_mismatch`, as today. A revise round produces a new packet. The
dry-run plan of the next-up set is what makes "edit the context of the next stage"
understandable: you edit something you can see.

### 4.3 The Steering Resolution

```yaml
# mc.steering_resolution.v1, the `answer` of human_resolution (digest-bound, attributed)
gate: s3_review
round: 1
expected_task_version: 4
packet_digest: sha256:…
verdict: approve                       # approve | revise | reject | select
select: null                           # option key, only for select
revise: null                           # §4.6, only for revise
on_reject: null                        # override within permits, only for reject
riders:
  - feedback: { text: "Good synthesis; section 3 overstates effect sizes.", attach: [] }
  - inject:
      scope: unit:S4                   # unit:<key> | units:[…] | role:<role> | downstream | mission | chain
      items:
        - instruction: "Lead with the limitations table; audience is clinicians."
        - artifact: artifact://…/style-guide.md      # an owner upload or any run artifact
        - point: point://…                            # a cognition point, rendered as state-as-of excerpt
        - transcript: { unit: S3, steps: "40-55" }    # a transcript slice
  - inject: { scope: mission, items: [{ instruction: "Cite primary sources only from now on." }] }
  - amend_deliverable: { obligation: S3.report, artifact: artifact://…/report-v2.md, note: "fixed §3" }
  - amend:
      target: S4
      set:
        objective: "…"                 # replace (class R); use inject to add (class C)
        model: { provider: openai, name: gpt-6-sol }
        capabilities: { skills: [{ pin: catalog://skills/clinical-writing@2 }] }
        lane_features: { deep_agents: { todo_list: {} } }
        outputs: [{ name: brief, kind: document, cardinality: { min: 2, max: 2 } }]
        budget: { usd: 3.00 }
        inputs: [{ name: report, from: S3.report, expand: materialize }]
  - transfer: { target: S4, history: { from: S3, mode: reference }, include: [S2.notes] }
draft_ref: review-draft://…/v7        # when the assistant helped; evidence, not authority
assistant_session_ref: null
```

**Atomic, all or nothing.** The resolution, its steering effects, the Revision Proposal built
from all `amend` riders, its validation and its head activation commit in **one** transaction,
or none of them do. An amendment that fails validation refuses the whole resolution with typed
issues (`amendment_invalid:<pointer>:<code>`), and the gate stays open. Partial steering would
leave the owner unsure what Stage 4 will see. The `review preview` call (§5.3) runs the same
validation without committing.

### 4.4 The boundary law: what needs a revision

This is the law that keeps a gate from being a loophole. An answer cannot smuggle a policy
change (`05` §6.3), and `request_changes` never mutates the revision or acceptance criteria
(ADR-0038). Every rider has one change class:

| Class | What it changes | Riders | Mechanism | Why |
| --- | --- | --- | --- | --- |
| **C, context** | what a unit *reads* | `feedback`, `inject` (all scopes), `attach`, `amend_deliverable`, `transfer` overrides that only add material already in this run or chain | Steering Effects read by the transfer policy (§9); no revision | `07` §6.1: instructions and artifact attachments may remain commands when they expand no authority |
| **R, configuration** | what a unit *is*: objective text (replace), obligations, model, lane, capabilities (skills, MCP, hooks, plugins, subagents), lane features, model tools, budget and governors, cycle policy, input bindings, graph structure (an added or removed stage, G7) | `amend`, `budget`, `revise` when it carries amendments | a **Revision Proposal** compiled from the riders against the head, validated (including the authority intersection with the reviewer's grants), activated in the resolution transaction; Transition Impact per node (`07` §4.2); in-flight work stays pinned | `07` §4, §6.1 |
| **M, meaning** | the goal, success criteria, acceptance meaning, the mission's authority ceiling, tenant | none | refused at the gate; the gate offers `reject` + "launch successor" or `fork` with a new goal | `07` §6.2-6.3: *"cannot be activated as a Revision of the same Mission"* |

The comprehensible rule for the owner and the coordinator is: **adding is context, replacing
is configuration, redefining success is a new mission.** "Tell Stage 4 to lead with
limitations" is an inject. "Stage 4's objective is now X" is an amend. "Actually the mission is
to produce a grant proposal" is a successor mission.

Two cases sit near the border and are interview items (§12, HR3):

- **Tightening acceptance** (raise `cardinality.min` from 1 to 2, add a validator). `07` §6.2
  allows clarifying or tightening an objective as a revision. Recommendation: class R, permitted.
- **Loosening acceptance** (drop a required obligation). Recommendation: class R only when the
  dropped obligation is no consumer's binding. Otherwise class M.

### 4.5 `approve`

- The gate settles `accepted` with release kind `review_approved`, or
  `review_approved_with_amendments` when any class R rider applied. The release kind is written
  on each dependent's activation (OC §4.3).
- Dependents are released from the current head, which is the new one if amended. They receive
  the subjects' deliverables (or the `amend_deliverable` replacement) per their bindings, plus
  the steering items (§9, H10-H13).
- `approve` on the last gate of a workflow finishes it. Graph acceptance still follows the
  graph's acceptance policy: execution completion is not acceptance (`01` §6). A gate that is
  the graph's declared final acceptance gate makes the owner's approval the acceptance fact.
- When the subjects carry `expected` obligations with shortfalls (OC §3.4
  `accepted_with_findings`), approving accepts the findings explicitly. The resolution records
  `accepted_findings: [...]`, so the shortfall becomes a decision rather than an oversight.

### 4.6 `revise`: try again from the finished point

```yaml
revise:
  target: S3                         # a unit, or region: [S2, S3]; must be within permits.revise_targets
  resume: continue                   # continue | from_point | fresh
  from_point: null                   # point://… when resume: from_point
  carry: { deliverables: materialize, workspace: carry }   # defaults by family, below
```

What the re-run receives, by resume mode:

| | `continue` (default) | `from_point` | `fresh` |
| --- | --- | --- | --- |
| Conversation | the target's thread seeded from its **result point** (`seed_fork`); your feedback is the injected human message | seeded from the point you name; the turns after it remain History | a new thread |
| Its files | in place: the state at the point includes them (Deep Agents state backend) or the workspace snapshot is carried | as of the point | prior deliverables materialized under `/inputs/prior/<obligation>/` |
| State, inline, mandatory | the review verdict and feedback; the **original objective** (never replaced); the prior fulfillment report and unmet obligations; findings; round `n` of `max_rounds`; budget remaining; the list of what was amended | the same | the same |
| Configuration | the head after the amendments | the same | the same |

Upstream targets (`target: S2` or `region: [S2, S3]`) re-run S2 by the chosen mode. Every unit
between the target and the gate then re-runs, because its inputs changed (the existing
`invalidation_frontier` semantics). Those units default to `fresh` with their prior deliverables
referenced. Completed work outside the frontier is untouched, and its carry-forward eligibility
is computed from digests (`07` §5.1). The superseded deliverables stay as artifacts with
`superseded_by_review` lineage and are never deleted.

**When `continue` is not possible.** These rules become compile-time and preview-time issues,
never surprises:

1. **Lane change** (amend `lane`): the thread belongs to the old harness, so the mode degrades
   to `fresh` with a typed notice `resume_degraded:lane_changed`.
2. **Model provider change** (OpenAI to Anthropic): Stage 2 found that every Responses API
   message carries an `encrypted_content` block (OC §1.1). Replaying those blocks into another
   provider is not meaningful. Recommendation: degrade to `fresh` plus a generated handoff, with
   notice `resume_degraded:model_provider_changed`. A model change within the same provider
   continues the thread.
3. **Capability or binding change on the same lane**: this must be verified before building
   (§13). `seed_fork` requires the point's `belllabs_binding_digest` and
   `belllabs_state_schema_digest` stamps. The derived unit's binding is "known at launch". The
   working assumption is that a new binding digest may continue a seeded thread when the
   **state schema digest** is unchanged; a changed state schema degrades to `fresh`.
4. **Codebase work** (`code_change` obligations): the workspace snapshot of the result point is
   carried (OC-D10), so edits accumulate. `fresh` on a codebase node still restores the branch
   head unless `carry.workspace: none`.

**Two interpreter rules change.** Today a cycle is admitted only when `next_objective` differs
from the current objective (`interpreter.py:580-583`), and every cycle visit starts a new unit at
generation 1 (`cognition_points.py:173-174`). A `revise` keeps the objective. Its admission
therefore rests on the typed review fact (the resolution ref and round) instead of a changed
string, which is the same move OC §4.4 makes with `ProgressObservation`. The new activation's
first attempt is pinned to the seeded point rather than to an empty thread.

**Governance.** Review rounds are counted (`max_review_rounds`, at most 20, as today). Today the
rounds are also capped at the blueprint's `max_cycles + 1` (`stagegraph.py:1499-1502`). Whether
a round also counts against the target's cycle cap is interview item HR4.3 (recommendation:
separate counters, ADR-0011's distinct counters). Each re-run consumes the target's budget. A
`budget` rider (class R, `policy_changed`) tops it up. Every revise round must show progress:
the re-run's fulfillment or findings must change, using the progress observation of OC §4.4. A
round with no progress is recorded `no_progress`, which the next packet shows.

**Goal Loop.** `revise` at a Goal review continues the loop (as today, with counters carried
on), with these changes. The executor's thread continues from iteration N's result point, as it
already does through the shared role thread (COGNITION-POINTS §1.2). The feedback is
owner-attributed, not untrusted. `amend` may target `role:executor`, `role:verifier` or the
loop's governors (class R). Amending the goal or its acceptance is class M.

### 4.7 `reject` and `select`

`reject` settles the gate `not_accepted`. The node's authored `on_reject` decides what follows:
`fail_run` (the default, as today), `skip_dependents` (the graph continues on independent
branches), `route:<node>` (release a declared fallback), or `conclude` (the run ends
`not_accepted` without failing infrastructure-wise). A reviewer may choose another `on_reject`
only from the gate's `permits.on_reject`. `reject` requires `feedback`, as today
(`feedback_required`).

`select` exists for gates that declare `options:`, each naming the nodes it releases (a typed
`conditional` release over the gate's fact, OC §4.3). Unselected branches are `skipped`. This is
how a review chooses between two drafts or two plans.

### 4.8 Injection, trust and rendering

Today the reviewer comment is rendered as *"untrusted content"* (`human_gate.py:631`). That is
right for text that arrives from outside, and wrong for the mission owner steering their own
mission. Proposal:

- Steering items carry `provenance: {principal, role: owner | reviewer, via: direct |
  assistant_draft, resolution_ref}`. They are rendered in a dedicated **Owner review** section
  at the top of `/.mission/context.md` and in `/.mission/state.json` under `steering`.
- They are **instructions with attribution, never authority.** They cannot grant a tool, raise
  a budget or change acceptance. Only class R riders do that, through the revision.
- Text the assistant drafted and the owner adopted is the owner's. The draft ref remains
  evidence of how it was written.
- An `artifact` injection may point to any artifact in the run or chain, and to owner uploads
  registered as artifacts with `origin: human`. It never points to a path in another unit's
  workspace (Stage 2's failure, OC §1.1).
- Mission Notes are capped in count and size (installation settings, recommendation: 20 notes,
  4 KB each). They are mandatory, and mandatory items are never truncated (OC §4.2 H3), so an
  unbounded list would eventually fail every packet. A new note may `supersede` an older one.

### 4.9 Between workflows: a Review Gate on a chain link

A chain link already has a release condition and a typed supply (`docs/knowledge/mission-chains.md`).
Proposal: a link may declare `review:`, which adds a link state `awaiting_review` between
`armed` and `released`. The link state machine is forward-only and enforced by a trigger, so
adding a state is a migration (owner executes). The gate is owned by the **chain**. It is a
Human Task scoped to the `mission_chain` and opened by the chain reducer in the same transaction
as the event that satisfies the link's condition. Its subjects are the upstream's supplied
deliverables, disposition, fulfillment rows and transcript handle.

| Verdict at a link | Effect |
| --- | --- |
| `approve` | The link is released; the downstream's first packet (purpose `chain_link`) gains the steering items |
| `approve` + `amend{target: <downstream mission>}` | The downstream member has a frozen admission and has not started, so the amendment produces its **successor revision before first run**. No in-flight work exists, and Transition Impact is trivial |
| `approve` + `inject{scope: chain}` | A Mission Note for every later member of the chain |
| `revise{target: upstream}` | The upstream run is terminal, so the upstream continues as a **derived run** seeded from its final result point (the existing precise fork, `run fork --at --point`) with the feedback. The link is re-armed on the derived run's acceptance. Interview item HR6.2 |
| `reject` | The link is `blocked` (`review_rejected`); `on_upstream_cancel`-style policy decides whether later members are cancelled or detached |

This is also how "link workflows through this node" reads to the coordinator. The link is the
dependency, and the review is its gate. Releasing on a specific upstream obligation
(`requires: <upstream>.<obligation>`, INT R5.1) composes with it.

---

## 5. The Review Assistant: talking to an agent at the review point

### 5.1 Role

The owner's words are *"it can help me supply the results"*. The assistant is a Mission
Control-skilled agent bound to **one open gate**. Its job is to turn the owner's intent into a
valid Steering Resolution and to show its consequences before submission.

| It can | It cannot |
| --- | --- |
| Read the Review Packet, the subjects' transcripts, points, state-as-of, fulfillment rows and artifacts | Resolve the gate on its own (§5.4) |
| Explain what a stage did and where it diverged; compare the deliverables with their obligations | Write the mission ledger, open commands, or touch a running unit |
| Check things in a scratch sandbox: re-verify citations, run a test, diff two drafts | Use authority the owner does not hold, or expand the mission's authority |
| Search the catalog for skills, MCP servers, lane features, model tools and review or obligation templates to add | Change the subjects' artifacts in place (it drafts a replacement for `amend_deliverable`) |
| Draft feedback, injections, a corrected deliverable and amendments; keep them in a **Review Draft** | Reach any run except the gate's run or chain |
| **Preview**: compile the amendments, show issues and Transition Impact, and render the exact packet Stage 4 (or the revised Stage 3) would receive | |
| Estimate the cost of a revise round from the target's usage so far | |

### 5.2 Where it runs: mock now, hosted later

| Phase | Assistant | Transport | Notes |
| --- | --- | --- | --- |
| **Mock (recommended for testing now)** | the owner's coordinator agent (Claude Code or another agent) with the `mission-control` skill's intervene bundle (CS §4.6) and the operator MCP | `missionctl human-task …` (new, §8.4) and the MCP `mission_human_task_*` tools, plus `review draft\|preview` | The dashboard is mocked by the CLI and the chat. This needs the tenant-scoped Human Task service on the coordinator mount (gap, §2). It also needs catalog search beside the operator tools: the operator MCP has none and the coordinator MCP has `search_capabilities` (§2), so the mock uses both mounts or the operator mount gains read-only catalog tools |
| Hosted | a **review session**: a Deep Agents unit that Mission Control starts when the gate opens (or on request) from a catalog agent profile (`catalog://agents/review-assistant@1`), with read-only operator tools over its run, the packet materialized, and a scratch sandbox | the mission stream; a dashboard chat pane | Budgeted under a separate `review` dimension, never the subjects' budget. Its transcript is History of the gate. It is not a node of the program and never affects the graph's acceptance |

The mock and the hosted assistant run the same skill and the same verbs, so the owner rehearses
the real flow from day one.

### 5.3 Drafts and preview

A **Review Draft** is append-only and versioned (`review_draft`: task id, version, author
principal or assistant session, body as a draft `mc.steering_resolution.v1`, digest). Either
party writes a new version. `review preview DRAFT` runs exactly the resolution transaction's
validation without committing. It returns typed issues, the Revision Proposal diff and
Transition Impact, any resume degradations (§4.6), and per dependent or revise target the
rendered `context.md`, `state.json` and the transfer plan. **Submitting** is
`human-task resolve TASK --draft DRAFT_VERSION`: the owner's action, attributed to the owner.

### 5.4 Can the assistant resolve on my behalf?

Recommendation for v1: **no.** The rules already say that *"No remote UI can resolve a task
without an attributed action"* (`docs/knowledge/durable-controls.md`, ADR-0016), and required
human review is never satisfied by notification delivery (ADR-0008). The assistant prepares and
the owner submits. In the mock, the owner either runs the command or confirms in chat while the
agent runs it with the owner's token. The resolution then records `via: assistant_confirmed`
and the session ref. Whether the owner may delegate standing authority ("approve anything that
meets all obligations with no findings") is interview item HR5.4. If adopted, delegation is a
reviewer grant `reviewer:<gate>@delegate` with a typed predicate, not the assistant's judgement.

---

## 6. Persistence, contracts and events

| Item | Change | Label |
| --- | --- | --- |
| `HumanGateSpec` | adds `steering: SteeringPolicy{permits, revise_targets, on_reject, options, hold, assistant}`; `remediation_target` generalizes into `revise_targets` | [P] |
| Manifest `HumanTaskSpec` | adds `steering:` and the `review:` sugar (§8.1); lifts V09 | [P] |
| `mc.steering_resolution.v1` | the resolution body (§4.3), exported as JSON Schema like `mc.chain.v1` | [P] |
| `human_resolution.answer` | holds the steering resolution (the existing JSON and digest column) | existing |
| `steering_effect` | one row per rider: resolution ref, rider kind, class, target, items or artifact refs, revision proposal ref, status `applied \| refused`, reason. Immutable, written in the resolution transaction | [P] release with OC-1 or later |
| `mission_note` | scope (mission, chain), body ref, effective-from (resolution ref and the head revision), `superseded_by`. Immutable plus supersession | [P] |
| `review_draft` | §5.3 | [P] |
| Revision service | proposal → validate → compile → activate on the existing 0002/0003 tables, with Transition Impact and carry-forward eligibility. **This is the largest new kernel piece** and it serves more than gates (INT R7 "a revision request that re-opens one obligation") | [P] |
| Chain link state | `awaiting_review` plus the trigger update (migration) | [P] |
| Events | `review.steered` (verdict, rider kinds, classes, amended targets) beside `human_task.resolved`; `mission_note.added`; `revision.activated`; `review.revise_started`; `review_draft.updated` (for the dashboard). All carry `unit_key`, `point_ref` and location (CS-D5) | [P] |
| Inbox | `review_required` (existing) gains the gate's subjects and next-up summary in its payload | [P] |
| Points | a resolution coordinate kind `human_resolution` joins `transferred_from` on the consumer's input point (OC §4.7), so "where did this instruction come from" is one hop | [P] |

---

## 7. A worked example: Stage 3's report, Stage 4 blocked

**The mission.** S1 gathers sources, S2 drafts findings, S3 writes an evidence-backed `report`
(`document`, `required`), and S4 turns the report into a clinician brief and a PDF. The owner
told the coordinator: *"I want to review the report before the brief is written, and I want to
be able to send it back."*

```yaml
stages:
  - key: S3
    outputs: [{ name: report, kind: document, template: catalog://obligations/evidence-report@2 }]
    review:
      template: catalog://reviews/report-review@1      # permits: steer_full; reviewers: [owner]
      revise_targets: [S3, S2]
      assistant: { start: on_open }
  - key: S4
    depends_on: [S3]                                    # the compiler rewires this to S3.review
    inputs: [{ name: report, from: S3.report, expand: materialize }]
    outputs:
      - { name: brief, kind: document }
      - { name: brief_pdf, kind: file_artifact, content_types: [application/pdf], derives_from: [S4.brief] }
```

**What you see** (inbox `review_required`, then `missionctl human-task get TASK`): the report
(downloadable), its fulfillment (`evidence_backed`: 14 citations, 2 unresolved), no findings, 1.10
USD used of 4.00, S4's configuration and the packet it would receive, and the permits.

**Scenario A: approve with feedback and context.** You tell the assistant: *"Approve, tell the
brief writer to lead with limitations, and keep primary sources only from now on."* The
assistant drafts the following and previews S4's `context.md`:

```yaml
verdict: approve
riders:
  - feedback: { text: "Approved. Two citations are unresolved; flag them, do not drop them." }
  - inject: { scope: unit:S4, items: [{ instruction: "Lead with the limitations table." }] }
  - inject: { scope: mission, items: [{ instruction: "Primary sources only." }] }
```

S4 starts. Its `/.mission/context.md` opens with:

```text
## Owner review (gate S3.review, round 1, owner, approved)
- Feedback: Approved. Two citations are unresolved; flag them, do not drop them.
- For you: Lead with the limitations table.
- Mission note: Primary sources only.
## Inputs
- report  document  materialize  /inputs/report/report.md  sha256:…  (from S3, released by review_approved)
```

**Scenario B: approve and reconfigure S4.** *"Use the bigger model for the brief, add the
clinical-writing skill, and require two variants."* The amendments are `amend{target: S4, set:
{model, capabilities.skills, outputs[brief].cardinality: {min: 2, max: 2}}}`. The preview shows
Revision 2 with impact `definition_changed` on S4, which is pending, so it releases from the new
head. The skill pin is within your grants, so there are no issues. On submit, Revision 2
activates and the gate releases S4 with `review_approved_with_amendments`.

**Scenario C: send S3 back.** *"Section 3 overstates the effect sizes; redo it with the
meta-analysis I'm attaching, and switch on the todo list so it plans."*

```yaml
verdict: revise
revise: { target: S3, resume: continue }
riders:
  - feedback: { text: "§3 overstates effect sizes; recompute against the attached meta-analysis." }
  - attach: [artifact://…/meta-analysis.pdf]
  - amend: { target: S3, set: { lane_features: { deep_agents: { todo_list: {} } } } }
```

S3 round 2 starts as a new activation under Revision 2. Its thread is seeded from round 1's
result point, so it sees its own conversation and its `report.md`. The next human message is
your feedback with the attachment path, and its state lists the original objective, round 2 of
3, the prior fulfillment and the amendment. S4 stays blocked. When S3 settles, the gate opens
round 2 with a new packet, which shows the diff between report v1 and v2.

**Scenario D: the problem is S2.** `revise{target: S2, resume: from_point, from_point:
point://…(before the third search)}`. S2 continues from that point and S3 re-runs `fresh` with
its v1 report referenced. The gate opens round 2.

**Scenario E: stop.** `reject` with feedback: the gate is `not_accepted` and `on_reject:
fail_run` ends the run. With `permits.on_reject: [fail_run, skip_dependents]` you could instead
skip S4 and let an independent branch finish.

---

## 8. Making it configurable and searchable for the coordinator

### 8.1 Authoring forms (one schema, three entry points)

```yaml
# the review block, valid on a stage (G2), a goal (G4), a link (G6), or inside a human_gate node (G1)
review:
  template: catalog://reviews/report-review@1   # optional; fields below override it
  prompt: "Review the report before the brief is written."
  reviewers: [owner]                              # roles or principals; default [owner]
  quorum: 1                                       # HR7
  permits: steer_full                             # a preset or an explicit block, §8.3
  revise_targets: [S3, S2]
  on_reject: fail_run
  options: []                                     # for select
  hold: dependents                                # dependents | run
  timeout: 72h
  on_timeout: keep_waiting                        # + escalate_to: [role]
  max_rounds: 3
  assistant: { profile: catalog://agents/review-assistant@1, start: on_open }   # or on_request | none
  show: [S3.report, S2.notes]                     # extra packet subjects
```

The compiler synthesizes the explicit gate node, rewires dependents, and emits a **review plan**
in the compile receipt. The plan has one row per gate: what it reviews, what it blocks, who
reviews, the permits, revise targets with their resume feasibility, timeout behaviour and the
assistant. Compile issues are typed: `revise_target_not_upstream`, `permits_exceed_authority`,
`resume_continue_impossible:<reason>`, `review_on_parallel_branch_holds_run` (a warning),
`gate_unreachable`.

### 8.2 Review templates in the catalog

A new catalog kind `review_template`, digest-pinned like skill bundles and obligation templates
(OC-D19). It is searched through the existing hybrid catalog search (ADR-0025) and the
`catalog` noun. A first set:

| Template | Use | Permits preset |
| --- | --- | --- |
| `report-review` | a knowledge deliverable before it is used | `steer_full` |
| `plan-approval` | a plan stage before execution stages | `steer_context` + amend downstream |
| `code-review-before-merge` | a `code_change` before an integrating stage; the packet shows the diff and checks receipts | `steer_full`, `amend_deliverable` via a commit the harness observes |
| `chain-handoff` | between linked missions | `steer_full` at link scope |
| `final-acceptance` | the graph's acceptance gate | `approve_reject` |
| `cycle-cap-escalation` | `on_cap: human_review` | `revise` + `budget` |
| `budget-checkpoint` | `on_budget: {at: 80%}` | `approve_reject` + `budget` |

### 8.3 Permits

Permits declare what a reviewer may do at this gate. The compiler intersects them with the
mission authority and the reviewer's grants. Presets: `observe_only`, `approve_reject`,
`steer_context` (feedback, inject, attach, transfer), `steer_full` (adds `amend`,
`amend_deliverable`, `revise`, `budget`), and `owner_full` (all of `steer_full` within the
mission's authority, the default for the `owner` role). An explicit block names verdicts,
rider kinds, amend fields (for example `amend: [objective, model, capabilities.skills,
outputs]`), inject scopes, revise targets and on-reject choices. Permits are what keep a
reviewer role other than the owner (a domain expert, a client) safe to invite.

### 8.4 Commands (CS grammar)

The CS proposal already adds `human-task list|get|resolve` (CS §3.5). This adds:

```text
missionctl human-task list [--run RUN] [--kind review] [--open]
missionctl human-task get TASK [--packet] [--next-up]        # the Review Packet, with S4's dry-run plan
missionctl human-task draft TASK [--from-file steer.yaml]    # create or append a Review Draft version
missionctl human-task preview TASK [--draft V]               # issues, revision diff, impact, rendered packets
missionctl human-task resolve TASK (--draft V | --approve | --revise S3 | --reject | --select OPT)
                              [--feedback-file F] [--inject SCOPE:FILE]... [--amend FILE] [--attach FILE]...
missionctl run hold RUN --before NODE [--review TEMPLATE]    # G7, a revision proposal
missionctl describe review-gate                              # verdicts, riders, classes, permits, generated
```

The HTTP routes and MCP tools stay one-to-one with these (CS §3.6).

### 8.5 What the skill tells a coordinator

The Stage Graph bundle step "Shape the graph … where humans review" (CS §4.5) becomes a table
that maps the owner's words to an authoring:

| The owner says | You author |
| --- | --- |
| "I want to review X before Y" | `review:` on X with the template that fits; Y depends on X |
| "…and be able to send it back" | `revise_targets: [X]` (+ upstream units the owner names), `max_rounds` |
| "…and change what Y does" | `permits` including `amend` on Y's fields |
| "Let me approve the plan" | `plan-approval` on the plan stage |
| "Check with me between these missions" | `review:` on the chain link (`chain-handoff`) |
| "Stop and ask me if it keeps failing / runs out" | `on_cap: human_review`, `on_budget` |
| "Let me talk it through with an agent" | `assistant: { start: on_open }` |
| "Don't block the other work" | `hold: dependents` (the default); state it in the plan |

Then: compile, read the **review plan** back to the owner in plain words, and confirm before
submitting. The workspace (INT R8) gets one card per verdict, rider, permit preset and template,
generated from the registry that defines them, so the coordinator's reference never drifts from
the code.

---

## 9. Amendments to the output-contracts specification

These are proposed edits to the companion, to be made in the companion's own session:

1. **OC §2 vocabulary**: add Review Gate, Steering Resolution, Verdict, Rider, Steering Effect,
   Mission Note, Review Assistant, Review Draft.
2. **OC §3.2 `verdict` kind**: a Review Gate's own obligation is a `verdict` with `author:
   human`. Its submission form is the Steering Resolution. Its mechanical checks are parse,
   verdict in the closed set, riders within permits, and an atomic amendment validation.
3. **OC-D25 (`verify:`)**: `verify: human` compiles to a G3 Review Gate. `gate` blocks the
   producer's acceptance; `annotate` records the verdict as a finding.
4. **OC §4.0 transfer points**: T10 splits into **T10a** review open (subjects to reviewer and
   assistant, purpose `review_open`), **T10b** approve (gate to dependents, purpose
   `review_release`), **T10c** revise (gate to the revise target, purpose `review_revise`), and
   **T10d** Mission Notes (to every later unit). **T9 + T10** is a chain-link review.
5. **OC §4.2 heuristics**, appended as data:

   | Id | Rule |
   | --- | --- |
   | H10 | Steering items scoped to the consumer (feedback, injections, the verdict, accepted findings) are State layer, inline, mandatory, attributed, rendered first in "Owner review". |
   | H11 | An `amend_deliverable` replacement binds in place of the original; the original is referenced with `superseded_by_review`. |
   | H12 | Active Mission Notes are inline and mandatory for every unit whose activation starts after the note's effective point; Goal iterations and subagents that inherit `/.mission/state.json` include them. |
   | H13 | A `revise` target under `continue` or `from_point` receives only State-layer additions; its deliverables and files are already in the seeded state. Under `fresh` its prior deliverables are materialized under `/inputs/prior/`. This overrides the K05 reference default because the unit is revising them. |
   | H14 | `transfer` riders apply as consumer overrides (OC §4.2 `overrides`) and may only add material already in the run or chain. |

6. **OC §4.3 dependency table**: replace the "Human review disposition" row with
   `review_approved`, `review_approved_with_amendments` and `review_selected:<option>` release
   kinds. Each transfers H10-H12 plus the subjects' deliverables per binding.
7. **OC §4.4 cycles**: a `revise` is a human-triggered revisit of the target region with its own
   round counter. It uses the same `ProgressObservation`, and the prior-cycle deliveries carry
   the original objective (never replaced; fixes `human_gate.py:719-731`).
8. **OC §4.5 Goal Loop**: owner feedback at a Goal review is H10, not an untrusted executor
   instruction. `amend` may target roles and governors.
9. **OC §4.6 materialization layout**: `/.mission/state.json` gains `steering` and
   `mission_notes`; `context.md` gains the "Owner review" section; `/inputs/prior/` is added.
10. **OC §6 build order**: see §11.

---

## 10. Decisions for the owner (recommendation marked)

| Id | Decision | Recommendation |
| --- | --- | --- |
| HG-D1 | Kernel noun: keep **Human Gate** with kind `REVIEW` and call it Review Gate; "checkpoint" is a product word only | **Adopt.** The glossary forbids "checkpoint" for gates |
| HG-D2 | Resolution = one verdict (`approve`, `revise`, `reject`, `select`) plus typed riders | **Adopt** |
| HG-D3 | The boundary law: C context (no revision), R configuration (Revision Proposal), M meaning (successor mission) | **Adopt** |
| HG-D4 | A resolution with amendments is atomic with its revision's validation and activation | **Adopt** |
| HG-D5 | `revise` defaults to `continue` from the target's result point; `from_point` and `fresh` by choice; the original objective is never replaced | **Adopt.** It changes today's `next_objective` behaviour |
| HG-D6 | Resume degrades to `fresh` on a lane or model-provider change, with a typed notice | **Adopt**, after the §13 verification |
| HG-D7 | Review rounds and cycle caps are separate counters | **Adopt** |
| HG-D8 | Owner steering is attributed instruction, not "untrusted content", and never authority | **Adopt** |
| HG-D9 | Mission Notes at `mission` and `chain` scope, capped, supersedable | **Adopt**, with 20 notes and 4 KB each |
| HG-D10 | `amend_deliverable`: owner-authored replacement artifacts with lineage | **Adopt** for knowledge kinds; for `code_change`, via a commit the harness observes |
| HG-D11 | Gate placement forms G1-G7 | **Adopt** G1, G2, G4 (completion and every N), G5 and G6; G3 with OC-D25; G7 after the revision service |
| HG-D12 | `hold: dependents` is the default; `hold: run` is optional | **Adopt** |
| HG-D13 | `on_reject` vocabulary (`fail_run`, `skip_dependents`, `route`, `conclude`), default `fail_run` | **Adopt** |
| HG-D14 | Permits with presets, intersected with authority at compile | **Adopt** |
| HG-D15 | Catalog kind `review_template` | **Adopt** |
| HG-D16 | Review Assistant: mocked by the coordinator agent now, hosted review session later | **Adopt** |
| HG-D17 | The assistant never resolves; the owner submits a draft (`via: direct \| assistant_confirmed`) | **Adopt** for v1; delegation per HR5.4 |
| HG-D18 | Review Drafts and preview, persisted server-side | **Adopt.** The preview is the comprehension tool |
| HG-D19 | Chain-link review owned by the chain, link state `awaiting_review` | **Adopt** with sprint G |
| HG-D20 | Revising an upstream mission after it is terminal = a derived run from its final point | **Adopt**, interview HR6.2 |
| HG-D21 | A revision service (proposal, validation, activation, Transition Impact, carry-forward) is built as its own kernel sprint | **Adopt.** Gates, obligation re-open and G7 all need it |
| HG-D22 | `steering_effect`, `mission_note`, `review_draft` tables; `review.*` events | **Adopt** |
| HG-D23 | The `human_resolution` coordinate in `transferred_from` | **Adopt** |
| HG-D24 | `select` with declared options as a typed conditional release | **Adopt**; it may slip to after OC-2's `conditional` |

---

## 11. Build order and proofs

The gate work reads fulfillment facts and writes into the transfer policy, so it follows the
companion's foundation. The insertion points in the INT §3 strawman (A … I):

```text
A  upgrade   B  configuration language
C  OC-1 obligations ─────────┐
D  OC-2 transfer ────────────┼─► HG-1  review gate v2 (context class)
E  OC-3 cycles, Goal Loop ───┼─► HG-2  revise from the finished point; Mission Notes
RV revision service ─────────┴─► HG-3  amendments, preview, G7 hold
F  lifecycle ─────────────────► HG-4  hosted review assistant, drafts in the stream
G  linked workflows ──────────► HG-5  chain-link review
```

| Session | Builds | Proves (T0 unless noted) |
| --- | --- | --- |
| **HG-1** (after OC-2) | `mc.steering_resolution.v1` with `approve`, `reject`, `revise(fresh)`; riders `feedback`, `inject` (unit, downstream), `attach`, `transfer`; lift V09; the `review:` sugar and review plan; the Review Packet from fulfillment rows and promoted artifacts; `steering_effect`; H10, H14; `missionctl human-task list\|get\|resolve`; the tenant-scoped service on the coordinator mount | FX-HG-APPROVE-FEEDBACK: S4's first model call sees the Owner review section and the report at the planned tier; its input point lists the resolution coordinate. FX-HG-REJECT: `fail_run` and `skip_dependents`. FX-HG-STALE: a resolution against an old packet digest is refused and changes nothing. FX-HG-PERMITS: an inject outside the permits is refused typed |
| **HG-2** (after OC-3) | `revise` `continue` and `from_point` via `seed_fork`; upstream targets and the frontier; round counters and progress; Mission Notes (H12); `amend_deliverable` (H11); the Goal Loop review with owner-attributed feedback and `every: N` | FX-HG-REVISE-CONTINUE: round 2's thread contains round 1's messages and files, the feedback is the next human message, and the original objective is in state. FX-HG-REVISE-UPSTREAM: S2 from a point, S3 fresh, gate round 2. FX-HG-NOTE: a mission note reaches S4, S5 and a Goal iteration. FX-HG-GOAL: iteration N+1 sees the owner feedback and continues the role thread |
| **RV** | the revision service on 0002/0003 | FX-RV-HEAD: concurrent proposals, one becomes stale; FX-RV-IMPACT: pending, running and completed nodes each get the specified treatment |
| **HG-3** | `amend` riders through RV, atomic with the resolution; `review draft\|preview`; resume degradations; `budget`; G7 `run hold` | FX-HG-AMEND-NEXT: S4 runs under Revision 2 with the added skill and a new obligation; the receipt shows both. FX-HG-ATOMIC: an invalid amendment refuses the whole resolution and the gate stays open. FX-HG-DEGRADE: a model-provider amend on a revise previews and runs `fresh` with the notice |
| **HG-4** (with F) | the hosted review session (catalog profile, read-only operator tools, scratch sandbox, `review` budget dimension), drafts in the stream, `via: assistant_confirmed` | FX-HG-ASSIST: the session drafts, previews and hands over; the owner submits; the session's transcript is reachable from the gate |
| **HG-5** (with G) | chain-link review, `awaiting_review`, downstream pre-start amendment, upstream revise as a derived run, `inject{scope: chain}` | FX-HG-CHAIN: approve with an amendment changes the downstream's first run; revise upstream re-arms the link on the derived run |

One **T2 proof** after HG-3, under 15 USD, with models named by the owner: the §7 mission live.
The owner resolves round 1 with `revise` + feedback + a lane feature, and round 2 with `approve`
+ an inject + an S4 amendment, both through the assistant. The proof is read end to end in the
transcript files.

The **mock path is usable from HG-1**. The owner and a coordinator agent with the skill can
review a real run through `missionctl human-task` while the dashboard does not exist.

**Two existing mechanisms shorten the path:**

- **HG-1's unit-scoped inject can ship before OC-2.** The resolution transaction writes an
  `add_context` mailbox entry keyed to the dependent's `node_key`. The mailbox already delivers it
  as a mandatory item at that stage's admission (`domain/policies/mailbox.py:233-258`). When OC-2
  lands, the same Steering Effect is read by the transfer policy (H10) instead, and the mailbox
  carrier is retired for steering.
- **An interim "amend by fork" if the revision service slips.** A resolution may end the gate's
  run and start a derived run from the gate's position, with `stage_objectives` and the
  configuration digest patched. The fork policy already admits this
  (`domain/policies/forks.py:1009-1030`, `application/programs/fork_templates.py`). It is honest
  about being a new run, and the derived run is a separate mission run in every read surface,
  which is the cost. The owner chooses between this fallback and waiting for RV in HR3.6.

---

## 12. Interviews to hold before implementation

The rounds follow the INT §4.3 protocol: context first; at most four questions per batch with
the recommendation first; restate the mental model as a manifest fragment or as "what you will
see"; record each answer in a decision log with its consequence; run the drift check against INT
§0. Participants: **the owner** decides, and **the interviewer agent** prepares, asks and
records. HR8 and HR9 also include **a coordinator agent** and **a review-assistant agent** as
subjects. Expect two sittings for HR0-HR7 and one for the two rehearsals.

### HR0. Language and the owner's mental model (15 min)

- **HR0.1 (must)** Is "Review Gate" (kernel), "review checkpoint" (product) and "Steering
  Resolution" acceptable? The glossary forbids "checkpoint" for the node.
- **HR0.2 (must)** Restate §1.1 in your own words: is that the capability you want? Name what
  is missing.
- **HR0.3 (must)** Agent context = a unit-scoped inject; mission context = a Mission Note. Are
  those the two you meant, or did "mission context" mean something else, such as the mission's
  shared state, goals or memory?

### HR1. Placement (20 min)

- **HR1.1 (must)** Forms G1-G7: which in v1? Is G7 (an ad hoc hold at runtime) important enough
  to pull the revision service earlier?
- **HR1.2 (must)** `hold: dependents` by default: are you comfortable with other branches
  running while you review?
- **HR1.3 (can defer)** The Goal Loop cadence: completion only, every N iterations, on verifier
  reject, on no progress?
- **HR1.4 (must)** Is a review of **several** subjects at once (S3 and S5 together) needed in v1?

### HR2. Verdicts and approve (20 min)

- **HR2.1 (must)** The four verdicts. Is `select` needed in v1? Is a fifth needed, such as
  "approve but also try an alternative" (`fork`)?
- **HR2.2 (must)** Approving with shortfalls records `accepted_findings`. Should approval be
  refused while a `required` obligation is unmet, or may the owner override with a reason
  (`overridden` resolution, `05` §6.3)?
- **HR2.3 (must)** Approve on the final gate: is your approval the graph's acceptance, or one
  input to it?

### HR3. The boundary law (heavy, 30 min)

- **HR3.1 (must)** Adding = context, replacing = configuration, redefining success = new
  mission. Agree?
- **HR3.2 (must)** Which configuration fields may an amendment touch in v1? The list:
  objective, obligations, model, lane, capabilities, lane features, model tools, subagents,
  budget, governors, cycle policy, input bindings, graph structure. Which should wait?
- **HR3.3 (must)** Tightening acceptance (raise a cardinality, add a validator) at a gate: class
  R, permitted? Loosening it?
- **HR3.4 (must)** Atomic resolution: is "the whole resolution is refused if any amendment is
  invalid" right, or do you want "apply what is valid and report the rest"?
- **HR3.5 (can defer)** May an amendment raise the mission's **authority ceiling** (a new
  credential scope) if you, the owner, hold it? The spec says that needs a successor mission.
- **HR3.6 (must)** If the revision service (RV) is not ready when HG-2 ends, use the interim
  "amend by fork" (§11), which ends the run and starts a derived run with the patched
  configuration? Or wait for RV and offer context-class steering only until then?

### HR4. Revise (heavy, 30 min)

- **HR4.1 (must)** `continue` as the default: is this "starts from its finished point" as you
  meant it? Restate: same conversation, your feedback as the next message, files in place,
  original objective kept.
- **HR4.2 (must)** On a lane or model-provider change, degrade to `fresh` plus a handoff, or
  refuse the amendment?
- **HR4.3 (must)** Separate counters for review rounds and cycles? What is the default
  `max_rounds`?
- **HR4.4 (must)** When an upstream unit is revised, should the units between it and the gate
  re-run `fresh` (default) or `continue` with a notice that their inputs changed?
- **HR4.5 (can defer)** When a round makes no progress: block the next round, warn, or nothing?
- **HR4.6 (must)** Codebase work: does `revise` on a `code_change` always carry the workspace?
  Is `amend_deliverable` for code a commit by you on the mission branch?

### HR5. The Review Assistant (heavy, 30 min)

- **HR5.1 (must)** The capability table of §5.1: is anything missing or unwanted? In particular,
  may it run scratch analyses that cost money, and with what cap?
- **HR5.2 (must)** Mock now through the coordinator agent and the CLI, hosted later: agreed?
  Which agent do you want as the mock (Claude Code with the skill)?
- **HR5.3 (must)** Assistant budget: a separate `review` dimension per gate, with what default?
- **HR5.4 (must)** Never resolves in v1. Do you want standing delegation later ("approve
  automatically when every obligation is fulfilled with no findings"), and if so, should it be
  a typed predicate or the assistant's judgement? (Recommendation: a typed predicate only.)
- **HR5.5 (can defer)** Should the assistant start automatically when a gate opens and prepare a
  first draft before you arrive?

### HR6. Between workflows (20 min)

- **HR6.1 (must)** A chain-link review owned by the chain, adding `awaiting_review`: agreed?
- **HR6.2 (must)** Revising a finished upstream mission as a derived run from its final point:
  acceptable, or should the upstream stay open (not terminal) until its link review passes?
- **HR6.3 (must)** Downstream amendments before first run: may they change the downstream's
  lane and its goal's wording, given that it has not started?
- **HR6.4 (can defer)** Chain-scope Mission Notes: should they also reach missions linked
  later?

### HR7. Reviewers, timeouts and notification (15 min)

- **HR7.1 (must)** Reviewers other than you in v1 (a domain expert, a client), with permits? Or
  owner only?
- **HR7.2 (can defer)** Several reviewers: any one, a quorum, or a sequence?
- **HR7.3 (must)** Default timeout and `on_timeout` (recommendation: `keep_waiting`, escalate
  after 72 h, never `default_answer` for a review).
- **HR7.4 (can defer)** Where do you want to be notified (inbox only, email, push)?

### HR8. Rehearsal 1: authoring interview with a coordinator agent (45 min)

Purpose: test comprehensibility before building. The interviewer gives a **coordinator agent**
only the proposed skill text (§8.5), the `review:` schema (§8.1) and the template list. The
owner then speaks to it exactly as they would in production, for example: *"Research X in three
stages; I want to review the synthesis and be able to send it back to the search stage; check
with me before the second mission starts."* The agent writes the manifest and reads back its
review plan.

- Record every place the agent hesitated, guessed or asked. Each one is a missing card, an
  ambiguous name or a missing preset.
- The owner judges whether the read-back matched their intent. Each mismatch is a decision to
  revisit.
- Repeat with three phrasings, including one where the owner wants a review between linked
  missions and one with a Goal Loop.

### HR9. Rehearsal 2: tabletop review with a review-assistant agent (45 min)

Purpose: find the missing details in the review interaction itself. The interviewer prepares a
**mocked Review Packet** for §7 (a real report from the Stage 2 transcripts, fake fulfillment
rows, S4's configuration). It gives a **review-assistant agent** the §5 capability table and the
§4.3 schema. The owner then runs scenarios A-E of §7 by talking to it.

- After each scenario the assistant must produce the draft resolution and a mocked preview (S4's
  `context.md`). The owner checks: *is this what I meant, and is this what I want Stage 4 to
  read?*
- Record the questions the assistant could not answer from the packet. Each one is a missing
  packet field.
- Record every point where the owner wanted an action the verdict and rider set did not offer.
  Each one is a missing rider or permit.
- End with the owner rating each scenario: clear, workable, or confusing.

**Outputs of the interviews:** the decision log (HG-D*), the parking lot, the amended §1.1 table
as the owner's confirmed capability set, the confirmed placement in the build order (§11), the
first session instruction (HG-1) written in full, and the fixes from the rehearsals to the
vocabulary, packet and skill.

---

## 13. Honest list and verifications before building

- **Verify** whether a derived unit with a **different binding digest** (amended capabilities or
  model) may continue a seeded thread. `seed_fork` reads the binding and state-schema stamps,
  and the request's `binding_digest` is optional (`application/execution/harness/time_travel.py:61-63`,
  `adapters/deep_agents/time_travel.py`). The §4.6 assumption (state schema equal → continue) is
  unproven.
- **Verify** how a within-run stage activation is seeded from a point. Today `seed_fork` serves
  derived runs. A revise round is a new activation inside the same run, which needs the
  OC-3/K02 seed-from-point path (OC-D12) generalized to stage activations.
- **Verify** that changing tools or the model on a seeded LangGraph thread is accepted by the
  installed `deepagents` (0.7.5) and after sprint A (0.7.30). Tool messages that reference tools
  absent from the new binding may need a typed refusal.
- The Stage Graph approved gate today completes with `output_refs: [resolution_ref]`
  (`human_gate.py:711-715`). OC-D4's change, where registered refs win and the model's
  `output_refs` is a claim, must not break the gate's own output. The gate's output becomes its
  `verdict` deliverable.
- The revision service does not exist. HG-3 and G7 depend on it, and it is a kernel sprint of its
  own size. Without it, a gate can steer context (HG-1, HG-2) but cannot amend configuration,
  except through the interim fork path (§11). Stage templates are frozen per semantic input
  binding (`application/programs/service.py:1732-1737`), so RV must also unfreeze a pending
  stage's template when its node is `definition_changed` under a new head.
- Name collision: the compaction failure policy already has a `human_review` step that is not
  connected to Human Tasks (`domain/context/checkpoint.py:857,863`). `on_cap: human_review` in
  OC §4.4 and §4.1 G5 should either use that name consistently with a real gate or use
  `on_cap: review`.
- `child_mission_invocation` is parsed but not lowered (the lowering handles only Stage Graph
  and Goal Loop roots). A review inside a child mission is out of scope until it is.
- The tenant-scoped Human Task service is missing from the coordinator mount, and the
  `missionctl human-task` group does not exist. The mock assistant needs both (HG-1).
- Nothing here is live-proven. The Human Gate itself is not live-proven
  (`docs/knowledge/human-gates.md`: *"nothing here is live-proven"*).
- `05` §6.3 says *"Approval ≠ input ≠ intervention: an answer cannot smuggle a policy change"*.
  Class R riders change policy, and they do so **only** through a Revision Proposal that
  validates and activates as a revision, never through the answer itself. This reading should
  be confirmed in HR3 and, if accepted, recorded in an ADR amending ADR-0038's consequence
  *"request_changes … never mutates the mission revision"*. The mutation is a new revision, not
  a change to the current one.
- ADR candidates: the Steering Resolution and the boundary law; revise-from-point as the default
  remediation; Mission Notes as attributed mandatory context; the Review Assistant as a
  non-program session that never resolves.
- Knowledge concepts to update when built: `human-gates`, `durable-controls`, `interventions`,
  `mission-chains`, `revisions`, `context-and-continuation`. Glossary: §3 terms.
