---
type: Concept
category: operations
title: Secret Broker
description: "How secrets reach a lane - references resolved only from installation sources (worker environment, secret-store file, keyring, Supabase Vault, provider-held names), per-run minted credentials stored as digests, one delivery channel per lane, exact-match redaction of frames, logs and receipts, and the pre-commit scan of Mission Control's commits (MO-11, proposed ADR-0043)."
tags: [mission-control, environments, secrets, security, implementation]
aliases: [secret refs, redaction, minted credentials, secret delivery]
questions:
  - How does a secret reach a lane and what gets redacted?
  - Which credential does a signal or knowledge call use?
  - Why must a secret never be committed?
updated: 2026-11-01
---

# Secret Broker

A binding names secrets; it never holds one. The Secret Broker
(`application/secrets/`, [ADR-0043](../adr/0043-secret-broker-per-lane-delivery-minted-signal-credentials-never-commit-secrets.md),
[SPEC-01 §4](../specs/archive/materialization-observation-2026-10/SPEC-01-environments.md)) resolves the
references, delivers each value through one lane channel and makes sure the value comes back out
of nothing Mission Control writes. The worker composition builds one broker per process
(`compose_secret_broker` in `adapters/temporal/deployment_composition.py`); it is the deployment's
`SecretResolutionPort` and replaces the worker-environment resolver.

## References and declarations

| Reference | Served by |
| --- | --- |
| `environment:<NAME>` | the worker environment (the deployment's own credentials) |
| `secret:<path>`, `vault:<path>` | the installation's store (`MISSION_CONTROL_SECRET_STORE`) |
| `mint:<purpose>` | the `CredentialMinter`, per run |

A binding's `EnvironmentBinding.secret_refs` carries declarations as `NAME[?]=<ref>[;phase,...]`:
`?` marks an optional secret, phases are `setup` (the mission layer) and/or `agent` (the
session). `declarations()` parses them (`application/secrets/references.py`); a variable is
declared once.

## Sources

`MISSION_CONTROL_SECRET_STORE` selects the store: `none` (the default: a store reference is
unavailable), `file` (`MISSION_CONTROL_SECRET_STORE_PATH`, a JSON object of `"path": "value"`
outside every git repository, re-read on each lookup), `keyring` (entries under
`MISSION_CONTROL_SECRET_KEYRING_SERVICE`) or `supabase_vault` (`vault.decrypted_secrets` by name
over `MISSION_CONTROL_SECRET_VAULT_DSN`). Paths in `MISSION_CONTROL_PROVIDER_HELD_SECRETS` are
never read; they resolve to names that delivery verifies in the provider's store. The broker never
falls back to the worker environment, and a required declaration without a value fails.

## Minted credentials

`mint:signal_token` issues an `mct_` token bound to the attempt's request scope, run, unit
(activation) and generation, with the `signal:write` scope, expiring after 24 hours or at the
mission deadline. Only `sha256:` of the token is stored (`MintedCredentialStore`). `verify`
rejects it as unknown, expired, revoked, wrong purpose, wrong binding or insufficient scope;
`revoke_superseded` (a new generation) and `revoke_run` (a terminal run) revoke. New purposes are
one `MINT_PURPOSES` entry. The process-local store serves tests and single-process installations;
the shared store is MO-40's `ingress_credential`: with a runtime pool the worker composes `ScopedSecretMinter`
(MO-41; `adapters/temporal/deployment_composition.py:959-961,986`), and standalone callers without the pool
refuse a `mint:` declaration. Knowledge-service credentials are a separate minter: the K01 gateway signs
single-use Ed25519 compact JWS per transmission with `Ed25519CredentialMinter`
(`bootstrap/composition.py:695`, [knowledge services](knowledge-services.md)).

## Delivery per lane

| Channel | Lanes | How |
| --- | --- | --- |
| `process_environment` | `cursor_local`, `claude_agent_sdk`, `codex` | `ProcessSecretDelivery` resolves the binding's agent-phase declarations into `extra` values of the MO-04 child environment (Claude and Codex compose it today; a `cursor_local` binding carries no `EnvironmentBinding` yet, MO-10) |
| `cursor_launch_env_vars` | `cursor_cloud` | `env_vars_ref` resolves through the broker once per process, before the branch is published; Cursor's documented launch limits are checked before the create (`adapters/cursor/secrets.launch_env_vars`) |
| `cursor_environment_secret`, `cursor_team_secret` | `cursor_cloud` | `CursorSecretsClient` puts `runtime_secret` values; listings verify provider-held names |
| `provider_vault` | `claude_managed`, `codex_agents` | `ProviderVaultStore` creates `environment_variable` credentials limited to allowed hosts |

`deliver_to_store` verifies provider-held names before writing, and every channel records
`SecretUse` (name, channel, target, held) for the Materialization Receipt. `claude_cloud` and
`codex_cloud` have no per-run channel (owner prerequisites).

## Redaction and the commit scan

Every value the broker resolves or mints joins its `SecretValueRegistry`:

- `LaneTurnService` passes the registry's values to each `FrameWriter` (exact match, then the
  existing patterns), so stored frames and the transcripts rendered from them never hold one;
  `mct_` tokens are also redacted by shape;
- `install_log_redaction` wraps the log record factory once per process: every record's message,
  arguments and traceback are redacted, whatever logger or handler emits it;
- `redact_receipt` is the redactor a receipt writer applies before persisting. No persisted
  receipt calls it yet: the Materialization Receipt that records `SecretUse` is not built.

`GitBranchPublisher.publish` and `commit_files` call `scan_commit` before writing: a path, content
or message carrying a value resolved for that run (on `cursor_cloud`, its launch `envVars`) or
any minted token raises `SecretInCommit` naming the path, and nothing reaches the remote. Values
under six characters are not matched. Redaction is process-wide (a log record names no run), so
every variable `env_vars_ref` lists is treated as a secret; non-secret settings belong in the
kit's variables, which never pass through the broker.

## Not yet resolved

An auth profile's `credential_ref` of `secret:<path>` or `keyring:<entry>` is accepted by the
profile schema but not resolved by the broker. Admission fails closed: it admits such a profile
only when the route's own variable is already present, and the child environment copies only an
`env:` credential, so the provider child never receives one from elsewhere. Resolving them needs
provider-auth detection and admission to consult the broker and a route-to-variable table
(follow-up recorded in the MO-11 handoff).

## Proof

- `tests/unit/secrets/test_sentinel_secret.py`: a sentinel resolved for a `cursor_cloud` turn
  appears only in the create's `envVars`, never in a commit, frame, transcript, log, receipt or
  binding.
- `tests/unit/secrets/test_minting.py`: binding, expiry, deadline, revocation, wrong-run use.
- `tests/unit/harness/test_local_lane_child_environments.py`: broker values reach the Claude CLI
  and `codex app-server` with the allowlist and nothing else.
- `tests/integration/postgres/test_secret_broker_vault_source.py`: the composed broker reads a
  Vault-shaped view on real PostgreSQL; `test_cursor_cloud_composition.py` uses the composed
  broker.

## Citations

- `src/mission_control/application/secrets/`, `src/mission_control/adapters/secrets/`,
  `src/mission_control/adapters/cursor/secrets.py`, `src/mission_control/adapters/cursor/scm.py`.
- [SPEC-01](../specs/archive/materialization-observation-2026-10/SPEC-01-environments.md) sections 3, 4
  and 10; [research/cursor.md](../specs/archive/materialization-observation-2026-10/research/cursor.md)
  section 2.
