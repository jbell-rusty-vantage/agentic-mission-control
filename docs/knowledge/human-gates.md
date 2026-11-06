---
type: Concept
category: domain-model
title: Human Gates, the Human Task Service and the review loop goal
description: How a Human Gate opens one Human Task per activation and review round and waits on an attributed resolution, how Stage Graph and Goal Loop use request-changes remediation, how native provider approvals and governed effects share the same service, exactly what exists today, and what the owner's mission-output review loop (continue, reject with feedback and redo, start new) would add.
tags: [mission-control, human-gate, human-task, approvals, review, goal, implementation]
aliases: [human task, review decision, approval broker, governed effect, review loop]
questions:
  - How does a Human Gate open, resolve or deny a human task?
  - What does request_changes do in a Stage Graph and in a Goal Loop?
  - What exists of the human review loop and what is only a goal?
  - How is a native provider approval turned into a human task?
  - Who can resolve a task and from which interface?
updated: 2026-11-01
---

# Human Gates, the Human Task Service and the review loop goal

A [Human Gate](../../GLOSSARY.md) opens one [Human Task](../../GLOSSARY.md) per activation and review round and waits on
its attributed resolution; timeout is never approval (ADR-0038, SPEC-03). The control vocabulary is in [durable
controls](durable-controls.md). Built by MP-10; native provider approvals and governed effects (MP-11) use the same
service. The Goal Loop review is integrated with a scripted approver (the archived Sprint OC log, section "Goal run-4": exact candidate plus
verifier-decision review proved as identity/digest approval, "not semantic human qualification"); no real human
decision has qualified the loop.

## 1. Scheduling: the control activation

`mc.human_gate.v1` (`adapters/temporal/workflows/human_gate.py:48`) runs `human_gate.open`, then `workflow.wait_condition`
on a `resolution_committed` hint signal or a bounded poll (default 300 s), holding no activity or cognition slot, and
re-reads the task through `human_gate.observe` on every wake. At the deadline the repository applies the timeout
policy; cancelling the activation runs `human_gate.cancel`. A resolution commits first; a lost signal only delays
until the next poll.

- **Stage Graph** (patch `mp10-stagegraph-human-gate`): a stage named in `StageGraphRunInput.human_gates` starts the
  activation as a child instead of an operation, releases its reservation against zero usage and reports the outcome as
  the stage result. `request_changes` completes it with a bounded workflow cycle whose frontier is the declared
  remediation target (target and descendants re-run, the target with the feedback as its objective;
  `stagegraph_gate_result`, `domain/programs/human_gate.py:700`). A denied gate fails the run (patch
  `mp20-stagegraph-concluded-failure`).
- **Goal Loop** (patch `mp10-goal-human-review`): with `GoalDirectedRunInput.human_review`, a verified completion proposal
  opens one review on the verified outputs and the verifier decision (`goal_review_packet`,
  `domain/programs/human_review.py:30`; `NamedReviewPacketRequest` freezes exact named outputs, `domain/programs/human_gate.py:276`).
  `request_changes` continues the loop at the next iteration with the same revision, acceptance and obligations, the
  feedback as an untrusted executor instruction, every counter carried on and the budget never reset; with no iteration
  left, or on any other outcome, the run fails not accepted (`apply_goal_review`).

## 2. Output-contract obligations

A review never fulfills a promise by itself: its outcome (`accepted`, `not_accepted`, `changes_requested`,
`stopped_by_policy`, `cancelled`) is an input to the completion expression (`human_resolution` leaf, [completion](completion.md)).
Approval of a report does not authorize knowledge ingestion, merge or deployment; those are separate declared
capabilities. Changing the reviewed bytes invalidates the outstanding approval: the activation freezes the packet
(`review_packet_digest`), and `packet_digest_mismatch` refuses a stale decision.

## 3. Context transfer

`HumanGateActivation` freezes the review packet (refs and digests, `domain/programs/human_gate.py:203`); the packet is
exact outputs, not "latest". Reviewer feedback is carried as the next executor's untrusted instruction (Goal Loop) or the
remediation stage's objective (Stage Graph); both enter the ordinary context path ([context](context-and-continuation.md)).

## 4. Runtime and rules

`HumanGateSpec` (lowered policy): `gate_key`, `task_kind` (`APPROVAL | QUESTION | SELECTION | REVIEW | POLICY_OVERRIDE`),
reviewers, packet sources, `timeout_seconds`, `on_timeout` (`keep_waiting | escalate | default_answer | stop`), explicit
`default_decision`, `remediation_target`, `max_review_rounds` (at most 20). Decision is the `workflow_gate` row of
`mc.approval_binding.v1` (`approve | deny | request_changes`); `request_changes` needs a remediation target and a round
left; a REVIEW task resolves `review_accept | review_reject`. `decide_resolution` refuses `already_resolved`,
`task_expired`, `task_cancelled`, `not_reviewer`, `stale_version`, `packet_digest_mismatch`, `decision_not_admitted`,
`feedback_required`, `deadline_passed`; the same request id is a `duplicate`. The task is a `mission_control.human_task`
row of kind `human_gate:<KIND>` with attributed `human_resolution` and events with outbox rows in one transaction.

`HumanTaskService` (`application/human_tasks/service.py`) is tenant scoped and the only mutation path; transports: HTTP
`/human-tasks` list/get/resolutions and `approval-resolutions` (`interfaces/http/human_tasks.py`), socket event
`resolve_human_task` ([mission stream](mission-stream.md)) and MCP `mission_human_task_list|get|resolve`, governed
`mission_governed_prepare|execute|status`, `mission_approval_resolve`. Production lowering
(`ManifestLaunchInputAuthor.family_input`) turns manifest `human_gate` nodes into `human_gates` and a Goal Loop whose
acceptance requires `human` into `human_review`; an undeclared Goal Loop reviewer is the `owner` role. Approval-origin
tasks (MP-11, `approval:<origin>`): a native provider request (Claude `can_use_tool`, Codex approval and user-input) or a
governed effect opens a task through `ApprovalBroker`, which binds the task and a live `approval_correlation` before anyone
waits, waits at most 600 s (expiry denies and interrupts), revalidates generation, policy digest, grants and the Stop Fence
before a decision reaches the provider and marks a dead connection's correlations `lost`; `GovernedEffectService` is
prepare, review, execute once by compare-and-set (migration 0033, release 1.2.0).

## 5. Gaps and the review loop (goal)

Gaps: manifest `HumanTaskSpec` cannot express a remediation target or default answer, so a manifest Stage Graph gate
admits only `approve | deny` (`gate_spec_from_manifest`; typed refusal, MP-20 V09); the technical coordinator mount has no
tenant-scoped Human Task or governed services (the development MCP server serves them); no `missionctl human-task` group;
`claimed` lifecycle is unused.

**The human review loop is a goal; its design is a proposal, not a decision.** Owner, 2026-11-01: "some mission output gets
to me and I can review and provide feedback and continue, reject with feedback and re-do or start new." The design exists as the
[human review gates and steering supplement](../specs/proposals-2026-10/HUMAN-REVIEW-GATES-AND-STEERING-SUPPLEMENT-2026-10-22.md)
(2026-10-22, open, owner interview HG-D1..24 before building). Exactly what it specifies versus what is built:

| Supplement specifies (section) | Built today |
| --- | --- |
| A Review Gate is the existing Human Gate with task kind `REVIEW`, always an explicit node, placed by seven forms G1-G7 (after a stage, on an obligation, in a Goal Loop, on escalation, on a chain link, ad hoc) (4.1) | Explicit `human_gate` nodes with `REVIEW` tasks (`domain/programs/human_gate.py:49-52`); Goal Loop review `at: completion` only (`domain/programs/human_review.py`); no `review:` sugar, no obligation, escalation, chain-link or ad hoc form |
| One typed Steering Resolution: a verdict (`approve`, `revise`, `reject`, `select`) plus riders (`feedback`, `inject`, `amend`, `amend_deliverable`) in `mc.steering_resolution.v1` (4.3, 6) | `approve`, `deny`, `request_changes` plus a comment; a manifest gate admits only `approve | deny` (`gate_spec_from_manifest`, V09). No `SteeringPolicy`, `steering_effect` or `mission_note` in `src/` |
| `revise` continues the stage from its finished point with the feedback as the next message and an optional amended configuration (4.6) | Re-run replaces the stage objective with a text built from the feedback (`human_gate.py:738`, `feedback_instruction`) and carries no prior state. The seed exists separately: the precise fork takes a point, a message and files (`ForkSeedRequest.message`, `.files` at `application/execution/harness/time_travel.py:51-67`) |
| A Review Packet with depth layers and purpose `review_open`; a Review Assistant agent that drafts the resolution (4.2, 5) | Not built (no `review_packet`, no assistant); coordinator attention events carry exact outputs ([coordinator attention](coordinator-attention.md)) |
| Amendments through a Revision Proposal validated in the same transaction as the resolution (4.4, 6) | Revision proposals and the scheduling head are specified, not built ([revisions](revisions.md)) |
| A review between linked workflows; a mission-level review of the finished output set with continue, reject-and-redo, start-new (4.9) | Not built; gates sit inside a run and reject by failing it. A successor revision with lineage exists ([revisions](revisions.md)) |

The loop would also need a review inbox of deliverables with a notification, feedback as durable input to the next activation that
never widens permissions or budget, and a fresh gate on the revised output. The deleted design sketch (`EXPERIENCE-AND-STREAMS.md`,
"Review, rejection and artifact navigation", `66185d2e`) proposed `ReviewPacket@1` and `ReviewDecision@1`; a second review state machine
is rejected (a review decision is a Human Task payload).

Built / specified / goal: gates, service, transports, approvals and governed effects built, tested on PostgreSQL and Temporal, integrated with a scripted approver; the mission-output review loop is a goal.

# Citations

- Spec: [SPEC-03](../specs/archive/multi-provider-2026-10/SPEC-03-human-control.md), [MP-10](../specs/archive/multi-provider-2026-10/issues/MP-10-execute-human-gate-nodes-and-review-with-feedback-paths.md); ADR [0038](../adr/0038-two-origins-of-human-control-over-one-human-task-service.md); owner goal: [answers](../specs/agentic-sdlc-2026-11/answers/AGENTIC-SDLC-SITTING-II-2026-11-02-ANSWERS.md) (AS-D33).
- Code: [gate rules](../../src/mission_control/domain/programs/human_gate.py), [goal review](../../src/mission_control/domain/programs/human_review.py),
  [service](../../src/mission_control/application/human_tasks/service.py), [family wiring](../../src/mission_control/application/programs/human_gates.py),
  [repository](../../src/mission_control/adapters/postgres/human_tasks/repository.py), [control activation](../../src/mission_control/adapters/temporal/workflows/human_gate.py),
  [HTTP](../../src/mission_control/interfaces/http/human_tasks.py), [MCP](../../src/mission_control/interfaces/mcp/human_task_tools.py),
  [launch lowering](../../src/mission_control/application/authoring/manifest_launch_inputs.py), [approvals](../../src/mission_control/application/execution/approvals.py),
  [broker](../../src/mission_control/application/execution/approvals_broker.py), [governed effects](../../src/mission_control/application/execution/approvals_governed.py),
  [governed MCP tools](../../src/mission_control/interfaces/mcp/governed_gateway.py).
- Tests: [rules](../../tests/unit/human_tasks/test_human_gate_rules.py), [interfaces](../../tests/unit/human_tasks/test_human_task_interfaces.py),
  [manifest lowering](../../tests/unit/human_tasks/test_manifest_gate_lowering.py), [Goal review](../../tests/unit/human_tasks/test_goal_review.py),
  [tasks in PostgreSQL](../../tests/integration/postgres/test_human_gate_tasks_postgres.py), [restart on Temporal](../../tests/integration/temporal/test_mp10_human_gate_restart.py),
  [denied gate](../../tests/unit/orchestration/test_mp20_stagegraph_concluded_failure.py), [approval broker](../../tests/unit/approvals/test_approval_broker.py),
  [approvals in PostgreSQL](../../tests/integration/postgres/test_mp11_approvals_postgres.py), [governed effects](../../tests/integration/postgres/test_mp11_governed_postgres.py).
