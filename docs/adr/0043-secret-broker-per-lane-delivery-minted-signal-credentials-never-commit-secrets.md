---
type: Decision Record
title: "Secret Broker: installation sources, per-lane delivery, minted signal credentials and never committing a secret"
description: "Accepted for the materialization-observation sprint (SPEC-01 section 4, MO-11): one application port resolves secret references from installation-configured sources only (the worker environment, a secret-store file or the owner's keyring locally, Supabase Vault when hosted, provider-held names verified in place), mints per-run credentials bound to scope, run, unit and generation with only their digest stored, delivers each value through one lane channel and records names only; every value it resolves is redacted by exact match from frames, logs and receipts, and Mission Control's commits to mission branches are scanned for them first."
tags: [mission-control, adr, accepted, environments, secrets, security]
status: accepted
source: docs/specs/archive/materialization-observation-2026-10/SPEC-01-environments.md (sections 3-4 and 10); docs/specs/archive/materialization-observation-2026-10/SPEC-04-watchers-and-callbacks.md (run_token tier); docs/specs/archive/materialization-observation-2026-10/SPEC-10-ingress-on-vercel.md (ingress_credential, token lifecycle); docs/specs/archive/materialization-observation-2026-10/research/cursor.md (section 2); docs/specs/archive/materialization-observation-2026-10/research/provider-smoke-2026-10.md (sections 2.1 and 3.1); DECISIONS Proposed ADRs 0043; MO-11; MO-04; MO-06; ADR-0034
---

# Secret Broker: per-lane delivery, minted signal credentials, never commit secrets

**Status: accepted 2026-11-01; implemented by the materialization-observation Run 2 finish (`b95ae4aa` completion summary; `152a3dcb` finish records, 2026-10-20) and the 1.4 database release (`b434e573`).** Previously proposed. 

Before this decision a secret reached a provider in whatever way each lane happened to use: the
worker's environment (MO-04 narrowed it to an allowlist), a binding's `env_vars_ref` resolved from
that same environment (MO-06), and `secret:`/`keyring:` references that admission accepted but
nothing resolved. Nothing issued a per-run credential, and nothing stopped a resolved value from
reaching a commit, a frame or a log line.

We add one port, the **Secret Broker** (`application/secrets/`), with adapters per source and per
delivery channel (`adapters/secrets/`, `adapters/cursor/secrets.py`); the worker composition
(`compose_secret_broker`) builds one per process and every lane uses it.

- **References, never values.** `environment:<NAME>` reads the worker environment (the
  deployment's own credentials, as before). `secret:<path>` (the manifest spelling) and
  `vault:<path>` (the `SecretRef` spelling) read the installation's store. `mint:<purpose>` issues
  a per-run credential. A binding carries each declaration as `NAME[?]=<ref>[;phase,...]`
  (`?` optional, phases `setup` and/or `agent`), so the compiled program, the binding and the
  receipt hold names and references only. MO-10 compiles the manifest's `environment.secrets`
  into these entries.
- **Sources are installation-configured** (`MISSION_CONTROL_SECRET_STORE`): `none`, `file` (a JSON
  object in a file outside every git working tree), `keyring` (the owner's OS keyring under a
  service name) or `supabase_vault` (`vault.decrypted_secrets` read by name over its own DSN).
  Store paths listed in `MISSION_CONTROL_PROVIDER_HELD_SECRETS` are never read: their values
  already live in the provider's store, and delivery only verifies the name exists there. A store
  reference with no store composed is unavailable; the broker never falls back to the worker
  environment, and a required declaration without a value fails the resolution.
- **Minting.** `mint:signal_token` issues a random `mct_` token bound to one request scope, run,
  unit and generation, carrying the `signal:write` scope only, expiring after 24 hours or at the
  mission deadline, whichever is first. Only its SHA-256 digest is stored. Verification rejects an
  unknown, expired or revoked token, another purpose, a missing scope and any other scope, run,
  unit or generation. A new generation revokes the unit's earlier tokens; a terminal run revokes
  all of its tokens. The purposes are one table (`MINT_PURPOSES`), so the operator launch
  credential (`mission_request`, MO-40) and the Model Gateway token (`model_gateway`, HL-03) are
  one entry each. The store is a port: the shared PostgreSQL store is MO-40's
  `ingress_credential` (migration 0035), which the edge reads; until it is composed the worker
  refuses a `mint:` declaration rather than issuing a token no verifier can see.
- **Delivery per lane**, each recorded as a `SecretUse` (name, channel, target, held), never a
  value:
  - `process_environment` (`cursor_local`, `claude_agent_sdk`, `codex`): the binding's
    agent-phase declarations become `extra` values of the MO-04 allowlisted child environment,
    so a child receives the allowlist plus exactly these. A provider-held secret cannot reach a
    local process and is refused.
  - `cursor_launch_env_vars` (`cursor_cloud`): the binding's `env_vars_ref` resolves through the
    broker once per process, before the run branch is published, and is checked against Cursor's
    launch limits before the create.
  - provider stores: Cursor environment and team secrets (`PUT .../secrets/{name}` as
    `runtime_secret`; the listings verify provider-held names), and Anthropic and OpenAI vault
    `environment_variable` credentials limited to their allowed hosts (the request shape HL-23
    sent live). An organization API key is never delivered into a sandbox, an image or a pack
    file: hosted sessions see a provider placeholder substituted only towards allowed hosts.
  - `claude_cloud` and `codex_cloud` have no per-run channel; their secrets stay owner
    prerequisites (SPEC-05).
- **Redaction by exact match.** Every value the broker resolves or mints joins the process's
  `SecretValueRegistry`. `LaneTurnService` adds the registry to each `FrameWriter`, so frames (and
  the transcripts rendered from them) never store a delivered value; one wrapped log record
  factory redacts every log record's message, arguments and traceback; receipt writers pass
  receipts through `redact_receipt`. Redaction is process-wide, because a log record names no
  run, so every variable a binding's `env_vars_ref` lists is treated as a secret. Values shorter than six characters are not matched. Minted tokens are also
  redacted by their `mct_` shape, which covers a process that never saw the value. The existing
  pattern-based redaction still applies.
- **Never commit a secret.** Every Mission Control commit to a mission branch
  (`GitBranchPublisher.publish` and `commit_files`) scans paths, contents and the message for the
  run's resolved values and for minted tokens first; a match refuses the commit before anything is
  written or pushed, and the error names the path, never the value.

We rejected resolving secrets inside each lane (each lane would choose its own fallback, which is
how the worker environment leaked), a broker that falls back to the worker environment when no
store is configured (a missing binding must not become an ambient lookup), storing minted tokens
reversibly (the edge needs to verify, never to read), and pattern-only redaction (a random
provider key has no recognisable shape).

## Consequences

- `compose_cursor_cloud` takes the broker (`SecretBroker`), not any `SecretResolutionPort`, so
  every launch value joins the redaction registry, and the MO-06 seam is closed: `env_vars_ref`
  variables come from the broker's sources. The `cursor_cloud` commit scan uses the run's own
  launch values only, so one run's values never refuse another run's commit.
  `EnvironmentSecretResolver` stays for the subscription relay and tests;
  `SecretReferenceUnavailable` is now a `SecretUnavailable`.
- `keyring` becomes a direct dependency (it was already resolved through `fastmcp`).
- A worker resolves a run's launch `envVars` again when it reattaches after a lost process, so
  its redaction and commit scan know them.
- Not yet delivered: broker-declared secrets and minted tokens on `cursor_local` and
  `cursor_cloud` (the Cursor bindings declare no `EnvironmentBinding` and `env_vars_ref` cannot
  name a `mint:` reference; MO-10/MO-40), the MCP
  servers' own `secret_environment` references (they are still copied by name from the worker,
  MO-04), syncing kit-level secrets into a Cursor environment (MO-13) and vault delivery for the
  hosted lanes (HL-21). Each uses the channels above.
- Not yet resolved: an auth profile's `credential_ref` of `secret:<path>` or `keyring:<entry>`.
  It fails closed (admission requires the route's variable to be present, and only an `env:`
  credential reaches a child environment); resolving it through the broker needs provider-auth
  detection, admission and a route-to-variable table. No persisted receipt calls
  `redact_receipt` or records `SecretUse` yet: the Materialization Receipt is not built, and the
  mission deadline is not yet passed to process delivery.
- The Supabase Vault source is proven against a disposable PostgreSQL view of Vault's documented
  shape, not against a live Supabase project; the Cursor secrets listings' fields beyond `name`
  and the OpenAI vault listing's fields are UNVERIFIED.
