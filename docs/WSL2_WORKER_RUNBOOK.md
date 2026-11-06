---
type: Operator Runbook
title: WSL2 worker runbook and host preflight for the local provider lanes
description: "How the Run 2 finish served Mission Control on a Windows host with a WSL2 worker for claude_agent_sdk, codex and cursor_local: host layout, configuration files, owner prerequisites per lane (A8, X4/X6, C9, M4) and their attestation, serving, preflight, Temporal Cloud re-pointing, memory management and known gotchas."
tags: [mission-control, operations, wsl, runbook]
---

# WSL2 worker runbook and host preflight

This is the procedure the Run 2 finish (2026-10-19/20) used to serve Mission Control from a
Windows host with its API and worker inside WSL2. With it, the `claude_agent_sdk` and `codex`
materialize-and-run cells passed on local Temporal and Temporal Cloud. Receipts are in
[the status ledger](specs/archive/materialization-observation-2026-10/runs/RUN-2-CLOSE-STATUS.md),
section "Finish". The operator scripts that ran it are private and outside the repository; this
page describes what they do so that an operator can reproduce it. Configuration models are in
the [operator guide](MISSION_CONTROL_LOCAL_API.md).

## 1. Host layout

- **Windows host.** The owner's sessions and the operator scripts run here. About 15 GB RAM.
- **WSL2 Ubuntu.** The VM is capped in `%USERPROFILE%\.wslconfig` (`memory=6GB`,
  `autoMemoryReclaim=gradual`). It runs:
  - the API, `uvicorn mission_control.bootstrap.api:create_app --factory`, on `127.0.0.1:18090`;
  - one worker, `python -m mission_control.bootstrap.worker`, with role `base` plus the lane
    queues listed in `MISSION_CONTROL_LANE_TASK_QUEUES`.

  Both run from a WSL venv that is an editable install of the checkout. Python 3.12, from the uv
  runtime.
- **Pinned native tools inside WSL:**
  - `claude-agent-sdk` 0.2.165 with bundled Claude Code 2.1.294;
  - `codex-cli 0.162.1` at an nvm Node path, named by `MISSION_CONTROL_CODEX_BINARY`. The
    launcher refuses any other version (`adapters/codex/protocol.py`, `PINNED_CODEX_CLI_VERSION`).
  - `cursor-sdk` 1.0.37, whose bridge brings its own Node `v24.5.0`
    (`cursor_sdk/_vendor/bridge/bin/node`). The WSL nvm Node does not count for C9.
- **Lease and workspace roots stay on ext4**, never under a Windows checkout, because paths
  exceed MAX_PATH. Set `MISSION_CONTROL_CLAUDE_LEASE_ROOT`, `MISSION_CONTROL_CODEX_LEASE_ROOT`,
  `CURSOR_LEASE_ROOT` and `DEEP_AGENT_SANDBOX_WORKSPACE_ROOT` explicitly.
- **Payloads.** `ARTIFACT_PAYLOAD_ROOT` is one ext4 directory shared by API and worker
  (same host; no split-host custody).

## 2. Configuration files (outside version control)

| File | Setting | Notes |
| --- | --- | --- |
| deployment | `MISSION_CONTROL_DEPLOYMENT_FILE` | Authentication block (issuer, audience, `public_jwks_file`, grants) and the per-application `temporal` block (`address`, `namespace`, queues ending `-coordinator-family-stagegraph`) |
| launch bindings | `MANIFEST_LAUNCH_BINDINGS_PATH` | `mc.manifest_launch_bindings.v2`; `providers.claude_agent_sdk`, `providers.codex`, `providers.cursor_local`. Each binding's `task_queue` must be a served lane queue |
| auth profiles | `MISSION_CONTROL_AUTH_PROFILES_PATH` | `mc.auth_profile.v1`; API-key routes `env:ANTHROPIC_API_KEY`, `env:OPENAI_API_KEY`, `env:CURSOR_API_KEY` |
| installation config | `MISSION_CONTROL_INSTALLATION_CONFIG_PATH` | `mc.installation_config.v1`, the values for `value_ref: config:<key>` (compile only) |
| owner probes | `MISSION_CONTROL_OWNER_PROBES_PATH` | `mc.owner_probes.v1`; re-read on every verify, but the variable is set only if the file exists when the API starts |
| preflight workspace root | `MISSION_CONTROL_PREFLIGHT_WORKSPACE_ROOT` | A local deployments/assets root outside version control (MO-68) |

The `cursor_local` binding needs a `repositories` entry keyed by the manifest's `repo.path`, with
`repo_url` equal to that absolute path and the `repo.ref` among `base_refs`. It also needs
`pins` equal to `REQUIRED_CURSOR_PINS`, a `lease_root`, and `hook_callback.listen` on
`127.0.0.1:<MISSION_CONTROL_HOOK_CALLBACK_PORT>`
(`application/authoring/cursor_launch.py`). Without `CURSOR_API_KEY` on both API and worker,
the lane is not registered (`adapters/temporal/deployment_composition.py`).

## 3. Secrets

The operator script reads DSNs and provider keys from the secret store into memory and hands
them to a small Linux exec shim **over stdin**, so they are never written to disk or printed.
The API needs each lane's credential **name** resolvable, because `broker_names` (M4) resolves
in the API process (`bootstrap/prerequisites.py`). The worker needs the keys and the observer
identity named by the host profile's `secret_refs`. If those `MC_S0_OBSERVER_*` names are
missing, the pre-create Secret Broker refusal is classified `in_doubt`.

## 4. Owner prerequisites per lane (host preflight)

| Lane | Codes | Probe operation | What the attestor observes |
| --- | --- | --- | --- |
| claude_agent_sdk | A8, M4 | `claude_native_host`, `broker_names` | Bundled CLI/SDK versions, worker import, identity equal to the preflight `why` digest |
| codex | X4, X6, M4 | `codex_native_auth`, `codex_native_cli`, `broker_names` | Pinned app-server with an isolated temporary `CODEX_HOME`, `cli_auth_credentials_store="ephemeral"`. `account/login/start` and `account/read` return `apiKey`, and `model/list` contains the selected model. No `auth.json`, thread or turn |
| cursor_local | C9, M4 | `cursor_native_host`, `broker_names` | Bridge Node `v24.5.0`, archive 1.0.0 (`@cursor/sdk` 1.0.37, protocol `sdk.v1`), SDK/bridge/loader closure digests, and a cleanup fixture (one disposable worktree under `lease_root`, removed, protected root unchanged) |

Procedure, for each lane:

1. **Measure** the host closure into the binding's `workspace` provision: the Python runtime,
   the venv, the `src` tree and a lane environment manifest. Any source change alters the
   package digest, and therefore the identity. Release the page cache per file while hashing
   (`posix_fadvise(DONTNEED)`), or the WSL VM can take more than 2 GB of host memory.
2. **Start the API**, then run `missionctl preflight <manifest>`. Each item carries the scoped
   id, the definition digest, and `why` ending in the native identity digest.
3. **Derive the identity** with the repository's own preflight classes:
   `BoundClaudePrerequisiteIdentity`, `BoundCodexPrerequisiteIdentity`,
   `BoundCursorPrerequisiteIdentity` (`application/prerequisites/preflight.py`). Check that its
   digest equals the `why` digest, then **observe** and write the
   `mc.{claude,codex,cursor}_native_*observation.v1` file.
4. **Write** one binding per scoped prerequisite into `owner-probes.json`, pinning `path` and
   `content_sha256`. M4 is `credentials: [{provider: environment, key: <NAME>}]`, and its
   evidence lives one hour (`max_age_seconds: 3600`).
5. **Restart the API**, then run `missionctl prereq verify <id> --definition-digest <d>` for
   every item, and preflight again. Ready means the host preflight passed.

Receipts from the finish: A8, M4, X4, X6, C9 and the three M4s were all verified, and preflight
was ready for `claude_agent_sdk`, `codex` and `cursor_local` on the WSL2 worker.

## 5. Caller tokens

Tokens are minted with `missionctl token mint` (MO-70). The operator key's public JWK goes into
the deployment's local `public_jwks_file`; the private key is mode 0600 and never committed. The
call names `--subject`, which is the grant **subject** (the actor id resolves from the grant),
`--tenant`, `--scope` once per granted permission, `--algorithm ES256` and
`--expires-in ≤ 3600`. The helper verifies the token before writing it to a new file. Re-mint
before each run: `missionctl wait` does not refresh tokens.

## 6. Temporal Cloud

Change the environment (`TEMPORAL_TARGET=cloud`, `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`,
`TEMPORAL_CLOUD_API_KEY`) **and** the deployment's `temporal.{address,namespace}` together; the
client refuses a mismatch (`adapters/temporal/client.py`). Use fresh private queue names in the
deployment, the bindings and `MISSION_CONTROL_LANE_TASK_QUEUES`. Check attributes read-only with
`python -m scripts.temporal_cloud.configure_search_attributes --plan <new-file>`; "additions {}"
means ready. Do not use `register_belllabs_search_attributes.py`, which is for self-hosted
servers. On Cloud, `missions:preflight` can exceed `missionctl`'s fixed 30 s client timeout, so
call the route with a longer client timeout.

## 7. Memory

- Run every heavy job in the foreground under a memory guard that refuses below about 1.5 GB
  available and stops only its own child tree.
- Drop the WSL page cache before live runs:
  `wsl -u root sh -c "sync; echo 1 > /proc/sys/vm/drop_caches"`.
- Stop Docker containers you do not need. Starting Docker Desktop can restart other stacks.
- Measured on this host:
  - one Claude or Codex session uses a few hundred MB in the VM;
  - the Cursor SDK bridge peaked at **199 MB RSS**, with WSL available never below 3.3 GB;
  - the Windows `cursor-agent` CLI, by contrast, committed about 3.6 GB.

## 8. Known gotchas

- Use `reuse: none` on stages: a reused lease re-collects earlier `outputs/` (K01).
- Answer provider-permission tasks within 300 s, because an undecided approval auto-denies.
  Configure `MISSION_CONTROL_APPROVAL_REVIEWERS` for the reviewing caller (the default is
  `owner`).
- Codex `workspace-write` with an allowlist network policy is **advisory**: network is switched
  on and the host list is not enforced (`application/environments/network.py`). Declare
  `network: none` when egress must be refused.
- Codex settles usage per turn, so a mission's token budget applies; give Codex stages a
  realistic budget. A Codex unit whose sub-agent threads lack usage provenance parks `in_doubt`
  (`codex_usage_requires_reconciliation`).
- The first HTTP call after idle can fail client-side through WSL forwarding; retry it with the
  same request id.
