---
type: Specification
title: "SPEC-03: Workspaces, worktrees and parallel placement for SDLC and knowledge missions"
description: "One allocator for every local lane, mission branches as the cloud worktree equivalent, fan-out with per-provider concurrency, knowledge workspaces that do not need a target repo, output collection and cleanup."
tags: [mission-control, specifications, worktrees, workspaces, parallelism, knowledge-work]
---

**Run 2 close-out disposition (2026-10-18, Gate L):** Gate L: the three-local-lane `within_run`/dirty-refusal/cleanup clause, proven on the S0 cells. Carried forward: cursor_cloud fan-out and the knowledge mission on cursor_cloud (S1). Deferred by the owner: cloud→local fork (MO-53). Criteria below are unchanged; see [the disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and [close-out instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).

# SPEC-03: Workspaces, worktrees and parallel placement

Gaps closed: G9 and G10 ([gap report](GAP-REPORT.md)). ADR-0037 stands: **Mission Control allocates the workspace; the agent never decides whether isolation exists.**

## 1. Unit of isolation

Every writable execution unit (attempt, Parallel Swarm member, Mission Chain link) gets its own **Workspace Lease**. The lease is one of two kinds:

| Placement | Lease is | Branch |
| --- | --- | --- |
| Local (all three providers) | A git worktree from Mission Control's dedicated clone under the admitted workspace root, at a pinned base commit | `mc/{run}/{unit}` |
| Provider-hosted | A **mission branch**, created by Mission Control from the pinned base commit and pushed before launch. It carries the mission layer and the cognition pack. The provider's VM is the isolation. | `mc/{run}/{unit}`. When the provider forces its own prefix (`claude/...`, `cursor/...`), Mission Control records the mapping from the observed branch. |

So "spawn N cloud worktrees" means N mission branches and N provider sessions. Locally it means N worktrees and N sessions, bounded by the host's slot policy.

## 2. Local allocator for every lane (G10)

- **One policy for every lane.** Codex (`codex/harness.py:571-580`) and Cursor local (fixed `CURSOR_LOCAL_POLICY`) adopt the manifest's `workspace.policy` through `WorkspaceAllocator`, as Claude already does.
- **Cleanup is wired.** `WorkspaceAllocator.cleanup` runs from the operation workflow after Artifact registration and liability settlement. It is idempotent, removes only the owned lease, and never force-deletes a dirty worktree whose work has not been snapshotted. Failed work is retained for the retention interval.
- **`shared_checkout` is reachable** through `join_shared`. It is used for read-only helpers, or when policy explicitly declares a coordination model.
- **Interplay with provider-native worktrees:**
  - The Mission Control root stays **outside** `~/.cursor/worktrees` and `$CODEX_HOME/worktrees`.
  - Cursor's machine-wide cleanup (`cursor.worktreeMaxCount`, default 25) may delete worktrees it did not create, so qualification item Q-W1 verifies that Cursor's cleanup never touches the Mission Control root. Until that is verified, the preflight warns on hosts where Cursor desktop is installed.
  - Provider-native nested worktrees (Claude subagent `isolation: worktree`, `claude --worktree`, Cursor `/best-of-n`) are allowed only *inside* the lease, when policy says `nested_worktrees: allow`. Their branches must use the lease's branch as base and are recorded as subordinate artifacts.
- **Windows host (G16).** The local Claude and Codex lanes currently refuse Windows. Two options:
  - **(a)** Make WSL2 the default local worker for those lanes, with the Mission Control root on the WSL filesystem. Recommended: it matches the existing Linux qualification.
  - **(b)** Qualify native Windows for the Claude CLI and Codex.

  The choice is [DECISIONS](DECISIONS.md) D5.

## 3. Cloud branch preparation

Before a provider-hosted launch, Mission Control:

1. Resolves the base commit for `git.repos[target].ref`.
2. Creates `mc/{run}/{unit}` from it.
3. Commits the mission layer (`.mission/setup/`), the cognition pack files (SPEC-02 delivery mode `branch_commit`) and the Context Packet. The commit passes the secret scan from SPEC-01 §4.
4. Pushes with the Mission Control GitHub App or an owner credential.
5. Launches against that branch.

How each provider's launch takes the branch:

- **Cursor:** `startingRef` plus `workOnCurrentBranch`, which exists today.
- **Claude cloud:** the session or routine starts on that branch (Q-L1).
- **Codex Cloud:** `codex cloud exec --env <id> --branch`, where the flag is supported (Q-X3).

**Large inputs never go into the branch.** The current Cursor cloud behaviour of committing input files is replaced:

- Inputs over 256 KiB, or classified sensitive, are referenced as Artifact URLs.
- The environment fetches them at run time through the Knowledge Services MCP, a signed URL or the ingress artifact endpoint (SPEC-04).

## 4. Knowledge workspaces (G9)

Claude Code cloud and Codex Cloud launch only against a GitHub repository.

*Correction, 2026-10-12, second pass:* Cursor cloud agents can run without a repo (CM-22), and `claude_managed` and `codex_agents` sessions need no repo at all ([SPEC-06](SPEC-06-hosted-api-lanes.md)).

The rules for knowledge, research, ingestion and content missions are therefore:

- **Lanes that need a repo:** the mission gets a **knowledge workspace repo** instead of being refused.
- **Lanes that need no repo:** a repo is optional. Inputs come through Files/artifacts and Knowledge Services MCP, and outputs come back through artifacts or ingress.

The binding rule `hosted bindings require repo_url+repo_commit` (`bindings.py:271-275`) and the v2 rule `workspace.repo required` (`manifest_v2.py:317`) are relaxed per profile.

- **Repo.** One owner-created private repo per Application, recorded in the Application Binding: `Overton77/bell-missions-biotech` and `Overton77/bell-missions-ai-engineer` (DECISIONS R23; the AI Engineer repo is currently public).
  - It holds `README`, `AGENTS.md` (knowledge-work conventions) and the base environment kit marker.
  - Each mission works on its own `mc/{run}/{unit}` branch and never on the default branch.
- **Manifest.**

  ```yaml
  workspace:
    kind: knowledge          # code (default) | knowledge | mixed
    repo: {use: application_knowledge_repo}   # or an explicit url
    inputs:
      - {artifact: "art_..."}                  # fetched at runtime
      - {knowledge_query: "...", via: knowledge_services}
    outputs:
      dir: outputs/
      collect: [artifact_upload, branch_commit]   # artifact_upload preferred
  ```

- **Mixed missions** use `kind: mixed`. The target code repo is the lease. The knowledge inputs and outputs follow the same `inputs` and `outputs` rules, and outputs go to `outputs/` on the mission branch (excluded from the code PR by `.mission/pr-exclude`) and to Artifacts.
- **Local lanes.** The knowledge workspace may be a plain directory lease with an initialized repo. The existing Cursor "research lease" (`adapters/cursor/workspace.py:188-230`) becomes reachable from the manifest, so no GitHub repo is needed locally.
- **Output collection** is a closed list of channels:
  1. Artifact upload through the ingress artifact endpoint (authenticated per run; SPEC-04).
  2. Commit on the mission branch, read back through GitHub.
  3. Cursor artifacts API.
  4. `codex cloud diff`.

  The Completion Contract names which channel is the evidence. Execution completion is not acceptance (AGENTS.md invariant).

## 5. Parallel placement

**Fan-out** (Parallel Swarm members, Mission Chain links released together, or coordinator-launched independent missions) is admitted against **per-provider concurrency budgets** in the installation config:

```yaml
placement_limits:
  cursor_cloud: {max_active_agents: 8, launches_per_minute: 15}   # API default 20/min; plan caps undocumented
  claude_cloud: {max_active_sessions: 4}                           # shared account rate limits
  codex_cloud: {max_active_tasks: 4}
  local: {max_writable_leases: 3, cpu_reserve: 2}                  # protects the owner's machine
```

- **Waiting.** A launch that exceeds its budget becomes a durable wait (Temporal) with the same deadline semantics as rate-limit waits. It is never a busy loop.
- **Placement preference.** For bulk or long parallel work, cloud placements come first, so that local slots stay free for interactive work. A manifest or coordinator can set `placement: prefer_cloud | cloud_only | local_only`. The resolver picks the first lane profile in the manifest's `lanes:` preference list whose qualification, prerequisites and budget all pass.
- **Convergence.** Members' branches are compared or merged through Mission Control Governed Effects (`repo_merge`, `repo_pr`). The Parallel Swarm convergence rules are unchanged.

## 6. Snapshots and forks

The existing snapshot and restore contract stays. Two additions:

- **Cloud leases.** A snapshot is the observed head SHA of the mission branch. Producing `branch:<branch>@<sha>` is now the job of the branch-preparation and collection step, closing the "needs a producer" note in multi-provider SPEC-02.
- **Cross-lane forks.** A local fork of a cloud attempt fetches the mission branch into a new local lease. A cloud fork of a local attempt snapshots the lease, pushes `mc/{run}/{unit}-f{n}` and launches against it. Conversation transfer follows ADR-0039 continuation, never a copied provider transcript.

## 7. Acceptance

- The three local lanes run with `policy.reuse: within_run`, a dirty-input refusal and cleanup after registration. The worktrees are removed and the snapshots are retained.
- **Fan-out of 5 cursor_cloud members** against one repo:
  - produces 5 `mc/{run}/m{i}` branches, 5 agents and 5 head-SHA artifacts;
  - throttles correctly when `max_active_agents: 3`.
- **A knowledge mission with no code repo:**
  - launches on cursor_cloud against the knowledge workspace repo;
  - fetches an Artifact input at run time;
  - uploads an output Artifact that satisfies its Completion Contract.
- A forked cloud→local attempt reproduces the cloud head SHA in a local lease.
