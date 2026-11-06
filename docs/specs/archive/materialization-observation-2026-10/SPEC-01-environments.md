---
type: Specification
title: "SPEC-01: Environment materialization — variables, secrets, runtimes, network, git and provider environments"
description: "Environment Kits, a two-layer base/mission setup model with one bootstrap entrypoint, a secret broker with per-lane delivery, network and git policy, and per-provider projection for Cursor, Claude Code and Codex, local and provider-hosted."
tags: [mission-control, specifications, environments, secrets, git, materialization]
---

**Run 2 close-out disposition (2026-10-18, Gate L):** Gate L (close in Run 2): the **Local lanes** clauses and the secret-sentinel clause, proven on the S0 cells and fixtures F1/F3. Carried forward: the **cursor_cloud with `sync`** clauses (S1). Known gap closed first: `config:<key>` installation source (P1). Criteria below are unchanged; see [the disposition](runs/RUN-2-GATE-L-DISPOSITION-2026-10-18.md) and [close-out instructions](RUN-2-CLAUDE-CODE-OPUS-INSTRUCTIONS-2026-10-18.md).

# SPEC-01: Environment materialization

Extends [multi-provider SPEC-02](../multi-provider-2026-10/SPEC-02-environments.md); its principles stay in force. This spec adds what that one left unmodelled:

- variables and secrets;
- packages and runtimes;
- provider environment files and records;
- git write access;
- enforced network policy;
- a setup model that works the same way across six profiles.

Gaps closed: G2, G3, G12 and part of G4 ([gap report](GAP-REPORT.md)).

## 1. Core idea: base layer plus mission layer

Provider-hosted environments are slow to change and often UI-only. Missions need per-run setup. Every profile therefore gets the same two-layer model.

| Layer | Contains | Changes | Owned by |
| --- | --- | --- | --- |
| **Base layer** | Toolchains and versions, system packages, long-lived services, egress allowlist, dependency repos, the **bootstrap entrypoint** | Rarely; keyed by Environment Kit digest | Mission Control through an API where one exists, otherwise an owner prerequisite ([SPEC-05](SPEC-05-owner-prerequisites.md)) |
| **Mission layer** | Per-mission installs, generated config, data fetch, health checks, readiness receipt | Every run | Mission Control. Committed on the mission branch under `.mission/setup/`, or written into the local worktree. Never contains secrets. |

The **bootstrap entrypoint** is the single generic hook that joins the two layers. It is installed once per provider environment and runs `.mission/setup/run` if it exists. It must be idempotent and bounded in time, and it writes `.mission/setup/receipt.json`.

| Profile | Where the entrypoint lives (base layer) | When it runs |
| --- | --- | --- |
| cursor_local / claude_agent_sdk / codex | Mission Control's prepare activity in the worker | Before the session starts, in the leased worktree |
| cursor_cloud | `start` in the Mission Control-owned `.cursor/environment.json` (or saved environment): `bash .mission/setup/run --phase start` | At every agent start; `install` stays the Build-time base. Q-C1 below. |
| claude_cloud | Committed `.claude/settings.json` `SessionStart` command hook guarded by `CLAUDE_CODE_REMOTE=true`, plus the UI setup script for the base | Every session start or resume, 600 s budget |
| codex_cloud | The environment's **Start skill** and install script (UI, pasted once from generated text): "run `.mission/setup/run` if present" | Task start. Q-X1 below. |

This replaces "ask the agent to install things in its first prompt", which never counts as enforcement. The mission layer runs before agent work wherever the provider orders it so. Where ordering is not provable (Codex Cloud), the receipt is missing until the entrypoint runs, and readiness stays `unproven`.

## 2. Environment Kit (new Capability Kind `environment_kit`)

An **Environment Kit** is a pinned, catalog-published bundle (`id@version#sha256`), stored through the existing bundle custody (ADR-0024).

```yaml
# mc.environment_kit.v1 — bundle manifest (illustrative)
id: envkit/python-uv-node
version: 3
toolchains: {python: "3.12", uv: "0.9", node: "22"}
system_packages: [ripgrep, jq, poppler-utils]
base:
  install: scripts/base-install.sh        # toolchains + system packages; no repo-specific work
  services: [{name: postgres, start: scripts/pg-start.sh, health: scripts/pg-health.sh}]
mission:
  steps:                                   # rendered into .mission/setup/run
    - {name: deps, run: "uv sync --frozen", when: "exists('uv.lock')"}
    - {name: node, run: "npm ci", when: "exists('package-lock.json')"}
  health: [{name: tests-import, run: "uv run python -c 'import mission_control'"}]
  timeout_s: 480
requires:
  variables: [LOG_LEVEL]
  secrets: [FIRECRAWL_API_KEY?]            # ? = optional
  egress: [pypi.org, files.pythonhosted.org, registry.npmjs.org]
  git_dependencies: []
host_support: {cursor_cloud: full, claude_cloud: base_via_owner, codex_cloud: base_via_owner, local: full}
```

Starter kits to publish:

- `envkit/python-uv`
- `envkit/node`
- `envkit/python-uv-node`
- `envkit/mission-control-dev` (this repo: uv, Postgres and Temporal CLI)
- `envkit/knowledge-research` (uv, pdf/ocr tools, Knowledge Services MCP and research API egress)
- `envkit/biotech-backend` (replaces the hand-written, stale `.cursor/environment.json` in this repo)

## 3. Manifest additions (`mission/v2` `environment`)

```yaml
environment:
  lane: cursor_cloud
  kit: {pin: "envkit/python-uv-node@3#sha256:<digest>"}
  variables:
    - {name: LOG_LEVEL, value: info}
    - {name: KS_API_URL, value_ref: "config:knowledge_services.public_url"}
  secrets:
    - {name: FIRECRAWL_API_KEY, ref: "secret:firecrawl/api_key", phases: [setup, agent]}
    - {name: MC_SIGNAL_TOKEN, ref: "mint:signal_token", phases: [agent]}   # minted per run (SPEC-04)
  network:
    mode: allowlist                  # allow_all | allowlist | none
    allow: [api.firecrawl.dev]
    include_kit: true
    include_signal_ingress: true     # adds the Mission Control ingress host (SPEC-04)
  git:
    repos:
      - {url: "https://github.com/<owner>/<repo>", ref: main, role: target}
      - {url: "https://github.com/<owner>/<dep>", role: dependency, access: read}
    write: {mode: branch_and_pr, branch: "mc/{run}/{unit}", pr: {draft: true, base: main}}
  provider_environment:
    strategy: sync                   # bind | sync | generate
    ref: "<provider-env-id-or-name>" # required for bind
```

Rules:

- **Values.** `variables[].value` is inline and non-secret. `value_ref` resolves from installation config at compile time.
- **Secret refs.** `secrets[].ref` resolves only in the Secret Broker (§4) and never into the compiled program, the bindings or a log. `mint:` refs are per-run credentials that Mission Control issues.
- **Inheritance** follows the existing manifest rules. A child may not widen `network.allow`, add secrets beyond the parent's grant, or relax `git.write`.
- **Compile without contacting providers.** The compiler resolves pins and checks that the kit's `requires` are satisfied by `variables`, `secrets` and `network`; any mismatch is a validation error. It produces a list of `secret_names`, never values.
- **Bindings.** `EnvironmentBinding` (`mc.environment_binding.v1`) is populated, not replaced: `setup_pin ← kit pin`, `secret_refs ← names+refs`, `network_policy_ref ← digest of the resolved policy`, `observed_config_digest ← provider config digest`, `readiness ← preflight result`.

## 4. Secret Broker

The Secret Broker is a port in the application layer, with adapters per source and per delivery channel.

- **Sources** (installation-configured):
  - owner keyring or `secret store` file outside any repo (local default);
  - Supabase Vault (hosted Mission Control);
  - `provider_held`: the value already lives in the provider's store and Mission Control only verifies the name exists.
- **Minting:** `mint:signal_token` produces a short-lived token (default 24 h or the mission deadline, whichever is shorter) bound to the run, unit and generation, carrying the `signal:write` scope only. Only the digest is stored ([SPEC-04](SPEC-04-watchers-and-callbacks.md)).

Delivery per lane:

| Lane | Delivery | Constraint |
| --- | --- | --- |
| cursor_local | Bridge process env built from an **allowlist**: the kit's declared secrets plus the auth route | Replaces "whatever the worker has" |
| claude_agent_sdk | `ClaudeAgentOptions.env` from the allowlist, with the child started from a **clean** env | Fixes the current leak (`bootstrap/provider_auth.py:171`): the whole worker env, DSNs included, reaches the CLI |
| codex | app-server child env allowlist plus `shell_environment_policy`; MCP `env` entries resolved per server | Fixes MCP servers starved of their secrets |
| cursor_cloud | `PUT /v1/environments/{id}/secrets/{name}` (`runtime_secret`, redacted) for kit-level secrets. Launch `envVars` (beta, per account) for per-run values such as `MC_SIGNAL_TOKEN`. If `envVars` is disabled, the run authenticates with the **VM-minted Cursor OIDC JWT** (SPEC-04) and needs no secret. | Build Secrets and user secrets are dashboard-only: owner prerequisite |
| claude_cloud | Owner prerequisite: environment env vars (`.env` format, visible to everyone using the environment) or Pro/Max network secrets per host | No per-run secret channel. Per-run identity uses `CLAUDE_CODE_REMOTE_SESSION_ID`, bound at first signal (SPEC-04 §3). |
| codex_cloud | Owner prerequisite: environment variables or network secrets (proxy-substituted for allowlisted HTTPS hosts) | No per-run channel |

Invariants:

- **Never commit a secret.** A pre-commit scan of every Mission Control commit onto a mission branch rejects a commit that contains any value the broker resolved for that run. This applies to all mission-layer files.
- **Redaction.** Frames, receipts and logs redact broker-resolved values by exact match. Existing redaction applies as well.
- **Secret use is recorded** as names only, plus the delivery channel, in the Materialization Receipt.

## 5. Network policy

Resolve one `network` policy and project it per lane. Record `enforced`, `advisory` or `unsupported` in the receipt.

| Lane | Projection | Enforcement |
| --- | --- | --- |
| cursor_cloud | `egressMode` + `egressAllowlist` in the base-layer environment | enforced (user and team policy may further restrict) |
| claude_cloud | Owner prerequisite: network level `Custom` with the generated domain list (plus defaults) | enforced by the provider. Owner must set it. |
| codex_cloud | Owner prerequisite: "Custom domains" plus additional domains | enforced by the provider. Owner must set it. |
| codex | `sandbox_workspace_write.network_access` / permission profile domains | enforced (sandbox) |
| claude_agent_sdk | Claude sandbox network settings in `.claude/settings.json` where supported, otherwise host firewall | partial; record honestly |
| cursor_local | Cursor sandbox flag | partial |

When callbacks are required, the Signal Ingress host is always added. A lane that cannot reach it degrades to provider-API observation only, and the preflight says so.

## 6. Git access

- **Repo roles.**
  - `target`: the branch is written.
  - `dependency`: read-only.
    - cursor_cloud projects it into `repositoryDependencies` (extends the generated GitHub token).
    - Local lanes add it to the clone set.
    - Claude cloud needs a multi-repo session, but **multi-repo sessions do not load repo settings or hooks**. A Claude cloud mission that needs dependencies plus callbacks is therefore refused unless dependencies come in through the mission layer (`git clone` over the GitHub proxy).
  - `knowledge`: the mission workspace repo for non-code work ([SPEC-03](SPEC-03-workspaces-and-placement.md)).
- **Local write.** Pushes use a per-run, worktree-scoped credential (`credential.helper` set in the worktree config, not global):
  - a Mission Control GitHub App installation token restricted to the target repo, preferred; or
  - the owner's `gh` credential as an owner-attested fallback.

  A worktree `pre-push` hook (Mission Control-owned, outside agent-writable paths where possible) rejects pushes to any ref except `mc/{run}/*`.
- **PR creation** is a Governed Effect (`repo_pr`) that Mission Control performs, not the agent, so approval and recording stay in Mission Control. On cloud lanes, the provider's own auto-PR may be used when `pr.mode: provider`, and the PR is then recorded as an observed artifact.
- **Commit identity.** Mission Control records the resolved head SHA of every mission branch as an immutable artifact:
  - Cursor: branch lookup through the GitHub API.
  - Claude cloud: the `Claude-Session:` commit trailer.
  - Codex Cloud: `codex cloud diff`/apply output.

## 7. Provider environment strategies

| Strategy | Meaning | Available on |
| --- | --- | --- |
| `bind` | Use an existing provider environment by ref. Mission Control verifies what it can (API read, or owner attestation plus a probe) and records `observed_config_digest`. | All cloud lanes |
| `sync` | Mission Control creates or updates the provider environment from the kit through an API. The name is `mc-<kit-id>-<digest8>`, where the digest covers the rendered configuration (the kit's base layer plus the projected egress fields) and the sorted target repositories, so one environment serves every mission using that kit and policy on that repository, and another repository gets its own (Cursor resolves an environment from the repositories it covers; a reused environment that does not cover the target repository is drift); secrets are synced by name. | **cursor_cloud only** (`/v1/environments`, `/v1/environments/{id}/secrets`) |
| `generate` | Mission Control renders the exact base-layer content (setup script, env var names, network list, entrypoint) and emits an **owner prerequisite** with a verification probe | claude_cloud, codex_cloud; and cursor_cloud items that are dashboard-only (Build Secrets, Build pin) |

**Cursor's override rule.** A repo-committed `.cursor/environment.json` on the default branch overrides any saved environment for that repo. For each cursor_cloud target repo, the preflight checks for it and reports one of three states:

- **mc-owned**: the file carries the Mission Control kit marker and matches the kit digest (its canonical configuration digest equals the kit's rendering; the marker over stale or hand-edited content is foreign).
- **foreign**: it exists without the marker. Launch is refused unless the manifest says `provider_environment.strategy: bind` to that file.
- **absent**: `sync` is used.

Mission Control may propose a PR that writes the mc-owned file (Governed Effect). It never pushes it silently.

### Qualification questions (resolved by drills, never assumed)

- **Q-C1 (Cursor):** does `start` run on the agent's `startingRef` checkout, so that `.mission/setup/run` from the mission branch is present? Does launching with a saved environment `name` still lose `startingRef`? If both answers are unfavourable, the per-mission layer for cursor_cloud moves into the first-turn harness step, and readiness stays `unproven` until the receipt arrives.
  - *Second part, answered 2026-10-14 (MO-13 drill, unfavourable):* `POST /v1/agents` with `env.name` and `repos` is `400 validation_error` ("env.name cannot be combined with repos for cloud environments"). A named launch therefore has no `startingRef`, and the `cursor_cloud` lane never names the environment. A synced environment is created for the target repository and Cursor resolves it from the repository (committed file first, then saved environments). A named launch of a synced environment ran its `start` and received its secret (drill A2).
  - *First part, UNVERIFIED:* the drill could not launch on a repository, because the account's Cursor SCM integration has no access to `Overton77/mission-control` or `ai-engineer-knowledge-services` ("does not have access to repository … to verify branch existence"). Environments with `repos` are refused for the same reason (`400 repository_access`). This is an owner prerequisite (grant the Cursor GitHub integration access to the target repositories). Until the A3 drill runs, the lane keeps `start` as the entrypoint, and readiness stays `delivered` until the receipt signal arrives.
- **Q-C2 (Cursor):** is launch `envVars` enabled on the owner's account? **Answered 2026-10-14 (MO-13 drill A2): yes.** A launch `envVars` value was present in the agent's shell.
- **Q-L1 (Claude):** is `remote.defaultEnvironmentId` from a committed mission-branch `.claude/settings.json` honoured when the routine or session starts on that branch?
- **Q-X1 (Codex):** does the current Codex Cloud Start skill run before agent work, and can it read the task's checked-out branch?

## 8. Readiness evidence and the Materialization Receipt

Readiness moves through levels. A launch policy states the minimum level it requires (default: `prepared` for local lanes, `delivered` for cloud lanes plus a `prepared` signal within N minutes, or the run is paused with a human task).

`declared` → `rendered` (files and digests) → `delivered` (written to the worktree, or committed at SHA X, or synced to provider env Y) → `prepared` (`.mission/setup/receipt.json` with step exit codes, toolchain versions and health results, received through a frame or signal) → `discovered` (the provider reports loading it; SPEC-02 §6) → `exercised` (a hook fired, a skill was invoked)

Persist `mc.environment_preparation.v1` (deferred item C15). Each record holds:

- the kit pin and the resolved policy digests;
- the delivery channel per item;
- secret names and their channels;
- the receipt digest;
- the readiness level and timestamps;
- omissions and degradations.

The Validation Report and the Launch Ticket cite it.

## 9. Lane-specific requirements

- **cursor_local:** use the manifest workspace policy (currently fixed). Run the base and mission layers in the worker. Write `.cursor/worktrees.json` only when the operator asks for Cursor-UI worktrees; Mission Control's own leases do not depend on it.
- **cursor_cloud:**
  - Compose `env_resolver` and `workspaces` in production (`deployment_composition.py:624-635`).
  - Send `env` per strategy.
  - Re-send inline `mcpServers` on every run and resume, because cloud ignores `.cursor/mcp.json`.
  - Handle `409 agent_busy` as the existing one-run-per-agent constraint.
- **claude_agent_sdk:** clean child env (§4). Run setup before `connect()`. Record the CLI version that was actually used (the discovery fixture shows 2.1.295 vs pinned 2.1.294).
- **codex:** isolated `CODEX_HOME` (exists). Project trust for the worktree path (exists). Env allowlist (§4). `.codex/environments/environment.toml` only for desktop-app interop.
- **claude_cloud / codex_cloud:** `generate` and `bind` only. Both are experimental lanes after the API lanes ([DECISIONS](DECISIONS.md) R5; issues SC-01 to SC-03).

## 10. Acceptance

- One manifest with `kit`, `variables`, `secrets`, `network` and `git` compiles for all six profiles. It yields per-lane projections plus a list of owner prerequisites for the lanes that need them, without contacting a provider.
- **Local lanes:**
  - A missing required secret fails preflight.
  - The child env contains exactly the allowlist.
  - A pre-push to a non-`mc/` ref is rejected.
  - A receipt with `prepared` is produced.
- **cursor_cloud with `sync`:**
  - A drill creates `mc-<kit>-<digest>` and syncs secret names.
  - The launched agent produces a `prepared` receipt signal.
  - A second mission with the same kit reuses the environment without an update.
- **No secret value** appears in any committed file, frame, log or binding. A test injects a sentinel secret and greps all outputs.
