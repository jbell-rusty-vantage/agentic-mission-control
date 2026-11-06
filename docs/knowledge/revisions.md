---
type: Concept
category: domain-model
title: Mission revisions, the scheduling head and per-policy mutation
description: How a mission definition becomes an immutable revision with a compiled program and a scheduling head, which writers exist today (manifest submit, chain members, nested runs), what the specified proposal, transition-impact and carry-forward pipeline adds, and the owner's goal of mutating a workflow per policy while it runs, with the built relatives (fork with a patch, bounded Goal Revisions).
tags: [mission-control, revisions, authoring, compiler, scheduling-head, mutation, goal]
aliases: [mission revision, scheduling head, revision proposal, change a workflow mid workflow, per-policy mutation]
questions:
  - How does a definition become an immutable revision?
  - Can I change a running workflow, and what exists for it today?
  - What is the scheduling head and who can move it?
  - How does a fork or a Goal Revision differ from a revision proposal?
  - What would per-policy mid-workflow mutation need?
updated: 2026-11-01
---

# Mission revisions, the scheduling head and per-policy mutation

A [Mission Definition](../../GLOSSARY.md) is the typed document a mission is authored as. Editing never overwrites
committed intent: every validation snapshot, committed [Revision](../../GLOSSARY.md), [Compiled
Program](../../GLOSSARY.md), activation, attempt and artifact is immutable; an edit produces a successor revision. The
code calls the compiler output `EffectiveRunConfiguration`. A mission has exactly one [Scheduling
Head](../../GLOSSARY.md); only that revision releases new work. A material change to goals, authority, tenant or the meaning
of success is not a revision but a successor or forked mission. Specification harvested from annex
`workflow-types/07` (deleted pack, `66185d2e`).

## 1. Scheduling: how a revision becomes the head (built path)

`insert_revision` (`adapters/postgres/control_plane/mission_revisions.py:105`) commits the next revision of a mission
and makes it the scheduling head, together with a definition snapshot, the compiled program and typed definition
rows; `admit_run_for_revision` (`:220`) admits the run that executes it. Writers today: manifest submit
(`manifest_submission.py`; one mission keyed by its manifest key, a resubmitted manifest is revision N+1), chain members
(the later members' frozen admissions, [mission chains](mission-chains.md)), nested child runs
(`PostgresNestedRunAdmissions` into the parent's mission revision, [recursive composition](recursive-composition.md)) and
the older `insert_admitted_run` (`adapters/postgres/run_control/canonical.py:249`). Committing a revision never
starts a run, and a new revision does not change a run already executing: it runs on its starting revision.
Compile resolves exact definition refs and verifies each digest (`compile_effective_run_configuration`,
`domain/authoring/compiler.py`; `ControlPlaneService.compile`, `application/authoring/service.py`), and expected-head
concurrency guards *definition publication* (`PublishRequest.expected_head_revision`, `DefinitionConflict`), not a
mission's scheduling head.

## 2. Specified, not built: proposals, impact, carry-forward

Authored edits and runtime graph changes share one specified pipeline: draft, submit a Revision Proposal naming its
`base_revision_id`, validate, compile, review, commit, activate the head. Activation locks and compares the expected
mission version and prior head in one transaction; the loser is `stale` and must rebase, never merged silently. Revert
is a new proposal from old content. Compiling a proposal emits a Transition Impact per node (`unchanged`,
`policy_changed`, `definition_changed`, `removed`, `added`) with a default treatment of running activations (continue,
apply at the next child boundary, `pause_and_checkpoint`, `supersede_after_completion`, release from the head),
applied at activation granularity (stage, swarm member, iteration, round, wait). Carry-forward eligibility is by
digests (node definition, inputs, policy, rubric version): `eligible | re_verify_required | ineligible`. Schema rows
exist (`revision_proposal`, `run_revision_transition`, `mission_run.scheduling_revision_id`:
`0002_authoring.sql`, `0003_execution.sql`) with no writer for proposals or transitions (grep: no hit for
`run_revision_transition` in `src/`). Revision activation while a Swarm or Goal Loop runs is therefore unspecified in code.

## 3. Per-policy mutation (goal)

Owner, 2026-11-01: provider lifecycles are synthesized into Temporal workflows "so that we can read and write from
mission state snapshots and do things like fork, queue a message, inject context and soon enough mutate per policy
(eg change a workflow mid workflow)". This is a **goal, not built**: no code mutates a running run's program or
policy. Nearest built relatives:

| Relative | What it changes | Limit |
| --- | --- | --- |
| Fork with a patch ([precise fork](precise-fork.md)) | A new derived run from a recorded point; typed `RunForkPatch` changes (stage objectives; templates compiled for a new configuration) | A new run, not the running one; frontier closed, old bytes never copied |
| Bounded Goal Revision ([goal loop](goal-loop.md)) | Tactics, subgoals, coverage emphasis of the next iteration or remaining run | Protected envelope (objective, acceptance, authority, budget, outputs); wider changes stop the run |
| Queue, inject, interrupt ([interventions](interventions.md)) | Context and instruction at a boundary | Content, not structure or policy |
| Successor revision (section 1) | The mission's next definition | Applies to new runs only |

What the goal needs beyond these: a policy that names which program or policy fields are mutable and by whom; an
activation of a successor revision against a live run using the specified transition-impact treatments; a read/write
of the mission state snapshot at a safe boundary through Temporal (update or signal) so the family workflow adopts the
new head; carry-forward by digest; and a family-level rule for each workflow system (a Stage Graph's frozen blueprint
and Goal Loop's protected envelope both forbid it today). Compatibility with replay is a constraint: family changes
already ship behind Temporal patches.

Built / specified / goal: revision commit and head built and tested (`tests/unit/control_plane/test_control_plane.py`); proposal, impact and carry-forward specified only; per-policy mid-workflow mutation is an owner goal with no code.

# Citations

- Spec (harvested at `66185d2e`): `workflow-types/07-MISSION_REVISION_AND_RUNTIME_EVOLUTION.md` §§1-10a; owner goal: [answers](../specs/agentic-sdlc-2026-11/answers/AGENTIC-SDLC-SITTING-II-2026-11-02-ANSWERS.md) (AS-D33, *MC context verbatim*).
- Code: [revision writers](../../src/mission_control/adapters/postgres/control_plane/mission_revisions.py), [manifest submission](../../src/mission_control/adapters/postgres/control_plane/manifest_submission.py),
  [canonical run writer](../../src/mission_control/adapters/postgres/run_control/canonical.py), [compiler](../../src/mission_control/domain/authoring/compiler.py),
  [authoring contracts](../../src/mission_control/domain/authoring/contracts.py), [control-plane service](../../src/mission_control/application/authoring/service.py),
  [definition repository](../../src/mission_control/adapters/postgres/control_plane/definition_repository.py), [fork patch](../../src/mission_control/domain/policies/forks.py),
  [fork templates](../../src/mission_control/application/programs/fork_templates.py).
- Tests: [control plane](../../tests/unit/control_plane/test_control_plane.py), [manifest submit](../../tests/integration/postgres/test_manifest_submit.py).
- Schema: [`0002_authoring.sql`](../../packages/mission-control-db-contract/component/migrations/0002_authoring.sql), [`0003_execution.sql`](../../packages/mission-control-db-contract/component/migrations/0003_execution.sql).
