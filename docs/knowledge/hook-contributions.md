---
type: Concept
category: execution
title: "Hook context contributions: scoped reads, staged candidates and safe-boundary install"
description: "How a hook script reads only its declared scopes, proposes attributed candidate files and operation requests, and how the host installs candidates exactly once at a safe boundary (WI-17); what stays gated."
tags: [mission-control, hooks, context, output-contracts, deep-agents, sprint]
aliases: [hook candidates, safe-boundary install, WI-17, scoped hook reads]
questions:
  - How can a hook read scopes and stage files for the agent?
  - When does the host install a hook's candidate files?
  - Why does a Deep Agents node refuse a selected hook script at launch?
  - What can a hook ask for besides staging files?
updated: 2026-11-01
---

# Hook context contributions

The decision is [ADR-0062](../adr/0062-durable-reactions-and-host-validated-context-contributions.md), which
partly supersedes [ADR-0026](../adr/0026-hook-scripts-one-event-vocabulary-projected-per-lane.md):
a hook sees a bounded event snapshot plus explicitly scoped host-mediated reads, stages candidate
files the host validates and installs, and asks for model or external work as a separate ordinary
operation. This page explains how current source realizes that (Sprint OC WI-17, OVE-180).

**What a result may do depends on the event.** [`event_role`](../../src/mission_control/domain/context/contributions.py)
maps every Hook Event to the §11 table: a *before-effect guard* (`session_start`, `before_prompt`,
`before_model`, `before_tool`, `before_shell`, `before_mcp`, `subagent_start`) answers allow/deny and
its deny prevents the not-yet-executed action; an *observation* event (`after_*`, `subagent_stop`,
`stop`, `session_end`) may add findings, staged candidates and operation requests, and its deny is a
finding that cannot undo the committed effect (`HookScriptMiddleware._post` appends it to the kept
tool result); `before_compaction` carries a preservation proposal consumed by the compaction
wrapper (WI-18). A candidate or request returned at a guard event refuses `RESULT_NOT_PERMITTED`.

**Declared, least-privilege reads.** A hook declares `host_reads` (`HostReadScope`): `workspace`
path patterns (`*` within a segment, `**` across) or `transfer_input` binding names of the
attempt's sealed plan. Patterns naming the whole workspace or host-owned `/.mission/` state refuse
at declaration; there is no Knowledge Services, credential or private-middleware read kind. At
dispatch [`HookReadBroker`](../../src/mission_control/application/context/hook_contributions.py)
reads each literal path, each declared binding and each path the event itself names (a file a tool
read or edited) through the receiver's actual backend and puts them in `mc.hook_input.v1` `reads`;
a path outside every scope refuses `READ_OUT_OF_SCOPE`, host state `READ_HOST_PRIVATE`, an oversize
or binary file `READ_TOO_LARGE`/`READ_NOT_TEXT` (nothing is truncated), and a transfer input whose
bytes differ from the sealed plan's digest `READ_DIGEST_MISMATCH` (today's file never substitutes).

**Staged candidates carry no origin.** `mc.hook_result.v1` `staged_candidates` holds path intent,
text, declared digest and media type; the host attributes each to the invocation
(`CandidateOrigin`: hook, event, run, operation, attempt, generation, execution, input digest),
checks the digest and stages the bytes content-addressed in custody. A script cannot name an
origin or an install state (closed schemas). The candidate identity is a deterministic digest of
hook, receiver, attempt, generation, path and bytes, so a hook retried within the attempt re-stages
the same candidate. Every collect is visible: a `mc.hook_contribution_collected` stream event (a
provider frame) names what was staged, each typed refusal and each operation-request admission
receipt (`CollectOutcome`).

**Installation happens only at a safe boundary.** On Deep Agents that boundary is the start of a
model call after the pre-model guards allowed it (no tool in flight); the agent's next tool call
reads the file through the same backend. [`HookContributionService.install_context_candidates`](../../src/mission_control/application/context/hook_contributions.py)
applies, in order: the domain policy (`install_refusal`: never `/.mission/` or the transfer index
`HOST_STATE_OVERWRITE`; never `/inputs/` or a used plan path `SEALED_INPUT_REWRITE`; never an output
slot `OUTPUT_SLOT_PATH`, because the adapter captures files there as the agent's output; never a
seeded slot, mount or Skill root `PROTECTED_PATH`; only inside the hook's `StageGrant`
`PATH_OUT_OF_GRANT`), per-boundary collisions and budgets, current authority (the run's stop fence,
`GENERATION_FENCED`), a version check (other bytes at the path are never overwritten,
`VERSION_CONFLICT`), then a durable **claim** of the receiver path and one durable **outcome** after
the write is read back through the backend.

**Exactly once across races and crashes, per attempt.** The claim is unique per (run, receiver
operation, receiver attempt, execution generation, path): of two racing candidates one claims, the
other refuses `PATH_CLAIMED`. A retry attempt (a fresh backend) is another receiver: it installs
anew and never inherits or replays an earlier attempt's claims; a recorded install whose bytes are
no longer present refuses `INSTALLED_FILE_ABSENT` instead of being reported installed. The outcome is unique
per claim. A backend durable on write (a sandbox) records the outcome at once; the Deep Agents state
channel is durable only after its step commits, so the claim stays `pending` and the next boundary
confirms it by reading it back (`settle_pending`). The same settlement recovers a crash: a claim
without an outcome whose bytes are present is recorded once (`recovered`), absent bytes are written
again from custody, and a claim with an outcome is never written again. Settlement runs the same
policy and current-authority checks as installation, so a fenced run settles nothing.

**Candidates staged at the final answer are refused visibly.** The Deep Agents boundary is before a
model call; after the final answer (`after_model`, `stop`, `session_end`) there is none, so
`ContributionSession.close` refuses every still-staged candidate `CANDIDATE_NOT_INSTALLED` and the
lane emits `mc.hook_contribution_closed`. A state-channel install made at the last boundary stays
`pending` (its file is in the final state, its outcome is not recorded) because no later step
confirms the commit. The materializer also closes the session when the attempt's stack tears down,
so an attempt that ends in an error, a cancel, the recursion limit or a final answer without `stop`
still refuses its leftovers (logged; emitted when a graph stream is live). Contribution events carry
a per-session `sequence` in their ids, and a hook-supplied path in a refusal event is a digest plus at
most 64 sanitized characters.

**Known dead ends.** A same-attempt checkpoint rollback after an outcome was recorded (the state
returns to before the install) leaves the outcome in place: the re-staged candidate refuses
`INSTALLED_FILE_ABSENT` and is never reinstalled in that attempt; only a new attempt (a new receiver)
installs it again. A transient backend read error is read as *absent* (`_current` returns no bytes):
before an outcome exists that can trigger a write the version check would otherwise have refused,
and after one it reports `INSTALLED_FILE_ABSENT`; read errors are not yet distinguished from absence.
The sealed plan for `transfer_input` reads is keyed by backend identity with a weak reference; a
backend that cannot be weakly referenced gets no plan (logged, `mc.hook_transfer_plan_unattached`),
and its transfer reads refuse `READ_UNAVAILABLE`.

**Nothing installed fulfills a promise.** An install record is not a submission act, an accepted
head, a transfer delivery receipt or an output-slot capture; the service has no output-contract
port. Operation requests (`OperationRequestProposal`: template, purpose, request key) are admitted
only for templates in the hook's grant and only through `OperationRequestPort`; with no port
composed they refuse `OPERATION_REQUEST_UNWIRED`, and no script ever runs model work or an
external write itself.

**Where it lives.** Pure rules: `domain/context/contributions.py`. Contracts:
[`contracts/hooks.py`](../../src/mission_control/contracts/hooks.py) (`HostRead`, `reads`,
`staged_candidates`, `operation_requests`, each absent from dumps and digests while empty); the
declarations on `HookScriptDefinition` and `DeepAgentHookScriptComponent` (`host_reads`, `stage`,
digest-neutral while undeclared). Lane: `HookDispatcher` (per-script reads and attribution) and
`HookScriptMiddleware` (the boundary) in [`adapters/deep_agents/hooks.py`](../../src/mission_control/adapters/deep_agents/hooks.py),
`DeepAgentCandidateWorkspace` and `FenceGrantCheck` in `adapters/deep_agents/hook_contributions.py`,
the session composed by `ExactDeepAgentMaterializer` (a binding that declares contributions with no
composed `hook_contributions` service refuses to prepare). Persistence:
[`PostgresCandidateInstallStore`](../../src/mission_control/adapters/postgres/context/candidate_installs.py)
over `context_candidate_install` / `context_candidate_install_outcome`
(`scripts/release_170/0060_hook_candidate_installs.sql`).

**Proof and limits.** `tests/unit/context/test_hook_contributions.py` (policy, race, crash,
no self-fulfillment, requests), `tests/unit/deep_agents/test_hook_contributions_graph.py` (a
compiled Deep Agents graph with real hook subprocesses), and
`tests/integration/postgres/test_hook_candidate_installs_postgres.py` (0060 on the built 1.7.0
migrations). Migration 0060 is in the built 1.7.0 component (`releases/1.7.0/component/manifest.json:283`). Not yet: production composition wires no store,
service or admission port (so declared contributions refuse at prepare); the Deep Agents compile
path still refuses selected hook scripts (`describe.py`), so no manifest reaches this at launch;
other lanes keep their declared hook exceptions (OC-D199). Protected effects additionally gate on
WI-03/WI-05. Recorded limits (review nits 8-11): a sandbox backend's symlinks are not resolved, so a
path policy check is lexical (case-folded) and a link inside an allowed directory could point at a
protected one; `ProtectedPaths.sealed_paths` is not populated by the materializer (sealed
placements all lie under `/inputs/`, which the rule refuses for every receiver); bytes are staged in
custody before the per-boundary budget is applied, so an over-budget candidate still occupies custody;
two hooks proposing the same bytes at the same path are distinct candidates (attribution is per
hook), so the second refuses `PATH_CLAIMED`. Contribution events are recorded as `unknown` frame
kinds until a typed kind is added.

Built / specified / goal: policy, install store and graph proofs tested; production composition wires no store or service and no manifest reaches it at launch (specified, not integrated).

## Citations

- Code: [contribution rules](../../src/mission_control/domain/context/contributions.py),
  [hook contracts](../../src/mission_control/contracts/hooks.py),
  [contribution service](../../src/mission_control/application/context/hook_contributions.py),
  [Deep Agents hooks](../../src/mission_control/adapters/deep_agents/hooks.py),
  [Deep Agents workspace and fence check](../../src/mission_control/adapters/deep_agents/hook_contributions.py),
  [materializer](../../src/mission_control/adapters/deep_agents/materializer.py),
  [install store](../../src/mission_control/adapters/postgres/context/candidate_installs.py),
  [migration 0060](../../scripts/release_170/0060_hook_candidate_installs.sql).
- Tests: [service and policy](../../tests/unit/context/test_hook_contributions.py),
  [compiled Deep Agents graph](../../tests/unit/deep_agents/test_hook_contributions_graph.py),
  [PostgreSQL install records](../../tests/integration/postgres/test_hook_candidate_installs_postgres.py).
