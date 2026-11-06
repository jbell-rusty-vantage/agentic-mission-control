---
type: Reference
title: "Run 2 finish: interface map for the materialize-and-run cells (2026-10-19)"
description: "Verified entry points, configuration knobs, evidence labels and gotchas for the agent executing the Run 2 finish instructions (W1-W6): mission authoring, owner prerequisites and probes per lane, serving composition (local and Temporal Cloud), the claude_agent_sdk, codex and cursor_local lanes, observation and control, custody, the CLI delegation skills, and the known defects with workarounds."
---

# Run 2 finish: interface map

Audience: the session executing [the finish instructions](RUN-2-FINISH-INSTRUCTIONS-2026-10-19.md)
(W1-W6). Source of truth: `main` at `2c3d9aad` in the `run2-final-main` checkout. Every
`path:line` below was read for this map. Repository paths are relative to the repository root;
private operator tooling is cited as `task/run2-close-20261018/...` (under
`C:/Users/Pinda/Documents/Codex/2026-10-16/`) and is never reproduced. Nothing was run.

Labels (as in the provider-consolidation
[baseline](../provider-consolidation-2026-10/docs/BASELINE-2026-10-19.md), which this map cites instead
of repeating): **L** evidenced live by a Run 2 receipt; **T** implemented with unit tests;
**U** implemented or declared, never proven live. "Inference" marks a conclusion drawn from code
that no receipt confirms.

## 0. Ten things that change the plan

1. **No `cursor_local` lane exists in the G1 configuration.** `g1/config/launch-bindings.json` has
   `providers.claude_agent_sdk` and `providers.codex` only, and `g1/config/auth-profiles.json` has
   `claude-sdk-api` and `codex-api-configured` only. W3 must add a `providers.cursor_local` binding
   (section 4.3), a Cursor auth profile, `CURSOR_API_KEY` on both API and worker, and the Cursor
   lane queue. Without `CURSOR_API_KEY` neither process registers the lane
   (`src/mission_control/adapters/temporal/deployment_composition.py:560-561`,
   `src/mission_control/bootstrap/api.py:673-680`).
2. **Codex M4 will fail as served (inference).** `broker_names` resolves credentials in the API
   process (`src/mission_control/bootstrap/prerequisites.py:42-49`,
   `src/mission_control/adapters/prerequisites/probes.py:94-98`), and `g1/serve.py:81-84` gives the
   API only `ANTHROPIC_API_KEY`. Add `OPENAI_API_KEY` (and `CURSOR_API_KEY` for W3) to the API
   child environment before verifying the codex/cursor M4.
3. **`g1/restart_g1.py` is Claude-only and single-manifest.** It picks the `.a8.` and `.m4.` items
   (`restart_g1.py:215-216`; a codex manifest raises `StopIteration`) and rewrites
   `owner-probes.json` with only those two bindings (`:226-229`). Bindings are keyed per scoped
   prerequisite, so a served Claude + Codex + Cursor set needs all of a8, m4(claude), x4, x6,
   m4(codex), c9, m4(cursor) merged in one file.
4. **M4 evidence lives one hour.** `restart_g1.py:228` writes `max_age_seconds: 3600` for
   `broker_names`; re-verify M4 before any start more than an hour later.
5. **`caller_loop.py` decides only Claude `Bash` approvals.** Codex approval tasks carry
   `tool_name` `commandExecution` / `fileChange` / `permissions`
   (`src/mission_control/adapters/codex/approvals.py:102-107`); `caller_loop.py:70-76` leaves
   them for manual review and ends the loop. Extend the classifier before MR-02, or the 300 s
   auto-deny kills the turn.
6. **Temporal Cloud search attributes already exist; the named script is the wrong tool.** MO-78's
   readback records all 14 attributes and `"missing_search_attributes": []`
   (`task/mo78-acceptance-proposal/MO-78-ACCEPTANCE-EVIDENCE-2026-10-17.json`). W4.2 names
   `scripts/register_belllabs_search_attributes.py`, which uses the server Operator API
   (`src/mission_control/adapters/temporal/search_attributes.py:251-278`); Cloud readiness reads
   through Cloud Ops (`search_attributes.py:281-294`, `adapters/temporal/cloud_namespace.py:44`).
   The Cloud tool is `python -m scripts.temporal_cloud.configure_search_attributes --plan`
   (read-only), documented at `docs/MISSION_CONTROL_LOCAL_API.md:899-907`. Inference: the Operator
   add call is not the supported Cloud path.
7. **The MO-70 helper cannot mint for G1 as configured (inference).** `missionctl token mint`
   signs with a local private key and verifies against the application's `public_jwks_file`
   (`src/mission_control/adapters/auth/operator_token.py:15-67`). G1's `deployment.json`
   authentication is the Supabase issuer, ES256, with a pinned Supabase JWKS; no operator key is
   in it. Using the helper needs an owner-approved operator public key in that JWKS. Otherwise MO-70
   stays "recorded", and `launcher_token.py` (Supabase password grant) remains in use.
8. **MR-01 receipts have gaps.** `g1/s0-01k/` has no `run transcript` receipt and no file names
   the model; only `g1/s0-01b/transcript-1.json` contains `claude-sonnet-5-5`. Neither directory
   has a sentinel-search or child-allowlist receipt. W1 must recheck clauses 3.1.2 (pinned model),
   3.1.4 (transcript peek during the run) and 3.1.6 (hygiene) instead of assuming them.
9. **Codex binary.** The worker launches `~/.nvm/versions/node/v24.21.0/bin/codex`
   (`g1/serve.py:103`), not a binary in the WSL venv. The launcher refuses anything but
   `codex-cli 0.162.1` (`src/mission_control/adapters/codex/protocol.py:51`,
   `adapters/codex/launcher.py:14`). Confirm the version on that exact path. Several comments
   still say 0.162.0 (`bootstrap/settings.py:411`, `domain/execution/bindings.py:239`); the
   constant is authoritative.
10. **Codex auth must be the API-key route.** The native Codex verifier accepts only
    `billing_mode == "api"` (`src/mission_control/adapters/prerequisites/codex_native.py:180-186`),
    and the harness performs an ephemeral API-key login only in `isolated` home mode
    (`adapters/codex/harness.py:927-937`). SPEC-09's "logged in with ChatGPT" owner selection
    (`SPEC-09-local-harness-path.md:147`) has no probe path; W2's `codex-api-configured` is right.

## 1. Mission authoring path

### 1.1 Manifest (`mission/v2`)

Capability: a YAML mission compiled against the installed catalog into an admitted definition.
Models: `src/mission_control/domain/authoring/manifest_v2.py` (V2 additions) over
`domain/authoring/manifest.py` (base). Template for every MR cell: `task/run2-close-20261018/g1/f1k.mission.yml`.

| Knob (YAML path) | Model and line | MR use / gotcha |
| --- | --- | --- |
| `environment.lane` | `manifest.py:588` (`Environment.lane`) | `claude_agent_sdk`, `codex`, `cursor_local`. L for claude |
| `environment.model.profile` | `manifest.py:535-537` | A profile name resolved in the lane binding's `model_profiles`: `claude.default` → `claude-sonnet-5-5`, `codex.default` → `gpt-6-luna` (G1 bindings). The model id is never in the manifest |
| `environment.auth.profile` | `manifest_v2.py:111-116`, `:317` | `claude-sdk-api`, `codex-api-configured`; Cursor needs a new profile |
| `environment.execution_environment` | `manifest_v2.py:123-145` | `kind: local_workspace`, `profile: worker.linux.wsl` |
| `environment.plugins[].pin` | `manifest.py:596` | f1k pins `plugin.cognition-sdlc@1#sha256:a57f…`. Members are expanded by the plugin row (P5a) |
| `environment.capabilities` / `agents` / `hooks` | `manifest.py:593-595` | skills/MCP/subagents/hook pins; the S0 probes pin `skill.mission-control-observe@0.3.1` |
| tool allow/deny | **not a manifest field** | Claude: `provider_options.allowed_tools/disallowed_tools` in the binding (`domain/execution/bindings.py:223-232`); G1 allows `Read Grep Glob Write Edit Bash`, disallows `WebFetch WebSearch`. Codex has no tool lists, only `approval_policy` and `sandbox_mode` (`bindings.py:235-243`). Cursor: `disallowed_tools` on the binding (`application/authoring/cursor_launch.py:165`) |
| `environment.network` | `domain/authoring/mission_environment.py:168-191` | `mode: allowlist|none|allow_all`, `allow`, `include_kit`; G1 host binding allowlists `127.0.0.1` |
| `environment.variables[].value_ref: config:<key>` | `mission_environment.py:280-297`; resolution section 1.3 | f1k: `MC_FOCUSED_TESTS ← config:sdlc.focused_tests`. Compile-only: the value is not delivered to the lane runtime (known limit) |
| `environment.workspace.repo` / `.policy` | `manifest_v2.py:167-175`, `:215-230` | **`reuse: none`** (default `within_run`, `application/workspaces/policy.py:45-50`, is the K01 trap) |
| `environment.workspace.outputs` | `manifest_v2.py:193-200` | default `outputs/` |
| `environment.requires` | `manifest_v2.py:273-283` | `approvals: [workflow_gate]`; do not require `provider_permission` on Cursor |
| `environment.budget` / `governors` | `manifest.py:562-576` | f1k: 400k tokens, 120 tool calls, 45 min |
| `controls.commands_allowed` | `domain/authoring/mission_watchers.py:98` | `cancel`, `interrupt_and_inject`, `queue_instruction` |
| `goals[].criteria[].acceptance` | `manifest.py:628-677` | `schema: schema.sdlc-…@1` or `human: review_accept`; free text is refused |
| `program.behavior: stage_graph`, `nodes[]` | `manifest_v2.py:625-628` | DAG via `depends_on`; one goal per stage (workaround) |
| `agent_executor.instruction` / `outputs[]` | `manifest.py:789-794`, `:708-711` | One required output per stage; output name = slot id = `outputs/<name>.json` (P5c) |
| `inputs[]` (`from: stage.output`, `expand: materialize`) | `manifest.py:681-705` | Lands under `inputs/<binding>/` |
| `human_gate.task` (`kind`, `prompt`, `reviewers`, `packet`, `timeout`, `on_timeout`) | `manifest.py:817-828` | Reviewers = `service:run2-s0-launcher` (disclosed); the caller must be in the gate's reviewer list |

Gotchas: the S0 example manifests (`examples/s0-codex.mission.yml:34`,
`s0-cursor-local.mission.yml:34`) still name `codex-owner-chatgpt`, `cursor-local-key`,
`reuse: within_run` and `OWNER-SELECT` placeholders; derive MR manifests from f1k, not from them.
f1k's instructions also name the WSL venv pytest path; Codex and Cursor stages run in their own
leases with the same host paths.

### 1.2 Compile → preflight → submit → start

| Step | HTTP route | Service | missionctl | Label |
| --- | --- | --- | --- | --- |
| compile | `POST /v1/applications/{app}/missions:compile` (`interfaces/http/missions.py:176`; 200 ok / 422 blockers) | `ManifestCompileService.compile` (`application/authoring/manifest_service.py:544`) | `mission compile FILE [--offline]` (`interfaces/cli/main.py:883-889`) | L |
| preflight | `missions:preflight` (`missions.py:192`) | `MissionManifestService.preflight` (`manifest_service.py:1690`) → `PrerequisitePreflight.assess` (`application/prerequisites/preflight.py:377`) | `preflight FILE` (`main.py:783-785`) | L |
| prereq verify | `POST /prerequisites/{id}:verify` (`missions.py:147-166`; needs `prerequisite.verify`) | `InstallationOwnerProbes.verify` (`bootstrap/prerequisites.py:34-55`) | `prereq verify ID --definition-digest D` (`interfaces/cli/setup.py:121-129`) | L (A8, M4) |
| submit | `missions:submit` (`missions.py:243`; 201 new, 200 replay/unchanged) | `ManifestSubmitService.submit` (`application/authoring/manifest_submit.py:307`) | `mission submit FILE [--request-id]` (`main.py:890-892`) | L |
| start | `missions:start` (`missions.py:315`, 202; `notify=inbox` default) | `ManifestSubmitService.start` (`manifest_submit.py:432`) | `mission start RUN_ID [--notify inbox|none]` (`main.py:893-898`) | L |

Gotchas: start answers 422 `PREREQUISITES_UNMET` before any create when a probe is missing or
stale, and 409 `start_unavailable` for projection refusals (`missions.py:276-306`). Submit
answered 200 `unchanged:false` on a first submission after a transport retry (ledger P3); do not
treat 200 as a replay. The preflight item ids and definition digests the verify call needs come
from the preflight body (`restart_g1.py:207-216` shows the extraction).

### 1.3 Installation configuration source (P1, `c49862bf`)

`MISSION_CONTROL_INSTALLATION_CONFIG_PATH` → `Settings.mission_control_installation_config_path`
(`bootstrap/settings.py:293`). The loader (`bootstrap/installation_config.py:137-166`) requires
top-level `schema: "mc.installation_config.v1"` (key `schema`, not `schema_version`), optional
`$comment`, `applications: {app: {key: value}}`; unknown fields, secret-like keys
(key|token|secret|password|passwd|dsn|credential) and a BOM refuse. Composition hands the
Application's mapping to compile (`bootstrap/manifests.py:102-126`, `:166`); compile reports
`config_secret_like` / `config_unresolved` (`application/authoring/manifest_v2_admission.py:351-360`).
Example: `deployments/examples/installation-config.example.json`. Label: L (F1 compile). A missing
or invalid file fails manifest composition, so it breaks every lane at once.

## 2. Owner prerequisites and probes per lane

### 2.1 Which prerequisites each lane needs

`application/prerequisites/catalog.py:270-298` maps lanes to codes; ids become
`<lane>.owner.<code>` and probe codes `prerequisite:<code>` (`catalog.py:336-359`). Preflight then
scopes each to the selected identity, appending a 24-hex suffix to the id and, for native lanes,
the identity digest to `why` (`application/prerequisites/preflight.py:303-374`).

| Lane | Codes | Owner-probe operation (method `file_check`) | Verifier |
| --- | --- | --- | --- |
| claude_agent_sdk | A8, M4 | `claude_native_host`, `broker_names` | `adapters/prerequisites/claude_native.py:42-109` (L) |
| codex | X4, X6, M4 | `codex_native_auth` (x4), `codex_native_cli` (x6), `broker_names` | `adapters/prerequisites/codex_native.py:153-193` (T) |
| cursor_local | C9, M4 | `cursor_native_host`, `broker_names` | `adapters/prerequisites/cursor_native.py:222-291` (T) |

Dispatch and the operation-to-probe allow-list: `adapters/prerequisites/probes.py:51-98` (an
operation must match its probe code, e.g. `codex_native_cli` only for `prerequisite:x6`).

### 2.2 File formats

- **`mc.owner_probes.v1`** (`application/prerequisites/probes.py:126-240`): `{schema_version,
  bindings: [...]}`; each binding has `request_scope`, `prerequisite_id` (the scoped id),
  `definition_digest`, `operation`, `max_age_seconds` (60 s–30 d, default 86400), and exactly one
  of `credentials` (SecretRefs, for `broker_names`) or `native_claude` / `native_codex` /
  `native_cursor` (`probes.py:170-209`). Unique per (scope, prerequisite). The file is re-read on
  every verify (`bootstrap/prerequisites.py:40-49`), but `g1/serve.py:83-84` only sets the env var
  when the file exists at API start: create it first, then rewrite freely.
- **`mc.manifest_launch_bindings.v2`** (`application/authoring/manifest_launch_inputs.py:341-370`):
  `providers.{claude_agent_sdk,codex}` are `ProviderLaneBinding`
  (`application/authoring/provider_launch.py:100-139`: `task_queue`, `model_profiles`,
  `auth_profiles`, `host_profiles`, `pins`, discriminated `provider_options`, `budgets`,
  `agent_profile_ref`, policy refs, `workspace` (`WorkspaceProvision`), `repository_commits`);
  `providers.cursor_local` is `CursorLocalLane` (`cursor_launch.py:127-176`: plus `repositories`,
  `pins` that must equal `REQUIRED_CURSOR_PINS` = cursor_sdk/bridge `1.0.37`, protocol `sdk.v1`,
  cloud_api `v1` (`cursor_launch.py:62-64`), `hook_callback.listen` `127.0.0.1:<port>`,
  `sandbox_enabled`, `disallowed_tools`, `lease_root`). Capability pins are refused in a binding
  (`provider_launch.py:136-137`); they come from the manifest.
- **`mc.auth_profile.v1`** (`{"profiles": [...]}`; shape in
  `deployments/examples/provider-auth-profiles.example.json`, setting `bootstrap/settings.py:360`):
  G1 entries carry `profile_id`, `lane_profile`, `route: api_key`, `billing_mode: api`,
  `credential_ref: env:<NAME>`, `shadowing: reject`, `max_observation_age_s: 300`.

### 2.3 A8 (Claude) as served: derivation and verification (L)

1. `attest_claude_host.py --measure` hashes the uv Python tree, the venv tree, MAIN `src/**/*.py`
   plus the overlay file and an environment manifest into a `WorkspaceProvision`
   (`g1/attest_claude_host.py:70-102`). Any source change alters `package_digest`, hence A8.
2. `restart_g1.py:197-199` writes that provision into `providers.claude_agent_sdk.workspace`.
3. Preflight derives the identity from the binding (`application/prerequisites/preflight.py:124-174`:
   workspace, host profile, auth, CLI and SDK pins, host-configuration digest, `auth_route`,
   model id, provider options, agent profile ref) and appends
   `" Native Claude host identity: sha256:<digest>"` to `why` (`preflight.py:353-363`).
4. `g1/claude_identity.py` recomputes the same dict and asserts equality with the `why` digest.
5. `attest_claude_host.py --observe` checks the bundled CLI (`2.1.294`) and SDK (`0.2.165`), adds
   `build_commit`, `cli_sha256`, `attestor`, and writes `mc.claude_native_host_observation.v1`.
6. `restart_g1.py:225-229` pins `path` + `content_sha256` in `owner-probes.json`; then
   `prereq verify` for A8 and M4. The verifier (`claude_native.py:48-106`) checks the scoped
   prerequisite, the `why` digest, a bounded regular non-symlink file, the content hash, identity
   equality, versions, `billing_mode api` / `auth_route api_key`, and freshness.

### 2.4 Codex X4/X6 (new work for W2): exactly what the verifier checks

- **Identity in `why`** (`preflight.py:82-121`, `:339-350`): `{workspace, host_profile, auth,
  cli_version (pins["cli.codex"]), model_id}` from `providers.codex` and the manifest's
  model/auth/host selections. The digest covers only these five fields.
- **Pinned binding** `native_codex` (`application/prerequisites/probes.py:21-45`): the five fields
  plus `build_commit` (40 hex), `cli_sha256`, `attestor`, absolute `path`, `content_sha256`. One
  observation file can back both the x4 and x6 bindings (two binding entries, same evidence).
- **Observation** `mc.codex_native_observation.v1` (`codex_native.py:130-150`): `identity`
  (equal to the pinned identity), `observed_at`, `cli_version_observed` = pin,
  `cli_sha256_observed` = pin, `api_login: "apiKey"`, `account_read: "apiKey"`,
  `credential_store: "ephemeral"`, `auth_json_created: false`, `thread_started: false`,
  `turn_started: false`, `remote_model_id` = `model_id` (`gpt-6-luna`), `remote_metadata_access: true`.
- **What the attestor must actually do** (inference from the fields and the X4 step text at
  `preflight.py:343-350`): start the pinned app-server with an isolated `CODEX_HOME` and
  `cli_auth_credentials_store="ephemeral"`, `initialize`, `account/login/start` with the API key,
  `account/read` (type `apiKey`), and a read-only model metadata call (`model/list`,
  `adapters/codex/protocol.py:128`) that lists `gpt-6-luna`; no thread, no turn. The harness does
  the same login sequence at session start (`adapters/codex/harness.py:927-997`), which is the model
  to copy. This calls OpenAI (metadata only); keep the key in the child environment.
- Unlike A8, the Codex verifier does not refuse symlinked paths and does not re-check the
  prerequisite id itself (`codex_native.py:173-177`); ConfiguredOwnerProbes still checks the
  definition digest (`probes.py:271-274`). The G1 `providers.codex.workspace` digests were carried
  from an older configuration, not re-measured (ledger P3): measure and write them as for Claude.

### 2.5 Cursor C9 (new work for W3): exactly what the verifier checks

- **Identity in `why`** (`preflight.py:201-269`, `:364-372`): workspace, host profile, host
  configuration digest, auth, `auth_route`, agent profile ref and a `cursor_configuration` (pins,
  model id, `CursorWorkspace` {repo_url, base_ref, lease_root, branch_prefix, admitted policy},
  mode, sandbox_enabled, disallowed_tools, hook-callback digest). It requires `lease_root`, a
  `repositories` entry keyed by the manifest's `repo.path` with a non-null `repo_url`, and a
  `repo.ref` among that entry's `base_refs`.
- **Pinned binding** `native_cursor` (`probes.py:78-123`): adds `build_commit`, `attestor`,
  `observed_repository_commit`, `git_executable` + `git_sha256`, `node_version` (literal
  `v24.5.0`), `node_sha256`, `bridge_archive_version` (literal `1.0.0`), `bridge_archive_sha256`,
  `sdk_closure_sha256`, `loader_closure_sha256`.
- **Observation** `mc.cursor_native_host_observation.v1` (`cursor_native.py:56-77`): the observed
  versions above, zero provider calls, and a `cleanup_fixture`. The verifier runs `git rev-parse`
  in the protected root **in the API process** and requires: `str(protected_root) == repo_url`,
  the retired worktree under `lease_root` and already absent, distinct before-identities, an
  unchanged root identity and identical protected file snapshots (`cursor_native.py:105-219`).
- Prior art (private): `task/run2-fresh-session-20261017/g1-current-bindings/native-cursor-observation-v2/capture_host_core.py`
  built this observation against an older wheel; reuse its method, not its pins.
- The Node pin `v24.5.0` is the bridge's runtime, not the WSL `nvm` Node `v24.21.0` on the
  worker PATH (`g1/serve.py:79`); measure what `cursor_sdk._vendor.resolve_bridge_path()` launches
  (`adapters/cursor/bridge_spawn.py:24-25`, `:58-60`).

### 2.6 M4 (`broker_names`)

Binding: `credentials: [{"provider":"environment","key":"<NAME>"}]`; the probe only checks that
the broker resolves each name (`probes.py:94-98`). One M4 per lane scope (claude:
`ANTHROPIC_API_KEY`, codex: `OPENAI_API_KEY`, cursor: `CURSOR_API_KEY`). The names must be in the
**API** environment (item 0.2).

## 3. Serving composition

### 3.1 Entry points

| Process | Entry point | Notes |
| --- | --- | --- |
| API | `mission_control.bootstrap.api:create_app` (`bootstrap/api.py:736`), uvicorn `--factory` on `127.0.0.1:18090` (`g1/serve.py:85-88`) | Loads `MISSION_CONTROL_DEPLOYMENT_FILE` (`api.py:718-721`); per application, resolves the Temporal connection and verifies search attributes before serving (`api.py:355-370`) |
| Worker | `python -m mission_control.bootstrap.worker` (`bootstrap/worker.py:781-801`) | Requires `MISSION_CONTROL_WORKER_APPLICATION_ID` and `MISSION_CONTROL_WORKER_BINDING_DIGEST` (`worker.py:785-787`); `run_worker` (`worker.py:396-560`) verifies pins and host readiness (`:317-366`), connects, verifies search attributes (`:428-432`), builds activities and workers |
| G1 launcher (private) | `g1/serve.py api|worker` via `wsl.exe` + `g1/linux_exec.py` (secrets over stdin); `g1/restart_g1.py <manifest>`; `g1/wsl_ctl.sh stop-api|stop-worker|status` | DSNs and API keys from AWS Secrets Manager `mission-control/ai-engineer/<NAME>` (`serve.py:36-44`) |

### 3.2 Settings that matter (`bootstrap/settings.py`; `.env` at `MISSION_CONTROL_HOME` is also read, `:18`, `:56-58`; MAIN has no `.env`)

| Concern | Setting / env name | Line | G1 value |
| --- | --- | --- | --- |
| Temporal target | `TEMPORAL_TARGET` (`local`/`cloud`), `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_CLOUD_API_KEY` | 324-329 | local, `127.0.0.1:17233`, `mc-run2-s0` |
| Versioning | `TEMPORAL_WORKER_VERSIONING`, `TEMPORAL_BUILD_ID`, `TEMPORAL_PROMOTE_ON_START` | 332-335 | false, `0.1.0-run2-close`, false |
| Execution gate | `COORDINATOR_LAUNCH_ENABLED` | 141 | true (worker refuses otherwise, `worker.py:240-241`) |
| Worker role, lane queues | `MISSION_CONTROL_WORKER_ROLE`, `MISSION_CONTROL_LANE_TASK_QUEUES` (JSON) | 266, 398 | base; `["mc-run2-close-lane-claude","mc-run2-close-lane-codex"]` |
| Lane opt-ins | `MISSION_CONTROL_CLAUDE_LANE`, `MISSION_CONTROL_CODEX_LANE`, `CURSOR_API_KEY`, `MISSION_CONTROL_ALLOW_UNQUALIFIED_LANES` | 401, 405, 338-339 | true, true, unset, true |
| Lease roots | `MISSION_CONTROL_CLAUDE_LEASE_ROOT`, `MISSION_CONTROL_CODEX_LEASE_ROOT`, `CURSOR_LEASE_ROOT`, `DEEP_AGENT_SANDBOX_WORKSPACE_ROOT` | 402, 407, 349, 312 | `~/mc-leases/{claude,codex}`, unset, `~/mc-close-workspaces` |
| Codex | `MISSION_CONTROL_CODEX_BINARY`, `…_CODEX_HOME_MODE` (`isolated` required for API key), `…_CODEX_ALLOW_VERSION_MISMATCH` | 406-412 | nvm `codex`, isolated, false |
| Hooks | `MISSION_CONTROL_HOOK_CALLBACK_PORT` | 355 | 47561 (Cursor binding `hook_callback.listen` must match) |
| Approvals | `MISSION_CONTROL_APPROVAL_REVIEWERS` (default `("owner",)`), `MISSION_CONTROL_APPROVAL_WAIT_S` (300) | 389-392 | `["service:run2-s0-launcher"]` (disclosed) |
| Bindings and probes | `MANIFEST_LAUNCH_BINDINGS_PATH`, `MISSION_CONTROL_OWNER_PROBES_PATH`, `MISSION_CONTROL_AUTH_PROFILES_PATH`, `MISSION_CONTROL_INSTALLATION_CONFIG_PATH`, `CAPABILITY_PINS_PATH` | 287-293, 360, 281 | `g1/config/*.json` |
| Payloads | `ARTIFACT_PAYLOAD_ROOT` (shared by API and worker; S3 when `S3_BUCKET`) | 262 | `~/mc-close-artifacts` |
| Workspace roots | `MISSION_CONTROL_WORKSPACE_ROOT`, `MISSION_CONTROL_PREFLIGHT_WORKSPACE_ROOT` (MO-68) | 22-30, 443 | `g1/config/assets` |
| Catalog | `MISSION_CONTROL_CATALOG_SCOPE`, `CAPABILITY_BUNDLE_BACKEND/LOCAL_ROOT` | 314, 305-311 | `mc/01a103c0…/ai-engineer/catalog`, local |
| Databases | `binding.database_secret_ref` = `MC_AI_ENGINEER_RUNTIME_DSN` (read by name, `worker.py:253`), `family_writer_secret_ref` = `MC_AI_ENGINEER_FAMILY_DSN`, `LANGGRAPH_CHECKPOINT_DATABASE_DIRECT` (must be the same database, `worker.py:256-273`) | — | from AWS, `sslmode=verify-full` + pinned CA |

### 3.3 Queues and roles

The deployment file's per-application `temporal` block names `address`, `namespace`,
`stagegraph_task_queue` (must end `-coordinator-family-stagegraph`), `goal_directed_task_queue`
(must match the same base) and `root_task_queue` (`worker.py:242-251`). The base worker serves the
coordinator, operation, artifact, linked-run (`<base>-linked-runs`) and maintenance queues plus the
lane queues listed in `MISSION_CONTROL_LANE_TASK_QUEUES` (`adapters/temporal/worker.py:143-147`);
each binding's `task_queue` must be one of them. A `lane` role worker needs an explicit build id
and non-base queues (`worker.py:275-278`, `adapters/temporal/worker.py:148-160`); MO-63 moved
lane-only workers out of Run 2.

### 3.4 Pointing at Temporal Cloud (W4)

- Values (R20, `DECISIONS.md:48`; `SPEC-09-local-harness-path.md:148`;
  `deployments/worker-aws/plan.py:15-18`): `TEMPORAL_TARGET=cloud`,
  `TEMPORAL_ADDRESS=us-east-1.aws.api.temporal.io:7233`,
  `TEMPORAL_NAMESPACE=mission-control-dev.ih0e7`, `TEMPORAL_CLOUD_API_KEY`. The key is in the
  canonical `.env` (R20) and in AWS Secrets Manager as
  `mission-control/ai-engineer/TEMPORAL_CLOUD_API_KEY` (`plan.py:41-49`, `:99`;
  `deployments/worker-aws/README.md:27`). Fetch it into the child environment as `serve.py`
  does for the other secrets.
- **Both** the env vars and `deployment.json` `applications[].temporal.{address,namespace}` must
  change: on the Cloud target `resolve_temporal_connection` refuses a deployment that names another
  address or namespace (`adapters/temporal/client.py:84-104`). TLS and the API key are applied only
  when `target == "cloud"` (`client.py:56-58`, `:113-123`).
- Startup (API and worker) verifies the 14 attributes through Cloud Ops with the same key
  (`search_attributes.py:281-299`, `cloud_namespace.py:44`), so the key needs Cloud Ops read access
  to the namespace (R20 calls it an account-owner key).
- Use fresh private queue names (a new `<base>-coordinator-family-*` set and new lane queues) in
  `deployment.json`, `launch-bindings.json` `task_queue` and `MISSION_CONTROL_LANE_TASK_QUEUES`
  together. `task_queue` is not part of the A8/X/C9 identities (section 2), so changing it does not
  invalidate probes; changing the source tree does.
- Run identity records the cluster `<target>:<address>/<namespace>`
  (`bootstrap/composition.py:159-173`). Cursor bridge recovery compares `temporal_target`
  (`bootstrap/cursor_bridges.py:44`): do not reuse Cursor leases across the switch.
- No-op connection probe after the readback: `python -m scripts.temporal_cloud.probe --execute-noop`
  (`docs/MISSION_CONTROL_LOCAL_API.md:905-907`), authorized separately.

## 4. Lanes in scope

Shared path: `LaneTurnService` (`application/execution/harness/lane_turns.py`) drives
prepare → start → send_turn → observe → end_session on each harness. Projection is checked against
the sealed `materialization_digest` (baseline §4). Per-lane matrix: baseline §9.

### 4.1 claude_agent_sdk (Claude Agent SDK 0.2.165, bundled Claude Code 2.1.294)

| Concern | Entry point | Label |
| --- | --- | --- |
| Composition | `compose_claude_local_lane` (`adapters/temporal/provider_lane_composition.py:122-178`): needs opt-in, an auth profile path and a supported host (`host_gate`, `adapters/claude/host.py`; Windows refused) | L |
| Prepare / projection | `ClaudeAgentSdkHarness.prepare` (`adapters/claude/harness.py:499-583`): lease, `materialize_packet`, projection digest check (`CAPABILITY_DRIFT`), `materialize_projection` | L |
| Options | `_options` (`harness.py:637-699`): `model` from the binding, `permission_mode`, `allowed_tools`, `disallowed_tools`, `setting_sources` (G1 `["project"]`), system prompt/agents from send options, Kernel Hook matchers, `can_use_tool` → broker, network sandbox | L |
| Instructions | channels `CLAUDE.md`, prompt, `.claude/settings.json` (`application/execution/harness/describe.py:422`); repo AGENTS.md preserved (L, runs b-k) | L |
| Approvals | `can_use_tool` → `PermissionBinder` → Human Task (`approval:provider_permission`); reviewers and wait from settings (`provider_lane_composition.py:166-173`) | L allow/deny |
| Disallowed tools | absent from the native tool set (run b: `WebFetch` not found), not a typed hook deny | L |
| Cancel | `cancel_turn` → `session.interrupt` (`harness.py:933-953`) | L (run b, ~30 s) |
| Inject | `cancel_and_replace` (`describe.py:405`); P5b keeps the interrupted turn from settling the attempt | L (runs b, c, d, j) |
| Outputs | `_output_files` collects every regular file under `outputs/` (`harness.py:374-382`) and registers each at `end_session` (`harness.py:1159-1172`) | L |
| Usage | `usage` from `ResultMessage.usage` (`harness.py:972-987`); every run projected `unknown` (E8) | L unknown |

### 4.2 codex (app-server, codex-cli 0.162.1, protocol v2)

| Concern | Entry point | Label |
| --- | --- | --- |
| Composition | `compose_codex_local_lane` (`provider_lane_composition.py:181-229`); refused on `win32` (`:196`); hooks answer on the loopback listener (`:226`) | U |
| Launch and auth | `GitWorktreeLeaser` lease under `binding.workspace_policy` (`adapters/codex/harness.py:755`); isolated `CODEX_HOME`; API-key route requires `isolated` mode, logs in ephemerally and confirms `account/read` type `apiKey` or terminates (`harness.py:925-997`); `OPENAI_API_KEY`/`CODEX_API_KEY` never forwarded to tool shells (`adapters/codex/launcher.py:142-145`) | T |
| Thread options | `_thread_start_params` (`harness.py:1037-1046`): `model`, `approval_policy` (binding: `on-request`), `approvals_reviewer: user`, `sandbox` (binding: `workspace-write`), `developer_instructions` from the projection (`harness.py:510-516`, `:786`) | T |
| Instructions | `AGENTS.md`, `.codex/config.toml`, `developer_instructions` (`describe.py:495`) | T |
| Tool policy | no allow/deny lists; the "disallowed family" for MR-02 has to be shown by sandbox/network refusal or a denied approval | T |
| Approvals | `item/commandExecution|fileChange|permissions/requestApproval` → `provider_permission` Human Tasks; reply accept/deny only (`adapters/codex/approvals.py:1-60`, `:102-107`) | U |
| Cancel | `turn/interrupt`, then waits for the terminal `turn/completed` (`harness.py:1558-1592`) | U |
| Inject | `cancel_and_replace`; native `turn/steer` unused (`describe.py:480`) | U |
| Outputs | `end_session` registers `leaser.outputs(...)` (`harness.py:2280-2310`) | U |
| Usage | per-turn tracker (`harness.py:1897-1906`); tokens `settled_per_turn`, cost `estimated` | U |
| Hooks / hook trust | trust records in the isolated `config.toml` (`adapters/codex/hook_trust.py:12-18`); MO-03 moved to the Codex sprint | T |

### 4.3 cursor_local (cursor-sdk 1.0.37 bridge)

| Concern | Entry point | Label |
| --- | --- | --- |
| Composition | `compose_cursor_local` (`adapters/temporal/deployment_composition.py:824-866`): only when `CURSOR_API_KEY` is set; lease root `CURSOR_LEASE_ROOT` or `<sandbox root>/cursor-leases`; hook callback `http://127.0.0.1:<port>` | T |
| Host gate | `host_gate` (`adapters/cursor/bridge.py:193-213`): Linux/WSL and macOS; Windows refused unless `MISSION_CONTROL_CURSOR_WINDOWS` | T |
| Bridge | `SdkBridgeLauncher` → detached bridge with an explicit environment (`adapters/cursor/bridge_spawn.py:1-60`) | T |
| Lifecycle | `CursorLocalHarness` prepare/start/send/cancel/usage/end (`adapters/cursor/local.py:389`, `:534`, `:792`, `:997`, `:1046`, `:1175`) | T |
| Instructions | `AGENTS.md`, `.cursor/rules/mc-mission.mdc`, prompt prefix (`describe.py:140`) | T |
| Approvals | hook deny only; no per-command ask-to-human (baseline §6). Refusing `provider_permission` is correct | T |
| Inject / cancel | `cancel_and_replace` / `turn_boundary_guaranteed` (`describe.py:124-131`) | T |
| Usage | settled only when the bridge reports it; otherwise `unknown` (`local.py:1046-1089`) | T |
| Binding to add (W3) | `providers.cursor_local` with `task_queue` (also in `MISSION_CONTROL_LANE_TASK_QUEUES`), `model_profiles` (`cursor.default` → owner-selected id; R22 says Cursor Auto), `auth_profiles`, `repositories` keyed by the manifest `repo.path` with `repo_url` = that absolute path and `base_refs`, `pins` = `REQUIRED_CURSOR_PINS`, `hook_callback.listen: 127.0.0.1:47561`, `host_profiles.worker.linux.wsl`, `lease_root`, `workspace` (measured) | — |

Memory: the LS-07 measurement (about 3.6 GB commit) was for the `cursor-agent` CLI, not this
bridge. The bridge's footprint is unmeasured (inference); W3's memory gate still applies.

### 4.4 P5 changes on `main` (all reviewed, Opus 5.5)

| Change | Commit | Where now |
| --- | --- | --- |
| P5a: a selected plugin is pinned whole on claude/codex; members skipped like Cursor | `ac9d5e7e` | `application/authoring/manifest_launch_inputs.py:1117`, `:2240` (Cursor path `:1485`) |
| P5b: an applied inject's interrupted turn no longer settles the attempt | `aeeda4a4` | `application/execution/harness/lane_turns.py:3067`, `:3504-3522`; `application/frames/reducer.py:137`, `:458` |
| P5c: session-lane packets name lease-relative `outputs/<slot>.json`, `inputs/`, `.mission/` and the JSON final-answer contract (`{"output_refs": []}`) | `c7f79b50` | `application/context/pack_service.py:1089-1105`, `:1212-1238` |
| P5d: set-order independent family mutation fingerprint and journal read-back | `5149bcbb` (+ `6fcb4f82` test fix) | `application/execution/run_control_repository.py:167`; `domain/programs/contracts.py:726-749` |
| Overlay: `cursor_bridge_recovery.py` reuses `BridgeShutdownDisposition` | `57b91dd8` | `application/execution/harness/cursor_bridge_recovery.py` (hashed into the A8 package digest, `attest_claude_host.py:29`, `:78`) |

## 5. Observation and control surfaces

| Surface | missionctl | HTTP | Label / gotcha |
| --- | --- | --- | --- |
| Wake | `wait --run RUN [--kinds …] [--ack] [--wait S] [--follow]` (`interfaces/cli/wait.py:48-56`, `:118-160`); exit 0 on wake, 6 on timeout | inbox list/notifications `interfaces/http/coordinator_inbox.py:154`, `:173` | L. Kinds: `review_required`, `blocked`, `failed`, `terminal_result`, `accepted_output`, `child_lifecycle`, `review_closed`, `progress` (`domain/subscriptions/significance.py:12-21`). Uses the caller's existing inbox for the run, else creates one replaying from seq 0 (`wait.py:97-115`) |
| Inbox | `inbox list --run`, `inbox ack SUB --id/--through` (`wait.py:57-66`) | — | Unacked notifications reprint on the next one-shot wait |
| Inspect | `run inspect RUN` (`main.py:789-790`) | `GET /runs/{id}` (`interfaces/http/runtime_inspection.py:124`) | L |
| Transcript | `run transcript RUN [--format md] [--since] [--node] [--kinds] [--follow]` (`main.py:810-821`) | `GET /runs/{id}/transcript` (`interfaces/http/transcript.py:228`) | L (run b). `--full` returns 501 (baseline §7) |
| Frames | `run frames RUN --tail [--after] [--until-end]` (`main.py:822-826`) | `GET /runs/{id}/frames/tail` (`transcript.py:253`) | T |
| Cancel | `command cancel RUN --urgency normal|immediate` (`main.py:869-873`) | `POST /runs/{id}/commands` (`interfaces/http/run_control.py:507`) | L (run b) |
| Inject | `command inject RUN --file F [--node-key]` (`main.py:862-868`) | same | L (b, c, d, j) |
| Queue | `command queue RUN --file F [--add-context]` (`main.py:850-861`) | same | T |
| Human tasks | — (no missionctl command) | `GET /human-tasks?run_id&lifecycle=open` (`interfaces/http/human_tasks.py:77`), `GET /human-tasks/{id}` (`:95`), `POST …/resolutions` (`:106`, body `HumanResolutionRequest`: `request_id`, `expected_task_version`, `decision` approve/deny/request_changes, `reviewed_packet_digest`, `comment`, `domain/programs/human_gate.py:314-322`), `POST …/approval-resolutions` (`:123`, `ApprovalResolutionRequest`, `application/execution/approvals.py:606-620`) | L. Private helpers `g1/tasks.py`, `g1/caller_loop.py:63-80` |
| Reconcile unit | — | `POST /runs/{id}/reconcile-unit` (`run_control.py:549`) | Needs `workflow_run.reconcile_unit`; the launcher grant lacks it (`ec193a1e` stays parked, E4) |

States: phases `pending|active|waiting|paused|cancelling|terminal`, outcomes
`completed|partially_completed|failed|cancelled` (`domain/policies/contracts.py:79-91`); Temporal
visibility phase also has `in_doubt` (`domain/programs/search_attributes.py:34`).

Tokens: `g1/launcher_token.py` signs the service account in through Supabase (password grant from
AWS `S0_LAUNCHER_AUTH` / `S0_OBSERVER_AUTH`) and writes a 0600 file; tokens last one hour.
`g1/mctl.py:101` reads the token once per process, so a single long `wait` cannot outlive it
(K16); keep `--wait` under the remaining lifetime and re-mint between calls. The repository helper
`missionctl token mint` (`interfaces/cli/token.py:15-58`) needs `--auth-config`,
`--private-key-file`, `--key-id`, `--subject`, `--tenant`, `--scope`, `--expires-in ≤ 3600`, and
refuses an existing `--out` file (`O_EXCL`, `token.py:49-50`); see item 0.7.

## 6. Custody and outputs

- **Lease layout** (`application/agentic_components/placement.py:1-51`, `:256-271`):
  `.mission/` (context index, operating contract, hooks, state), `inputs/<binding>/` read-only
  (mode 0444, digest-verified), and an `outputs/` created with `exist_ok=True` (not emptied: K01).
- **Lease slot by policy** (`application/workspaces/policy.py:111-125`): `none` → one slot per
  holder generation; `within_session`; `within_run` (default) → one worktree for the whole run.
- **Registration** (`application/execution/operations/lane_outputs.py:61-136`): each file under
  `outputs/` becomes a workspace candidate of the operation's writable slot at `end_session`; with
  one writable slot, every file lands there, so two files mean two candidates (runs f, h, i).
- **Schema validation**: required outputs need a bound validator at compile
  (`application/authoring/completion_support.py:94-114`, reason
  `output_schema_validator_unavailable`); bytes are validated offline with JSON Schema 2020-12
  (`application/programs/artifact_validation.py:1-24`).
- **D5 seeds** (L, applied live with readback): definitions in
  `packages/mission-control-db-contract/seeds/sdlc_report_schemas.py:101-216`
  (`schema.sdlc-diagnosis-report`, `-patch-report`, `-review-report`, versions
  `mc.sdlc_*_report.v1`, strict `additionalProperties: false`), frozen bundle
  `packages/mission-control-db-contract/seeds/ai-engineer/mc.app.ai-engineer.artifact-schemas-1.0.0.json`,
  registered by `packages/mission-control-db-contract/seeds/generate_catalog_seeds.py:727-734`
  (`bb2388b1`, `b9588f44`). Report rules that bite: diagnosis `disposition: diagnosed` requires
  `affected_files`, `evidence_refs`, an identified root cause and an observed/failed reproduction;
  patch and review need at least one `tests`/`tests_rerun` entry with observed exit codes;
  `changes_required` needs findings (`sdlc_report_schemas.py:101-190`).

## 7. CLI delegation skills for LS-08 (W5)

Location: `.agents/skills/` in the repository. These jobs have no Mission Control lifecycle.

- **Router** `.agents/skills/coding-cli-jobs/SKILL.md`; runner
  `.agents/skills/coding-cli-jobs/scripts/agentjob.py` (commands `run JOB… [--max-parallel N]
  --allow-live [--i-understand]`, `doctor JOB`, `status ID --repo R [--follow]`, `cancel ID`,
  `agentjob.py:529-576`); adapters `scripts/adapters/{claude,codex,cursor}.py`; contract
  `references/job-schema.md` and `schemas/job.schema.json` (`cli` claude|codex|cursor, `host`
  auto|native|wsl, `permissions` read-only|edit|full, `auth` subscription|api).
- **Per-CLI skills**: `claude-code-headless` (stream-json, `--session-id`, read-only = dontAsk +
  Read/Grep/Glob; subscription needs `authMethod` oauth), `codex-exec` (`codex exec
  --ignore-user-config --json … -`, `-s read-only|workspace-write`, ChatGPT guard), and
  `cursor-agent-headless` (not needed for the substitute demo).
- **Launch two background jobs**: write a Codex fix job and a Claude review job with fresh ids
  (`run2-close-20261018/ls/ls08-codex-fix.yaml` exists, id `ls08-codex-fix-close`; the Cursor
  review job is replaced by a `cli: claude`, `permissions: read-only` job). Run `doctor` on each,
  then from Claude Code Bash with `run_in_background: true`:
  `uv run --script .agents/skills/coding-cli-jobs/scripts/agentjob.py run codex.yaml claude.yaml
  --max-parallel 2 --allow-live` from the fixture root
  (`references/live-handoffs.md`, last paragraph). The private wrapper
  `ls/run_agentjob.py` loads named credentials from the canonical `.env` into the child only.
- **Read results**: `<fixture>/.tmp/agent-jobs/<id>/result.json` (written at `agentjob.py:524`),
  `status.json`, redacted `run.jsonl`; the retained worktree `.worktrees/<id>` on branch
  `agentjob/<id>`.
- Gotchas: existing ids, paths and branches refuse (`job-schema.md`); the fixture already holds
  `.worktrees/ls07-cursor-readonly-close{,2}` and their branches. WSL hosting is Codex-only; the
  Claude job must be `host: native`. `max_usd` refuses for non-Claude CLIs. Live execution needs
  `--allow-live`, which is a gate, not authority.

## 8. Known defects that will bite the finish runs

| Defect (ledger / finish §6.4) | Code reference | Workaround for the finish runs |
| --- | --- | --- |
| Reused lease keeps prior `outputs/` (K01) | `placement.py:270`; `adapters/claude/harness.py:374-382`; `policy.py:121-124` | `reuse: none` on every stage |
| Undecided approval auto-denies at 300 s and interrupts the turn (K12) | `settings.py:389`; `approvals.py:984-996` | Caller loop answers within 300 s; never let it die (foreground, guarded) |
| Approval reviewers default to `owner` | `settings.py:392` | Worker `MISSION_CONTROL_APPROVAL_REVIEWERS=["service:run2-s0-launcher"]`, disclosed |
| Caller loop decides only Claude `Bash` | `g1/caller_loop.py:70-76`; `adapters/codex/approvals.py:102-107` | Add `commandExecution`/`fileChange` classification (command text in `arguments.command`, `cwd`) before MR-02 |
| `missionctl wait` does not refresh tokens (K16) | `g1/mctl.py:101`; `interfaces/cli/wait.py:118-160` | Re-mint before each run; bound `--wait`; the loop re-invokes `mctl.py` per wake |
| Second `review_required` did not wake a fresh wait (cause unconfirmed) | `wait.py:97-115` (inbox reuse) | After any wake or timeout, list open human tasks directly (`caller_loop.py:63`) |
| Inject at a finished node stays queued | `application/execution/harness/inject.py:145-150` | Inject only while a stage is running; not a finish requirement (E6) |
| P5b residual timeout window | `lane_turns.py:3504-3522` | Record if seen; do not fix (E7) |
| P5c multi-output and Goal Loop output gaps (K02-K04) | `pack_service.py:1212-1238`; `lane_outputs.py:80-89` | One output per stage; Stage Graph only; instruction says "write exactly one file … as your very last action" |
| Inject text asking for prose breaks the JSON final answer | `pack_service.py:1223-1238` | Inject text must not ask for prose |
| Pre-create secret refusal classified `in_doubt` | binding `secret_refs` (`g1/config/launch-bindings.json` host profile) | Worker env must carry `MC_S0_OBSERVER_{JWT,URL,APPLICATION_ID}` (`g1/serve.py:111-114`) for every lane whose host profile names them, codex included |
| Config values not delivered to the lane runtime | `bootstrap/manifests.py:102-126` (compile only) | Name test files in the instruction; do not rely on `MC_FOCUSED_TESTS` in the environment |
| First HTTP call after idle fails client-side (WSL forwarding) | — | Retry with the same request id |
| Latent frozenset JSON dump | `application/programs/service.py:526-533` | Only on admission rejection; record if hit |
| Codex/Cursor M4 credentials absent from the API env (inference) | `bootstrap/prerequisites.py:42-49`; `g1/serve.py:81-84` | Add `OPENAI_API_KEY`/`CURSOR_API_KEY` to the API child env |
| `restart_g1.py` handles only A8/M4 and one manifest | `g1/restart_g1.py:207-229` | Generalize to merge per-lane bindings (a8, x4, x6, c9, m4 ×3) |
| No Cursor binding or auth profile in G1 | `g1/config/launch-bindings.json`, `auth-profiles.json` | Add per section 4.3 before W3 compile |
| Cloud attribute registration script uses the Operator API | `scripts/register_belllabs_search_attributes.py:23-38` | Attributes already present (MO-78); verify with `scripts/temporal_cloud/configure_search_attributes.py --plan` |
| Deployment Temporal block must match Cloud env | `adapters/temporal/client.py:90-97` | Edit `deployment.json` and the env together |
| Source change invalidates A8 | `g1/attest_claude_host.py:74-81` | Any E7 fix requires re-measure, re-derive and re-verify (`restart_g1.py`) |
| Lease paths exceed Windows MAX_PATH under MAIN | `g1/serve.py:99-102` | Keep every lease root on ext4 (`~/mc-leases`, `~/mc-close-workspaces`); set `CURSOR_LEASE_ROOT` too |
