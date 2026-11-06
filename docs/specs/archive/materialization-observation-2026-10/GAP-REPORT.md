---
type: Specification
title: "Capability gap report: environment, cognition and observation control across six coding-agent profiles"
description: "Evidence-backed current state (2026-10-12) of what Mission Control can materialize, configure, isolate and observe for Cursor, Claude Code and Codex, local and provider-hosted, for SDLC and knowledge work; separates Mission Control gaps from provider-imposed limits."
tags: [mission-control, specifications, environments, materialization, observation, gap-report]
---

# Capability gap report — 2026-10-12

Baseline: `main` at `2d20f62` with the owner's uncommitted working tree. Evidence:

- Read-only code audits: [materialization](research/codebase-materialization.md) and [observation](research/codebase-observation.md).
- Primary-source provider fact sheets read the same day: [Cursor](research/cursor.md), [Claude Code](research/claude-code.md) and [Codex](research/codex.md).
- Unit suites run during the audit: 470 tests for projection, workspace, launch and the three lanes, and 192 for subscriptions, streams, hooks and controls. All passed, on Windows with fakes.
- Not run: integration suites, PostgreSQL inbox suites (no `MISSION_CONTROL_TEST_ADMIN_DSN`) and live provider drills.

**No profile is live-qualified.** Every `qualified` flag is `False`.

Statuses used below:

| Status | Meaning |
| --- | --- |
| WIRED+TESTED | The production path exists and has tests. |
| WIRED-UNTESTED | The production path exists without tests. |
| PARTIAL | Some of the behaviour exists. |
| DESIGNED-ONLY | Specified or typed, but nothing calls it. |
| ABSENT | Not there at all. |
| BLOCKED | The provider offers no surface for it. |

## 1. Verdict

Mission Control's **kernel is strong and the last mile is missing**. What works:

- The mission journal, reducers, outbox, Native Event Store and transcript.
- Subscriptions and the coordinator inbox.
- One pure Host Projection renderer with digests.
- The workspace allocator.
- Fail-closed materialization.

These are the right foundations, and none of them needs to be redesigned. What the owner asked for sits *on top of* them, and most of it does not exist yet. The gaps fall into four areas.

1. **Environment control is essentially absent.** The manifest has no field for environment variables, secrets, packages or runtimes, setup scripts, provider environment files, git write policy or enforced network policy.
   - No code writes `.cursor/environment.json` or any setup script.
   - No code selects a provider environment.
   - The environment resolver and readiness attestation are imported only by tests.
2. **Cognition materialization is rendered but cannot be delivered in production.**
   - Skill bundles and hook scripts fail on every lane, because no composition passes bundle custody (`bootstrap/manifests.py:213`, `deployment_composition.py:628`).
   - Instruction files collide with the repo's own. Cursor overwrites `AGENTS.md`; Claude and Codex refuse to start.
   - Codex kernel hooks call a `kernel.py` that the Codex lane never writes.
3. **Observation stops at Mission Control's edge.** Events are durable and replayable, but:
   - Nothing wakes the orchestrating agent.
   - In-environment hooks report back only on `cursor_local`, over loopback.
   - No manifest can declare watchers, callbacks or their limits.
4. **Two of the six cloud/local profiles are blocked by the providers, not by us.** Claude Code cloud sessions and Codex Cloud tasks still have no programmatic status, cancel or event stream (re-validated 2026-10-12). Cursor cloud is the only fully programmable provider-hosted lane, and since late September 2026 it also has REST APIs for environments and secrets.

## 2. Matrix: what Mission Control does today per profile

Code evidence for every cell is in [research/codebase-materialization.md §1](research/codebase-materialization.md).

| Capability | cursor_local | cursor_cloud | claude_agent_sdk | claude_cloud | codex | codex_cloud |
| --- | --- | --- | --- | --- | --- | --- |
| Lane launches at all | WIRED+TESTED | WIRED+TESTED (fakes) | WIRED+TESTED (Linux/WSL only) | ABSENT (stub, refused) | WIRED+TESTED (Linux/WSL only) | ABSENT (stub, refused) |
| Skills | PARTIAL¹ | PARTIAL¹ | PARTIAL¹ | DESIGNED-ONLY | PARTIAL¹ | DESIGNED-ONLY |
| Subagent files | WIRED+TESTED | WIRED+TESTED | WIRED+TESTED | DESIGNED-ONLY | WIRED-UNTESTED | BLOCKED/unknown |
| Hook scripts + config | PARTIAL (kernel only; catalog refused) | ABSENT | PARTIAL¹ | DESIGNED-ONLY | BROKEN (dangling `kernel.py`) | BLOCKED |
| Rules / instructions | WIRED (overwrites repo `AGENTS.md`) | WIRED (overwrites) | PARTIAL (refuses repo files) | DESIGNED-ONLY | PARTIAL (refuses repo files) | DESIGNED-ONLY |
| MCP config | WIRED+TESTED | PARTIAL (file ignored by cloud) | WIRED+TESTED | DESIGNED-ONLY | PARTIAL (no secrets) | BLOCKED |
| Env vars | ABSENT | PARTIAL (not composed) | ABSENT | BLOCKED (UI) | ABSENT | BLOCKED (UI) |
| Secrets | PARTIAL (worker env) | PARTIAL (not composed) | LEAKY (whole worker env) | BLOCKED (UI) | ABSENT | BLOCKED (UI) |
| Packages / runtimes setup | ABSENT | ABSENT | PARTIAL (exe check) | BLOCKED (UI) | PARTIAL (exe check) | BLOCKED (UI) |
| Provider environment file / record | n/a | ABSENT | n/a | BLOCKED (UI) | n/a | BLOCKED (UI) |
| Git read | WIRED+TESTED | PARTIAL | WIRED+TESTED | BLOCKED | WIRED+TESTED | BLOCKED |
| Git push / PR | ABSENT | PARTIAL (ambient creds) | ABSENT | DESIGNED-ONLY | ABSENT | DESIGNED-ONLY |
| Worktree isolation per attempt | WIRED (fixed policy) | PARTIAL (lease not composed) | WIRED+TESTED (policy honoured) | BLOCKED | PARTIAL (ignores policy) | BLOCKED |
| Network policy | PARTIAL (sandbox flag) | ABSENT | ABSENT | BLOCKED | PARTIAL (`sandbox_mode`) | BLOCKED |
| Owner preflight (manual steps listed before spawn) | PARTIAL (installation only) | PARTIAL | PARTIAL | ABSENT | PARTIAL | ABSENT |
| Knowledge work without a target repo | ABSENT² | ABSENT² | ABSENT² | ABSENT | ABSENT² | ABSENT |
| In-environment hooks → Mission Control | WIRED+TESTED (loopback) | ABSENT | in-process only | ABSENT | BROKEN | BLOCKED |
| Native frames observed | WIRED+TESTED | WIRED+TESTED (SSE + poll) | WIRED+TESTED | ABSENT | WIRED+TESTED | ABSENT |

¹ The renderer works, but nothing can fetch stored bundles in production (no custody composed).

² Every provider lane requires `workspace.repo` at launch (`manifest_launch_inputs.py:854,1103`). The Cursor "research lease" is unreachable, and there are no corpus or data mounts.

## 3. What the providers allow (2026-10-12)

Summary of the [materialization maps](research) in the three fact sheets.

| Lever | Cursor local | Cursor cloud | Claude local (CLI/SDK) | Claude Code cloud | Codex local (CLI/app-server) | Codex Cloud |
| --- | --- | --- | --- | --- | --- | --- |
| Skills | `.cursor/skills`, `.agents/skills` (+ reads `.claude/skills`, `.codex/skills`) | Repo skills yes | `.claude/skills`; SDK via `setting_sources` | Repo skills yes | `.agents/skills`, `.codex/skills` | Repo skills yes |
| Subagents | `.cursor/agents/*.md` (5 fields) | Repo files + inline `customSubagents` (≤20) | `.claude/agents/*.md` (rich: tools, model, hooks, `isolation: worktree`, skills…) | Repo files yes | `.codex/agents/*.toml` (trusted project) | UNVERIFIED |
| Hooks | `.cursor/hooks.json`, 21 events | Command hooks only, 14 events (no session start/end) | Settings hooks, 33 events, `command`/`http`/`mcp_tool`/`prompt`/`agent`; `onFailure: block` | Same, from committed settings, single-repo sessions only | `hooks.json`, 12 events, `command`/`mcp_tool`; **hash trust required** | Not supported for repo/command hooks (UNVERIFIED for tasks) |
| MCP | `.cursor/mcp.json` | **File ignored**; inline `mcpServers` per launch or dashboard | `.mcp.json` | `.mcp.json` (single-repo; no localhost) | `[mcp_servers]` (trusted) | Local servers unavailable |
| Environment definition | `.cursor/worktrees.json` setup | `.cursor/environment.json` **or** REST `/v1/environments` (repo file wins) | n/a (we own the host) | UI only; per-repo default pin via committed `remote.defaultEnvironmentId` | `.codex/environments/environment.toml` (desktop app) | UI only |
| Env vars / secrets | Process env | REST team/environment secrets; launch `envVars` (beta) | Process env / `options.env` | UI only (Pro/Max network secrets) | Process env / `shell_environment_policy` | UI only (network secrets via proxy) |
| Per-mission setup carrier | We run it | Build `install` (default-branch config) and `start`/`terminals` per agent | We run it | **`SessionStart` hook guarded by `CLAUDE_CODE_REMOTE`** (600 s) | We run it | None per task |
| Git | Our clone | GitHub app; `repositoryDependencies`; auto-PR | Our clone | GitHub proxy; `claude/...` branches; session trailer on commits | Our clone | GitHub connector |
| Launch / observe / cancel API | SDK | REST v1 + SSE + v0 webhook; one run per agent | SDK | **None adequate** (routine trigger only; no status/cancel) | app-server | **None adequate** (`codex cloud exec` experimental; status/list poll) |
| Callback from inside the env | Loopback | Hooks can POST; **VM-minted OIDC JWT** for auth | In-process callbacks / http hooks | **HTTP hooks** to an allowlisted host (Custom/Full network) | Hooks/`notify` | Egress possible; no hooks |
| Native worktrees | `agent -w`, `.cursor/worktrees.json`; **cleanup may delete non-Cursor worktrees** | VM + branch per agent | `--worktree`, `WorktreeCreate` hooks, subagent isolation | VM + branch per session | Desktop app worktrees | Task isolation |

**Provider-imposed hard limits** (not ours to fix):

- **Claude Code cloud:**
  - No session list, status, cancel or event API.
  - Session control needs a human `claude auth login` every 30 days.
  - Environments, env vars and secrets are UI-only.
  - Repo-declared plugins are not installed.
- **Codex Cloud:**
  - Environments are UI-only.
  - No follow-up, cancel or event API.
  - Hooks are not supported under cloud orchestration.
- **Cursor cloud:**
  - Build triggers, Build pinning, user secrets and Build Secrets are dashboard-only.
  - v1 webhooks are "coming soon".
  - One active run per agent.
  - The cloud has no `sessionStart` or `sessionEnd` hook.
  - A committed `.cursor/environment.json` overrides any API-created environment for that repo.

## 4. Observation and callbacks: current state

Evidence: [research/codebase-observation.md](research/codebase-observation.md).

| Need | Today |
| --- | --- |
| Durable event journal, replay, transcript | WIRED+TESTED |
| SSE `events watch`, Socket.IO dashboard stream | WIRED+TESTED (no browser interop test; Redis publishers unwired) |
| Webhook subscriptions | WIRED+TESTED. Opt-in relay env var; https **global** targets only; payloads are references only. |
| Coordinator inbox (significance, batching, rate and recursion caps) | WIRED via HTTP. On MCP only the **unauthenticated dev server** has it. No long-poll, no CLI verb. |
| MCP `mission_subscribe` push | TESTED-UNWIRED: stateless HTTP and no notifier composed. Not model-visible even if fixed. |
| Coordinator auto-subscribe on launch (ADR-0032) | DESIGNED-ONLY |
| Wake an idle orchestrating Claude Code / Codex / Cursor session | ABSENT |
| Hook signals from provider VMs | ABSENT. The listener is loopback-only, and `HookCallbackEndpoint` is never populated. |
| Agent-emitted milestones ("blocked", "artifact ready") | ABSENT |
| Manifest watchers, triggers, conditions, recipients, limits | ABSENT. `controls.notifications` is parsed and ignored but still taught by the author skill; `channel: mcp` is dead. |
| `event_wait` satisfied by an external event (PR merged, CI green, file arrived) | PARTIAL. Only a manual `satisfy_wait` releases it. |
| Provider push signals (Cursor v0 `statusChange`, Claude cloud HTTP hooks/OTel) | Unused |
| Observe skill | Stale. Advertises a broken push, omits the inbox, has no wait recipe. |

**The owner's prior watcher scripts** fall into six families: supervisors, scheduled wakeups, HTTP callbacks, poll-until-done loops, Cursor `stop` hooks and Markdown ledgers.

- All of them signalled through files, log lines or exit codes. None pushed to the orchestrating agent.
- Recurring failures: stop/claim races, wrong-run wakes, orphaned schedulers, Windows quirks (BOM, PATH, sleep), rotating tokens, weak health signals, pollers abandoning live remote work, and handoffs lost when the orchestrator hit usage limits.

Mission Control's journal, inbox and dedupe already solve durability. Waking the orchestrator and receiving signals from remote environments are the parts that remain.

## 5. Ranked gaps

Impact is measured against the owner goal: an orchestrating agent spawns and controls local and cloud missions for SDLC and knowledge work, with materialized cognition and environment and formal observation.

| # | Gap | Kind | Spec |
| --- | --- | --- | --- |
| G1 | Bundle custody not composed, so skills and hook scripts fail on every lane in production | MC defect | [SPEC-02](SPEC-02-cognition.md) |
| G2 | No environment model: env vars, secrets, setup/runtimes, network, git write | MC absent | [SPEC-01](SPEC-01-environments.md) |
| G3 | No provider environment projection or selection (`environment.json`, Cursor environments/secrets API, Claude/Codex UI binding) | MC absent | SPEC-01 |
| G4 | No owner prerequisite catalog or pre-spawn preflight that tells the owner exactly what to do | MC absent | [SPEC-05](SPEC-05-owner-prerequisites.md) |
| G5 | Nothing wakes the orchestrating agent; no wait or long-poll; MCP surface split; auto-subscribe missing | MC absent | [SPEC-04](SPEC-04-watchers-and-callbacks.md) |
| G6 | No authenticated public signal ingress, so cloud lanes are blind beyond provider APIs | MC absent | SPEC-04 |
| G7 | Manifest cannot declare watchers, callbacks, conditions, actions or boundaries | MC absent | SPEC-04 |
| G8 | Instruction-file collision: repo `AGENTS.md`/`CLAUDE.md` overwritten or refused | MC defect | SPEC-02 |
| G9 | Knowledge, research and content missions cannot launch without a target repo; no corpus or artifact channel | MC absent | [SPEC-03](SPEC-03-workspaces-and-placement.md) |
| G10 | Worktree policy inconsistent (Codex and Cursor ignore the manifest); cleanup never runs; cloud lease not composed | MC defect | SPEC-03 |
| G11 | Codex kernel hooks dangling; Codex hook trust not handled; Cursor cannot carry hook scripts or plugins | MC defect | SPEC-02 |
| G12 | Claude child process inherits the whole worker environment (credential leak); Codex strips the secrets its MCP servers need | MC defect | SPEC-01 |
| G13 | Cross-provider ambient cognition: Cursor also loads `.claude/*` and `.codex/agents`; nothing inventories or reports it | MC absent | SPEC-02 |
| G14 | No discovery proof that a provider actually loaded what we materialized | MC absent | SPEC-02 |
| G15 | `claude_cloud` and `codex_cloud` have no lane | Provider-blocked; decision needed | [DECISIONS](DECISIONS.md) |
| G16 | Local Claude and Codex lanes refuse Windows hosts; the owner's machine is Windows | MC constraint | MO-08 (decision D5) |
| G17 | Stale docs: capabilities, cursor-lane, lanes-and-harness, release statement on Codex hooks, author cheatsheet `notifications` | Docs | MO-07 |

## 6. What is already right and must be reused

- **Host Projection** (`application/agentic_components/projections.py::render_host_files`): one pure renderer with a degradation report. Extend it; do not create a second renderer.
- **`EnvironmentBinding`** already has slots for `secret_refs`, `network_policy_ref`, `setup_pin`, `observed_config_digest` and readiness. Populate them; do not invent a parallel binding.
- **`WorkspaceAllocator`** with dedicated clones, unique branches, snapshots and restore. Make every local lane use it.
- **Coordinator inbox** with significance kinds, batching, rate and recursion caps. This becomes the delivery target for watchers and wake channels.
- **Hook contract** `mc.hook_input.v1`/`mc.hook_result.v1` and the `HookCallbackEndpoint` slot. Populate the slot for remote ingress.
- **SPEC-02 (multi-provider) principles stay in force:**
  - pinned bundles;
  - "a generated file does not prove the provider loaded it";
  - no secrets in Git;
  - kernel controls outside agent-writable configuration;
  - `localhost` in a provider VM is not this computer.

## 7. Addendum — second pass (2026-10-12): hosted API lanes, Cursor maturity, local CLI skills

The owner approved API billing and asked for full maturity on Cursor, Anthropic Managed Agents and OpenAI Agents, plus local CLI skills ([DECISIONS](DECISIONS.md) R1–R7).

| # | Gap | Kind | Spec |
| --- | --- | --- | --- |
| G18 | No `claude_managed` profile. Managed Agents is a different harness from Claude Code (correction C1). The API covers sessions, events, approvals, budgets and webhooks; hooks, fork and an idempotency key are missing. | MC absent | [SPEC-06](SPEC-06-hosted-api-lanes.md) |
| G19 | No `codex_agents` profile. The Agents API is the closed Codex harness: cancel and steer exist; approval of shell or patch, hooks, fork, diffs and a replay cursor are missing. | MC absent | SPEC-06 |
| G20 | No Sandbox Host. Self-hosted executors for both APIs, and the real Claude Code and Codex harnesses on rented compute, need one provider-neutral port and a keyless Model Gateway. | MC absent | SPEC-06 §2 |
| G21 | No shared remote-session machinery and no lane conformance suite. Describe-honesty tests cover Cursor only. | MC absent | SPEC-06 §3 |
| G22 | Cursor defects: parallel units share a workspace; cloud `outputs/` never registered; continuation drops settings; a missing staged turn resends the original prompt; both SSE vocabularies persisted | MC defect | [SPEC-07](SPEC-07-cursor-maturity.md) |
| G23 | Cursor accounting and durability: per-run usage misattributed; cloud cost never composed; local bridge dies with the worker; Windows refused | MC defect | SPEC-07 |
| G24 | No data-class policy. Neither hosted API is ZDR-eligible. | MC absent | SPEC-06 §8 |
| G25 | No local skills for driving the Claude Code, Codex and Cursor CLIs; no job runner | Absent | [SPEC-08](SPEC-08-local-cli-skills.md) |

Evidence:

- [research/anthropic-managed-agents.md](research/anthropic-managed-agents.md)
- [research/openai-hosted-agents.md](research/openai-hosted-agents.md)
- [research/cursor-maturity.md](research/cursor-maturity.md)
- [research/local-cli-skills.md](research/local-cli-skills.md)
- [research/codebase-new-lanes.md](research/codebase-new-lanes.md)

Tests run in the second pass: Cursor unit tests (262 passed), lane contracts and registry (49 passed) and describe honesty (76 passed), all on Windows with fakes. No integration or live runs.

## 8. Addendum — final pass (2026-10-12): what the machine and accounts actually allow

| # | Finding | Effect | Where |
| --- | --- | --- | --- |
| G26 | S0 cannot run today. All three CLI lanes refuse a Windows worker. WSL lacks Node, `claude`, a working `codex`, a current uv and Python 3.12. No operator files exist (62 unresolved binding values). Codex launches signed out in isolated homes without a guard. Preflight cannot see a local 1.3.0 release. | S0 issues MO-63 to 72, MO-08 | [SPEC-09](SPEC-09-local-harness-path.md) |
| G27 | Ingress infrastructure gaps. The Vercel team is on Hobby (non-commercial). The live Supabase databases are at component 1.0.0 (the repo is at 1.3.0; ingress needs 1.4.0). Vercel cannot reach local Postgres, and its request bodies are capped at 4.5 MB. | MO-40, MO-74 to 76; owner inputs | [SPEC-10](SPEC-10-ingress-on-vercel.md) |
| G28 | Daytona constraints. Stdin is text lines only, with no EOF. Per-sandbox egress allowlists need Tier 3+. Container snapshots are filesystem-only and need a stop. Auto-stop ignores background work. | HL-01, HL-02; SH2/SH3 | [SPEC-06 §12](SPEC-06-hosted-api-lanes.md) |
| G29 | CLI flag errors in the first SPEC-08 draft: Codex `-a` on `exec`, `--full-auto`, resume argument order. The owner's Codex user config defaults to `danger-full-access`. | LS-03 and LS-06 corrections | [SPEC-08 §10](SPEC-08-local-cli-skills.md) |
| G30 | The Claude SDK skips SessionStore resume with a custom transport. The existing local lane may never restore mirrored sessions. | MO-73 | SPEC-06 §6 |

**Update (2026-10-12, owner readiness decisions R16–R22):**

- G27: Vercel is Pro (team `overtons-projects`), and the live upgrade is approved: 1.3.0 is applied with the checkpoint, and 1.4.0 is pre-approved.
- G28: the egress part is resolved without Tier 3, because the gateway and ingress are served from `*.vercel.app`, which is on Daytona's essential-services list.
