---
type: Research Note
title: "Codebase audit: environment, capability and worktree materialization (2026-10-12)"
description: "Read-only audit of what Mission Control materializes per lane profile today, with path:line evidence, production composition gaps and doc/code contradictions."
tags: [mission-control, research, materialization-observation]
---

# Mission Control: environment, capability and worktree materialization audit

Repo: `platform/mission-control` (read-only audit, 2026-10-12). Paths below are relative to
`src/mission_control/` unless they start with `docs/`, `tests/`, `packages/` or `.cursor/`.
Line numbers are from the working tree as read today.

Verification run during this audit (read-only): `uv run --no-sync pytest -q -p no:cacheprovider
tests/unit/agentic_components tests/unit/workspaces tests/unit/authoring/test_manifest_v2_launch.py
tests/unit/authoring/test_manifest_cursor_launch.py tests/unit/cursor tests/unit/harness/test_cursor_cloud.py
tests/unit/claude tests/unit/codex` → **470 passed, 0 failed** (Windows host, fakes/fixtures only).
No integration (PostgreSQL/Temporal) or live provider test was run by this audit.

## Cell legend

- **WIRED+TESTED**: on the production composition path and covered by automated tests (offline fakes,
  recorded fixtures and/or disposable PG/Temporal). **No cell is live-qualified**: every profile is
  `qualified=False` and every live drill is unrun (`docs/specs/archive/mc-surfaces-2026-10/docs/qualification/release/multi-provider-2026-10.md:57-65`).
- **WIRED-UNTESTED**: on the production path but no test exercises that behaviour (or only renders a file
  whose loading was never observed).
- **PARTIAL**: some of the item exists/works; a named piece is missing or broken in production.
- **DESIGNED-ONLY**: spec/contract/renderer exists; the profile cannot launch, or nothing consumes it.
- **ABSENT**: no design or code for this item on this profile.
- **BLOCKED-BY-PROVIDER**: the vendor surface does not exist or is UI-only per the feasibility studies.
- **N/A**: not meaningful for this placement (e.g. a provider environment file on a local worker).

Hosted Claude/Codex note: `claude_cloud` and `codex_cloud` have **no harness/adapter at all**; they are
describe-only v2 stubs (`application/execution/harness/describe.py:643`, `V2_STUB_LANE_PROFILES`) and
launch is refused at `application/authoring/manifest_launch_inputs.py:797-802`. The projection renderer
does render files for them (golden fixtures `tests/fixtures/projections/{claude_cloud,codex_cloud}/`), so
several of their cells are DESIGNED-ONLY rather than ABSENT.

## 1. Capability matrix

| Item | cursor_local | cursor_cloud | claude_agent_sdk (local) | claude_cloud | codex (local) | codex_cloud |
| --- | --- | --- | --- | --- | --- | --- |
| **Skills (SKILL.md bundles)** | PARTIAL: rendered to `.cursor/skills/` (`application/agentic_components/projections.py:74-81,129`); bound via `CursorProjections.skills`. Production rows resolver has **no bundle custody** → any skill raises `CapabilityNotFound("custody is not configured")` (`application/capabilities/catalog.py:288-294`; `adapters/temporal/deployment_composition.py:668-677`) | PARTIAL: same renderer; committed to run branch; same custody gap (`deployment_composition.py:624-635`) | PARTIAL: `.claude/skills/`; recorded local discovery fixture shows load (`tests/fixtures/projections/discovery/claude_agent_sdk.recorded.json`); production rows resolver lacks custody (`adapters/temporal/provider_lane_composition.py:103-104`; launch author `bootstrap/manifests.py:213-217`) | DESIGNED-ONLY (renders `.claude/skills/`; launch refused) | PARTIAL: `.agents/skills/`; no custody (`provider_lane_composition.py:163-164`); no discovery recording (no Codex binary, `application/environments/bootstrap.py:115-125`) | DESIGNED-ONLY / BLOCKED-BY-PROVIDER: renders AGENTS.md + `.agents/skills` (`projections.py:129-132,911-944`); launch refused; hosted task reads repo skills only |
| **Provider subagent files** | WIRED+TESTED: `.cursor/agents/<name>.md` + inline `agents` send option (`projections.py:835-858`) | WIRED+TESTED: files on branch + `customSubagents` (≤20) on create (`adapters/cursor/cloud.py:469-474,493-495`) | WIRED+TESTED: `.claude/agents/<name>.md` (`projections.py:905-908`); discovery fixture lists projected agent | DESIGNED-ONLY | WIRED-UNTESTED (load): `.codex/agents/<name>.toml` + project trust (`projections.py:976-978`; trust in `adapters/codex/harness.py:624-633`); codex README: "written, not loaded by a CLI" (`docs/qualification/lanes/codex/README.md:156`) | BLOCKED-BY-PROVIDER: skipped (`projections.py:943-944`) |
| **Hooks + hook config** | PARTIAL: Kernel Hooks WIRED+TESTED (`.cursor/hooks.json` fail-closed, `.mission/hooks/kernel.py` written at `adapters/cursor/local.py:386`, loopback callback service `deployment_composition.py:653-661`, `tests/integration/cursor/test_kernel_hook_roundtrip.py`). **Catalog hook scripts refused at launch** (no slot in `mc.cursor_binding.v1`; `application/authoring/cursor_launch.py:22-25`, `manifest_launch_inputs.py:166`) | ABSENT: Kernel Hooks disabled (`kernel_hooks=()`, `deployment_composition.py:633`; VM cannot reach loopback); catalog hooks refused as above | PARTIAL: Kernel Hooks in-process SDK callbacks, fail closed, WIRED+TESTED (`adapters/claude/hooks.py`, `projections.py:880-887`, `tests/unit/claude/test_claude_controls.py`); catalog hooks → `.claude/settings.json` + `.mission/hooks/run.py`, but hook bundles need custody (broken in production, as Skills) | DESIGNED-ONLY: settings hooks rendered; kernel hooks reported degraded (`projections.py:896-903`) | **PARTIAL/BROKEN**: `.codex/hooks.json` references `python .mission/hooks/kernel.py …` (`projections.py:514-515,970-975`; golden `tests/fixtures/projections/codex/`), but the Codex lane never writes `kernel.py` or a callback token and no callback service is composed (only `adapters/cursor/local.py:386` writes it; `grep -i kernel adapters/codex/harness.py` = 0 hits). Catalog hooks need custody | BLOCKED-BY-PROVIDER: "no command hooks under cloud orchestration" (`projections.py:940-942`) |
| **Rules / instructions** | WIRED+TESTED: `AGENTS.md`, `.cursor/rules/mc-mission.mdc`, `.mission/operating-contract.md` (`projections.py:803-809`; `adapters/cursor/projection.py:50,254-289`). **Overwrites** the repo's own `AGENTS.md` (unlink+write, `adapters/cursor/projection.py:228`) | WIRED+TESTED via integration commit on `mc/<run>` (repo AGENTS.md replaced on that branch) | PARTIAL: `CLAUDE.md`; `materialize_projection` **refuses** if the repo already has a different `CLAUDE.md`/`.mcp.json`/`.claude/settings.json` (`application/agentic_components/materialization.py:202-209`) | DESIGNED-ONLY | PARTIAL: `AGENTS.md` (32 KiB cap, `projections.py:957-964`); collision refusal if repo has its own `AGENTS.md` (same line) | DESIGNED-ONLY (AGENTS.md renderer; launch refused) |
| **MCP config** | WIRED+TESTED: `.cursor/mcp.json`, secrets as `${env:NAME}` (`projections.py:648-681,810-822`); values come from the worker's ambient env | PARTIAL: `mcp.json` committed to branch; `${env:NAME}` must exist in the Cursor VM (owner-configured; `envVars` path not composed, see Secrets); `localhost` stdio launchers are VM-local | WIRED+TESTED (render + recorded discovery shows `discovery-stub connected`): `.mcp.json` with `${NAME}` (`projections.py:871-884`) | DESIGNED-ONLY | PARTIAL: `.codex/config.toml` with `env_vars` forwarding (`projections.py:698-726`), but child env is an allow-list without those names (`adapters/codex/launcher.py:47-77,149-167`) → secret-bearing MCP servers get no credentials | BLOCKED-BY-PROVIDER: reported "configure the server on the Codex Cloud environment" (`projections.py:932-935`) |
| **Env vars (non-secret)** | ABSENT (no manifest field; agent inherits worker env via in-process SDK) | PARTIAL: `CursorCloudOptions.env_vars_ref` → `envVars` (`domain/execution/lanes.py:681-699`, `adapters/cursor/cloud.py:500-505`), unit-tested, but **no `env_resolver` is composed** (`deployment_composition.py:624-635`) → `UNSUPPORTED_BEHAVIOR` if bound | ABSENT (no field; child inherits the whole worker env minus shadowing credentials, `bootstrap/provider_auth.py:171-188`, `provider_lane_composition.py:121`) | BLOCKED-BY-PROVIDER (env vars edited in web UI only; `application/environments/bootstrap.py:142-149`) | ABSENT (allow-list only, `adapters/codex/launcher.py:47-77`) | BLOCKED-BY-PROVIDER (UI-only environment variables) |
| **Secrets** | PARTIAL: capability `secret_refs` (names only, `domain/capabilities/host_support.py`) rendered as references; resolved only from ambient worker env; `EnvironmentBinding.secret_refs` not consumed by any coding lane (grep: only `application/environments/resolver.py:340`, Deep Agents uses its own) | PARTIAL/unwired (see Env vars); owner must set secrets in Cursor dashboard; nothing checks | PARTIAL: ambient; over-broad (whole worker env reaches the CLI, `adapters/claude/transport.py:1-20,83-100`) | BLOCKED-BY-PROVIDER | ABSENT for MCP secrets (stripped by allow-list); provider auth credential only (`launcher.py:141-167`) | BLOCKED-BY-PROVIDER |
| **Provider auth route** (context) | Worker setting `CURSOR_API_KEY` (key in agent options, not env: `adapters/cursor/bridge.py:10-12`) | same key; `CloudAgentsClient` (`adapters/cursor/cloud_api.py:121-136`) | WIRED+TESTED: MP-05 auth admission + profiles file (`MISSION_CONTROL_AUTH_PROFILES_PATH`); no route account-enabled | ABSENT | WIRED+TESTED: MP-05 admission; `CODEX_HOME` isolated/owner modes (`adapters/codex/harness.py:624-633`) | ABSENT |
| **Packages / runtimes setup** | ABSENT (worker must be pre-provisioned; no setup step) | ABSENT: MC never generates/selects a Cursor environment or install script; relies on whatever the repo already has | PARTIAL: only a presence check of required executables (hook interpreters, stdio MCP launchers) before start (`materialization.py:103-140,169-199`; `adapters/claude/harness.py:498-505`) | BLOCKED-BY-PROVIDER (setup script UI-only) | PARTIAL: same executable check (`adapters/codex/harness.py:588-600`) | BLOCKED-BY-PROVIDER (install script/start skill UI-only) |
| **Provider environment file** (`.cursor/environment.json`, Claude cloud env/setup, Codex cloud env) | N/A | **ABSENT**: no code writes `.cursor/environment.json` (grep `environment.json` in `src/` = 0); create body sends only `env.type` (`cloud.py:490-491`); `CursorCloudEnvironment.environment_ref` is a deployment key that is never sent to Cursor; `setup.pin` only compared to the deployment value (`manifest_launch_inputs.py:1256-1260`) | N/A | BLOCKED-BY-PROVIDER: no env list/get/revision; `--environment` rejects `env_` IDs (`docs/specs/archive/mc-surfaces-2026-10/docs/qualification/lanes/claude_cloud/FEASIBILITY.md:84,162-170`) | N/A | BLOCKED-BY-PROVIDER / DESIGNED-ONLY: `CodexCloudOptions` binding shape (`domain/execution/bindings.py:208-214`), `codex cloud exec --env` exists but no adapter; no revision/setup digest (`codex_cloud/FEASIBILITY.md:88-89`) |
| **Git read access** | WIRED+TESTED: dedicated bare clone under lease root (`adapters/workspaces/git_workspaces.py:499-536`); worker's ambient git credentials; prompts disabled | PARTIAL: worker mirror clone (`adapters/cursor/scm.py:82-89`) + Cursor's own GitHub integration clones in the VM (owner prerequisite, unchecked) | WIRED+TESTED (allocator clone, `provider_lane_composition.py:105-115`) | BLOCKED-BY-PROVIDER (GitHub proxy/app; no API) | WIRED+TESTED (via `GitWorktreeLeaser` → allocator clone) | BLOCKED-BY-PROVIDER |
| **Git push / PR access** | ABSENT: detached worktree; changes leave as patch/snapshot artifacts only (`adapters/cursor/workspace.py:1-15`) | PARTIAL: worker pushes `mc/<run>` with ambient git creds (`scm.py:142,246`); agent pushes via Cursor GitHub integration; `autoCreatePR` option (`cloud.py:487`); no push-rights preflight | ABSENT: branch `mc/ws/<digest>` local only; no push/PR effect (no `push` outside `scm.py`) | DESIGNED-ONLY: `ClaudeCloudOptions.create_pr` (`bindings.py:198-205`), nothing consumes it | ABSENT (detached worktree) | DESIGNED-ONLY/BLOCKED (`CodexCloudOptions.branch`; no apply/push adapter) |
| **Worktree / branch isolation** | WIRED+TESTED but **fixed policy**: `CURSOR_LOCAL_POLICY` (reuse `none`, detached) regardless of manifest (`adapters/cursor/workspace.py:44-50,159-187`); manifest `workspace.policy` not used by Cursor binding | PARTIAL: per-run branch `mc/<run>` shared by all units of a run (`cloud.py:160,178-179`); provider-workspace lease via `allocate_provider_workspace` is **not composed in production** (no `workspaces=` at `deployment_composition.py:624-635`; tests pass it, `tests/unit/cursor/support.py:107-114`) | WIRED+TESTED: `WorkspaceAllocator` honouring `binding.workspace_policy` (`adapters/claude/harness.py:475`; `application/workspaces/policy.py`), symlink/nesting checks, dirty-input reject/snapshot | BLOCKED-BY-PROVIDER (refused, `application/workspaces/policy.py:37-39,72-77`) | PARTIAL: uses `GitWorktreeLeaser` with default `CURSOR_LOCAL_POLICY`; **ignores `binding.workspace_policy`** (`adapters/codex/harness.py:571-580`; handoff C14) | BLOCKED-BY-PROVIDER (refused) |
| **Network policy** | PARTIAL: deployment-level `sandbox_enabled` (Cursor sandbox) (`adapters/cursor/bridge.py:292`); manifest `sandbox.egress` only hashed | ABSENT (VM network set in Cursor dashboard; nothing sent) | ABSENT: `sandbox.egress` only folded into `policy_digest` (`manifest_launch_inputs.py:892-894`) | BLOCKED-BY-PROVIDER (UI allowlist) | PARTIAL: `sandbox_mode` from deployment options (`bindings.py:187-195`); egress unenforced | BLOCKED-BY-PROVIDER |
| **Owner preflight / manual steps** | PARTIAL: installation readiness gate (OS, auth route, bindings placeholders `OWNER-SELECT:`, pins, DB release) `bootstrap/preflight.py:1-25,324-331`; tested `tests/unit/runtime/test_mp22_local_readiness.py`; no per-mission checklist | PARTIAL: only API key + host check; no GitHub-integration, push-rights, env/secret or environment checks | PARTIAL: OS gate + auth preflight (`adapters/provider_auth/preflight.py`) | ABSENT (launch refused; UI steps only in feasibility doc) | PARTIAL: OS gate + auth + CLI version pin (`adapters/codex/launcher.py`) | ABSENT (refused) |
| **Environment inheritance / reuse** | WIRED+TESTED at manifest level: node overlays deep-merge, lists replace, widening refused (`domain/authoring/manifest.py:1655`, `manifest_v2.py:453`; `tests/unit/authoring/test_manifest_schema.py`, `test_manifest_v2.py`). Runtime reuse: none (fixed policy) | manifest: as left; runtime: run branch reused across units | manifest: as left; runtime: `within_run`/`within_session` slots honoured | DESIGNED-ONLY | manifest: as left; runtime: none (fixed policy) | DESIGNED-ONLY. `templates:`/`extends:` deferred for all (ADR-0034) |
| **Knowledge-work inputs** (corpora, documents, data) | PARTIAL: Context Packet files `.mission/context.md`, `.mission/inputs.json`, `inputs/` read-only (`adapters/cursor/projection.py:254-307`; ADR-0027). Launch **requires `workspace.repo`** (`manifest_launch_inputs.py:1101-1104`); string context profiles refused (`:1282-1288`); no corpus/volume mount concept | PARTIAL: packet files **committed into the git run branch** (`cloud.py:370-396`) — size and sensitive-data exposure risk | PARTIAL: same packet; repo required (`manifest_launch_inputs.py:851-855`) | BLOCKED-BY-PROVIDER | PARTIAL: same; `mount_root` is only a path-prefix remap (`adapters/codex/harness.py:284,444-449`) | BLOCKED-BY-PROVIDER |
| **Output / artifact collection** | WIRED+TESTED (fixture): `outputs/` → digest-checked `workspace-candidate://` refs (`WorkspaceCandidateLaneOutputs`, `deployment_composition.py:953-957`), final JSON = Completion Candidate, patch capture excluding MC files | WIRED+TESTED (fixture): branch diff as patch, artifacts via presigned download, `branch:<b>@<sha>` snapshot (`cloud.py:33-40,1162-1190`) | WIRED+TESTED (fixture): snapshot on release excluding state root (`adapters/claude/workspace.py:81-104`) + outputs | BLOCKED-BY-PROVIDER | WIRED+TESTED (fixture) | BLOCKED-BY-PROVIDER |

## 2. Data model today (environments, capabilities, hooks, agents, worktrees)

Authoring (YAML manifest):
- `domain/authoring/manifest.py` (`mission/v1`): `Environment` (`:562-577`) = `lane`, `model{profile,settings}`,
  `sandbox{profile, egress[]}`, `workspace{repo{url|path, ref}, context[], skills[]}`, `capabilities[]`
  (pin or search), `agents[]` (`AgentEntry` + `overlay`), `hooks[]` (`HookEntry`: `events`, `matcher`,
  `fail_closed`, `:482-485`), `plugins[]`, `budget`, `governors`, `side_effects`. `ContextEntry`
  (`:488-515`) = `pin|search|artifact|path` + `expand: inline|reference|materialize|auto`.
  `resolve_environments` (`:1655`) computes effective per-node environments.
- `domain/authoring/manifest_v2.py` (`mission/v2`): `EnvironmentV2` (`:214-222`) adds `auth{profile}`,
  `execution_environment{kind: local_workspace|provider_hosted, profile, provider, environment_ref,
  expected_revision, setup{pin}}` (`:105-127`), `workspace.policy{mode managed_worktree|provider_workspace|
  shared_checkout, reuse, dirty_input, cleanup}` (`:149-160`), `continuation{…}`, `requires{controls,
  approvals, observation, all_writes_gated}`.
- **Not in the manifest at all**: environment variables, secret values or secret bindings for the
  agent process, setup/install scripts, packages/runtimes, network allowlist beyond `sandbox.egress` slugs,
  data/corpus mounts, git push/PR policy.

Bindings (sealed at launch):
- `domain/execution/bindings.py`: `EnvironmentBinding` `mc.environment_binding.v1` (`:87-111`: kind, host_profile,
  provider, environment_ref, expected_revision, observed_config_digest, verified_by/at, setup_pin,
  network_policy_ref, secret_refs, storage_policy_ref, timeout_ceiling_s, readiness, readiness_evidence_ref);
  `WorkspacePolicyPin` (`:148-152`); `ProviderExecutionBinding` `mc.execution_binding.v2` (`:226-254`: model,
  auth, environment, workspace_policy, repo_url/ref/commit, materialization_digest, requirements,
  policy_digest, pins incl. `capability.<role>.<id>`, typed `provider_options`
  ClaudeSdkOptions|CodexAppServerOptions|ClaudeCloudOptions|CodexCloudOptions, budgets, task_queue);
  `WorkspaceSnapshot` `mc.workspace_snapshot.v1` (`:306-331`).
- `domain/execution/lanes.py`: `CursorExecutionBinding` `mc.cursor_binding.v1` (`:708-730`) with
  `CursorWorkspace{repo_url, base_ref, lease_root, branch_prefix}`, `CursorProjections{rules_digest,
  agents_digest, skills[], mcp_servers[], hooks_digest}` (no hook-script or plugin pins),
  `CursorCloudOptions{auto_create_pr, env_vars_ref, metadata, environment: cloud|pool|machine,
  client_agent_id}` (`:681-699`).
- Deployment file `mc.manifest_launch_bindings.v2` `providers` section: `ProviderLaneBinding`
  (`application/authoring/provider_launch.py:95-127`: task_queue, model/auth/host profiles, pins,
  provider_options, budgets, `WorkspaceProvision`) and `CursorLocalLane`/`CursorCloudLane`
  (`application/authoring/cursor_launch.py:113-200`: repositories, hook_callback, sandbox flag,
  `environments{ref → CursorCloudEnvironment}`, `v1_environment`). The `EnvironmentBinding` sealed into a
  claude/codex binding is copied verbatim from `host_profiles[...]` (`manifest_launch_inputs.py:838-843,913`);
  `repo_commit` is never set for local profiles.
- `application/environments/` (MP-03): `EnvironmentRequest`, `PreparationAttestation`,
  `resolve_environment`, `BootstrapRoute` evidence table (`bootstrap.py:75-181`). **Only tests import it**
  (`tests/unit/agentic_components/test_environments.py`, `test_adapter_discovery.py`).

Capabilities (catalog):
- Kinds `skill_bundle | mcp_server | mcp_tool | hook_script | subagent_profile | plugin | middleware`
  (migration `0025`), `host_support` matrix and `secret_refs` (names) per row
  (`domain/capabilities/host_support.py`); pins `id@version#sha256:…` (`domain/capabilities/pins.py`);
  bundle manifest `mc.capability_bundle_manifest.v1` (`domain/capabilities/bundles.py`); custody service
  `application/capabilities/bundle_custody.py` (local FS or Supabase bucket) — **not composed** in the API
  or in any lane rows resolver.
- Hooks: one `HookEvent` vocabulary + per-profile `HOOK_EVENT_MAPPING` (`domain/capabilities/hooks.py`);
  `mc.hook_input.v1`/`mc.hook_result.v1` (`contracts/hooks.py`); Kernel Hooks `mc.stop_fence`,
  `mc.operation_intent`, `mc.frame_capture`, `mc.usage` (`domain/agentic_components/projection.py:99-102`).
- Subagents: `mc.subagent_profile.v1` (`domain/capabilities/subagents.py`); plugins
  `mc.plugin_manifest.v1` (`domain/capabilities/plugins.py`).

Worktrees:
- `application/workspaces/policy.py` (admission, slots, branch `mc/ws/<digest>`, containment checks),
  `service.py` `WorkspaceAllocator` (`:106`; `allocate`, `allocate_provider_workspace` `:266`, `join_shared`,
  `snapshot`, `restore`, `release`, `cleanup` `:494`), `snapshots.py`; backend
  `adapters/workspaces/git_workspaces.py` (bare dedicated clone, unique branch, non-mutating capture,
  verified restore). Lease ledger table `workspace_lease` (migration `0003`), artifact custody (`0024`).
  No environment-binding or preparation-attestation table (`mc.environment_preparation.v1` deferred, C15).

## 3. Projection to native layouts (who writes what, where)

Single pure renderer `application/agentic_components/projections.py::render_host_files` (`:91-142`)
turns resolved capability rows + lane profile + instruction + Kernel Hooks into a `HostProjection`
(files + report `degraded/unsupported_on_lane/requires_trust/overflow/skipped`). Placement per lane:

| Profile | Files rendered | Written by | When / how |
| --- | --- | --- | --- |
| cursor_local | `AGENTS.md`, `.cursor/rules/mc-mission.mdc`, `.cursor/skills/<n>/…`, `.cursor/agents/<n>.md`, `.cursor/mcp.json`, `.cursor/hooks.json`, `.mission/hooks/run.py` + hook dirs; plus `.mission/hooks/kernel.py`, `.mission/hooks/context.json`, `.mission/bin/.token`, packet files, `.mission/operating-contract.md`, `outputs/` | `RenderedProjectionSource` (`adapters/cursor/projection.py:119-139`) → `write_files` (unlink + write, `:218-240`) from `adapters/cursor/local.py:386-388` | At `prepare` into the leased detached worktree; digests (rules/agents/hooks) must equal the binding or `CAPABILITY_DRIFT` (`projection.py:183-208`) |
| cursor_cloud | Same Cursor files minus Kernel Hooks (`kernel_hooks=()`), plus packet files | `GitBranchPublisher.publish` (`adapters/cursor/scm.py:91-145`) | At `prepare`, committed and pushed to `mc/<run>` from base ref with the worker's git credentials; later units commit on top (`commit_files`, `:215-250`); agent created with `startingRef` + `workOnCurrentBranch` (`cloud.py:476-505`) |
| claude_agent_sdk | `CLAUDE.md`, `.mcp.json`, `.claude/skills/…`, `.claude/agents/<n>.md`, `.claude/settings.json` (catalog hooks only), `.mission/hooks/run.py`; Kernel Hooks as in-process callbacks + `setting_sources=["project"]` in `send_options` | `materialize_projection` (`application/agentic_components/materialization.py:169-232`) from `adapters/claude/harness.py:482-505` | At `prepare` into the allocator worktree; fail-closed on digest drift, traversal, symlink, **collision with different existing bytes**, missing executables; `ClaudeAgentOptions(cwd, setting_sources, agents, hooks, can_use_tool, …)` (`harness.py:552-604`) |
| codex | `AGENTS.md` (≤32 KiB), `.agents/skills/…`, `.codex/config.toml` (MCP), `.codex/hooks.json` (Kernel + catalog), `.codex/agents/<n>.toml`; isolated `CODEX_HOME/config.toml` with project trust | `materialize_projection` from `adapters/codex/harness.py:583-608`; trust in `_prepare_codex_home` (`:624-633`) | At `prepare` into a `GitWorktreeLeaser` detached worktree; `.mission/hooks/kernel.py` referenced by hooks.json is **not written** |
| claude_cloud | `CLAUDE.md`, `.mcp.json`, `.claude/settings.json`, skills, agents (golden fixture only) | nothing (no adapter) | Launch refused |
| codex_cloud | `AGENTS.md`, `.agents/skills/…`; MCP/hooks/agents reported degraded/skipped | nothing (no adapter) | Launch refused |

Not projected anywhere: `.cursor/environment.json` / Dockerfile / install/start scripts, Claude Code
cloud environment or setup script, Codex Cloud environment/install script/start skill, environment
variables, secret values, `.claude/settings.json` `env`/`permissions`, Codex `sandbox_workspace_write.network_access`.
The repo's own `.cursor/environment.json` (`name: "Biotech backend (Docker Compose)"`,
`repositoryDependencies: ["https://github.com/Overton77/biotech-meta"]`, install/start scripts that clone
biotech-meta and `docker compose up`) is hand-written developer setup for working *on* this repo, appears
stale relative to the workspace reorganization, and is not an MC-produced or MC-consumed artifact.
`skills-lock.json` locks 53 third-party developer skills (mattpocock, langchain-ai, …) installed for the
repo's own agents; the MC runtime bundles are `skills/mission-control*/` with `manifest.json`
(`mc.skill_bundle.v1`).

## 4. Gaps, contradictions, stubs

Production composition gaps (code-verified):
1. **No bundle custody anywhere in production.** `CatalogProjectionRows(...)` (`bootstrap/manifests.py:213-217`,
   `adapters/temporal/provider_lane_composition.py:103-104,163-164`) and `CatalogRows(...)`
   (`deployment_composition.py:628-632,672-677`) are built without `custody`, and
   `_bundle_files` raises when custody is `None` (`application/capabilities/catalog.py:288-294`). Every
   skill bundle and hook script fails to resolve on every lane; documented as parity gap 15 / C5 and in
   `docs/knowledge/capabilities.md` ("CatalogService.custody defaults to None").
2. **Environment resolver/attestation is dead code**: `resolve_environment`/`attest_local_preparation`
   are imported only by tests. No production code produces a `PreparationAttestation`, discovers loaded
   controls, or sets `readiness=ready`; bindings copy deployment-declared `EnvironmentBinding`s.
3. **cursor_cloud composed without `env_resolver` and without `workspaces`** (`deployment_composition.py:624-635`):
   bound `env_vars_ref` → `UNSUPPORTED_BEHAVIOR` (`cloud.py:500-504`); no provider-workspace lease is recorded,
   contradicting `docs/knowledge/cursor-lane.md:88-90` and `docs/qualification/lanes/cursor_cloud/README.md:31`
   (true only in tests, `tests/unit/cursor/support.py:113`).
4. **Codex Kernel Hooks cannot run**: hooks.json points at `.mission/hooks/kernel.py` which only the Cursor
   local lane writes (`adapters/cursor/local.py:386`); Codex composition has no hook callback service or token.
   Contradicts the release statement's "`codex` … Hooks fail closed: yes (command hooks)"
   (`docs/specs/archive/mc-surfaces-2026-10/docs/qualification/release/multi-provider-2026-10.md:86`). Uncertainty: whether codex-cli 0.162.0 loads
   project `.codex/hooks.json` at all under the written trust is unobserved ("written, not loaded by a CLI").
5. **Instruction-file collision**: Claude/Codex `materialize_projection` refuses any repo that already has a
   different `AGENTS.md`/`CLAUDE.md`/`.mcp.json`/`.claude/settings.json`/`.codex/*`; Cursor overwrites them.
   There is no merge of repo-owned rules with the mission instruction. Not covered by a test against a real
   repo (fixtures use a clean fixture repo). This repo itself has `AGENTS.md` and `.claude/skills/`.
6. **Workspace policy honoured only by Claude**: Codex uses `GitWorktreeLeaser` with `CURSOR_LOCAL_POLICY`
   default (`adapters/codex/harness.py:571-580`; `provider_lane_composition.py:168`); Cursor local is fixed
   reuse `none`. `WorkspaceAllocator.cleanup`, `join_shared`, `allocate_shared_parent` have **no production
   callers** (grep) → retained worktrees are never cleaned; `shared_checkout` is unreachable.
7. **No env/secret injection model** for coding lanes: `EnvironmentBinding.secret_refs`, `network_policy_ref`,
   `setup_pin`, `storage_policy_ref`, `timeout_ceiling_s` are consumed by no coding adapter. Claude child env =
   whole worker env minus admission `env_unset` (`bootstrap/provider_auth.py:171-188` with `environ=os.environ`),
   i.e. DB DSNs, `CURSOR_API_KEY` etc. reach the Claude CLI and its tools if present on the worker; Codex is
   the opposite (strict allow-list), so its MCP `env_vars` are empty. HANDOFF-2026-10-10.md:102 calls both
   "credential-free child environment" — accurate for Codex only.
8. **Launch requires a repository** for all four provider lanes (`manifest_launch_inputs.py:851-855,1101-1104`);
   the cursor "research lease" (empty initialized repo, `adapters/cursor/workspace.py:188-230`) is unreachable
   from the manifest path. String context profiles are refused for provider lanes. No corpus/data mounts.
9. **Cursor binding cannot carry hook scripts or plugins** (`cursor_launch.py:22-25`; `_CURSOR_MANIFEST_KINDS`
   `manifest_launch_inputs.py:166`) → refused at pointer (parity gap 15; Missions 2/3 cannot launch as authored).
10. **No push/PR path for local lanes**; `repo_commit` never pinned for local bindings (only validated for hosted,
    `bindings.py:270-273`); cloud push relies on worker ambient credentials; no push-rights/GitHub-app preflight.
11. **Provider environments are not selected**: Cursor create sends `env.type` only; the deployment's
    `environment_ref` is never transmitted; `setup.pin` is a compared label; no `.cursor/environment.json`.
12. **Egress/network unenforced**: `sandbox.egress` only enters `policy_digest` (`manifest_launch_inputs.py:892-894`).
13. **Hosted Claude/Codex**: no adapter, no harness; feasibility Outcome 3 (13/14 vendor operations missing).
    `ClaudeCloudOptions`/`CodexCloudOptions` exist only as binding shapes.

Doc-vs-code contradictions / stale statements:
- `docs/knowledge/capabilities.md` "Claude and Codex layouts … render too … though no lane runs them" — stale;
  both local lanes now materialize them.
- `docs/knowledge/lanes-and-harness.md:115` says the environment resolver refuses hosted profiles — the resolver
  is not on the launch path; the refusal is in `manifest_launch_inputs.py:797` and `workspaces/policy.py`.
- `application/environments/bootstrap.py:109-113` route note says "the Python SDK is not pinned" — it is
  (`claude-agent-sdk==0.2.165`, bundled CLI 2.1.294); the discovery fixture was recorded with CLI **2.1.295**.
- ADR-0024 (workers download bundles through signed URLs) and ADR-0023 ("existing renderer becomes the host
  projection for every kind") are implemented in code but not composed (custody gap).
- ADR-0037 / SPEC-02 `managed_worktree` semantics (reuse, cleanup after artifact registration) are implemented
  in the allocator but only the Claude lane uses them and cleanup is never invoked.
- SPEC-02 "Environment profiles": persist resolved binding with setup digests, toolchain pins, egress, credential
  references — fields exist; nothing populates or enforces them.
- Release statement: `cursor_cloud` "allocator-backed lease" implemented — only in test composition.
- ADR-0035–0041 remain `proposed` (O9).

Stubs / TODO-like: `V2_STUB_LANE_PROFILES={claude_cloud, codex_cloud}` (`describe.py:643`); C14 lane-neutral
projection helpers still in `adapters/cursor/projection.py` (imported by Claude and Codex); C15
`mc.environment_preparation.v1` not persisted; `templates:`/`extends:` deferred (ADR-0034).

## 5. Owner-run / unrun items relevant to environments

From `HANDOFF-2026-10-10.md` §Remaining work and the release statement §Blocked requirements:
- **O1** Live drills, one per profile, with Linear-approved finite budgets: `make lane-qualify PROFILE=<cursor_local|cursor_cloud|claude_agent_sdk|codex> LIVE=1`
  (cursor_cloud also needs `MC_CURSOR_CLOUD_REPO`, a throwaway repo the worker's git can push to). Unrun.
- **O2** Linux or WSL 2 worker (`codex-cli 0.162.0` on PATH) — `cursor_local`, `claude_agent_sdk`, `codex` refuse Windows (`LANE_UNSUPPORTED_OS`). Unprovided.
- **O3** `MISSION_CONTROL_AUTH_PROFILES_PATH` document (+ Claude `owner_cli_login` attestation), lane opt-ins
  `MISSION_CONTROL_CLAUDE_LANE`/`_CODEX_LANE`, `MISSION_CONTROL_LANE_TASK_QUEUES`. Unauthored; no route account-enabled.
- **O4** Remove stray nested `agent-browser/` in `Biotech/.agents/skills/agent-browser` (worker `PIN_DRIFT`).
- **O5** CRLF vs LF decision for `skills-lock.json` and seeds (bundle digest portability).
- **O6** DB release 1.2.0 live install (`pg_trgm` in `extensions`, `mission-db inspect/lock/plan/apply/verify`, seed phases incl. the `capability-bundles` bucket seed which reports `blocked` on plain PostgreSQL).
- **O7** Production `mc.manifest_launch_bindings` v2 file with `providers` (Claude, Codex, Cursor: host profiles = the `EnvironmentBinding`s, repositories, Cursor cloud environments) and resolve `OWNER-SELECT:` pointers / Temporal Cloud cluster.
- **O9** Accept/amend ADR-0035…0041 (incl. 0037 workspaces).
- **O10** Hosted: nothing runnable; MP-18/19/21 blocked on vendor operations. Optional feasibility probes
  (owner-approved) need: Claude — throwaway repo with the Claude GitHub App installed, `allow_remote_sessions`
  on, non-ZDR org, `.claude/settings.json` HTTP hooks to a public receiver (`claude_cloud/FEASIBILITY.md:243-248`);
  Codex — ChatGPT plan with Codex Cloud, throwaway repo connected to ChatGPT, one published environment
  (trivial install script, internet off, no secrets) (`codex_cloud/FEASIBILITY.md:163-171`).
- Code follow-ups touching environments (no owner decision): **C5** (custody + hook/plugin slot in
  `mc.cursor_binding.v1`), **C14** (projection helper layering; Codex workspace policy pin), **C15**
  (`mc.environment_preparation.v1`), C16 (structured-output projection), C18 (unexplained
  "workspace identity was reused with different materialization" Cursor Goal Loop failure).
- VALIDATION scenarios still unrun live: V01 (compile refusal per profile, offline-tested), **V03** (two agents,
  same writable workspace; DB-tested only), **V20** (hosted lifecycle incl. environment proof — blocked), G4
  (per-profile live drill with exact environment), MP-03 acceptance "actual adapter discovery fixtures prove
  skills, MCP and subagents load" — met only for Claude local via one recorded CLI fixture; none for Codex or Cursor.
