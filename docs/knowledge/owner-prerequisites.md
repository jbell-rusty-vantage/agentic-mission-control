---
type: Concept
category: operations
title: Owner prerequisites
description: "The human-only steps a lane needs before a mission spawns - mc.owner_prerequisite.v1 records with paste-ready content generated from the binding's Environment Kit and network policy, verification methods, freshness and expiry, the per-installation store (migration 0038) and the standings a preflight reports (MO-20, proposed ADR-0047)."
tags: [mission-control, environments, owner-prerequisites, preflight, providers, implementation]
aliases: [owner steps, prerequisite record, preflight standing, attest]
questions:
  - Which human-only steps must I do before a lane can run?
  - How do I attest or verify a prerequisite?
  - Why does preflight say PREREQUISITES_UNMET?
updated: 2026-11-01
---

# Owner prerequisites

Some steps only the owner can take: a plan, a dashboard switch, a cloud environment created in
a web UI, an interactive login. Each is an **Owner Prerequisite** (`mc.owner_prerequisite.v1`,
`domain/prerequisites/owner_prerequisites.py`,
[ADR-0047](../adr/0047-owner-prerequisites-and-preflight-block-launch.md),
[SPEC-05](../specs/archive/materialization-observation-2026-10/SPEC-05-owner-prerequisites.md)). Preflight
and the `PREREQUISITES_UNMET` launch refusal (MO-21) and the setup wizard (MO-22) consume this; production
manifest services and run launchers compose the PostgreSQL store through the same guard.

`missionctl preflight FILE --json`, `POST /v1/applications/{app}/missions:preflight` and
the `mission_preflight` MCP tool return `mc.preflight.v1`: current definitions, assessments,
owner steps, generated blocks, degradations and per-role readiness. Unmet or expired items
return HTTP 422 / CLI exit 2. Launch returns `PREREQUISITES_UNMET` with that report before
provider sessions or subscriptions start. Selected account, repository and environment
identities scope evidence independently. Compilation/catalog blockers also keep preflight
not ready; it never invents a provider environment to render an owner checklist.

`missionctl setup <provider|lane> --manifest mission.yml --script setup.sh` generates a
reviewable Bash wizard using the repository's unmodified wizard helper library. Running it
opens provider portals, prints the exact steps and paste blocks, asks the owner to attest,
then requests server-owned verification. Without `--script`, setup runs interactively in a
terminal; `--json` returns the scoped plan. Credentials are entered only in provider UIs or
the broker, never captured by this wizard. Omit `--manifest` only for an account checklist;
that checklist does not establish readiness for a selected environment.

Owner tokens need `prerequisite.read`, `prerequisite.attest` and `prerequisite.verify` grants
(plus manifest read/catalog grants when a manifest is supplied). Ordinary launch grants do
not grant attestation. `missionctl prereq attest ID --definition-digest DIGEST [--value env_ID]`
records the authenticated owner; `prereq verify` accepts only the record's identity and digest. The server
invokes a trusted probe and persists its proof; an unavailable probe is `probe_unavailable`, never verified. The
wizard exits nonzero for skipped or failed steps and reruns preflight when generated for a manifest.

## Trusted probe configuration

The API composes `InstallationOwnerProbes` with the worker's Secret Broker and its restricted
runtime pool. Set `MISSION_CONTROL_OWNER_PROBES_PATH` to an operator-reviewed JSON file with
`schema_version: mc.owner_probes.v1` and `bindings`. Each binding pins `request_scope`,
`prerequisite_id` and `definition_digest` from the current setup report, plus an `operation`:

- `managed_agents_access` / `agents_api_access`: one `credentials` SecretRef, e.g.
  `{"provider":"environment","key":"ANTHROPIC_API_KEY"}`. A read-only agents-list request proves
  credential/API read access; it does not prove billing limits or every write/API permission.
- `github_readonly_repository` / `github_publication_repository`: one credential reference and
  exact `repository: owner/name`; read and push permissions must match the intended purpose.
- `broker_names`: explicit credential references; checks resolution without returning values.
- `claude_native_host`: pinned `mc.claude_native_host_observation.v1` proves A8's exact SDK/CLI,
  host/workspace/profile/options and fresh public-file identity without commands or credential reads.
  API delivery configuration only: no key validity, entitlement, inference or subscription proof; M4 stays separate.
- `codex_native_auth` / `codex_native_cli` (X4, X6) and `cursor_native_host` (C9): pinned native observation
  verifiers (`verify_native_codex`, `verify_native_cursor`); `managed_mcp_oauth`: `validate_managed_oauth` over
  the Managed Agents client for an MCP OAuth connection (`adapters/prerequisites/probes.py:72,88,102`).
- `signed_webhook`, `signal_receipt`, `exercised_environment`: `run_key` and `binding_digest`
  of an actual probe. Checks current-generation preparation and correlated durable delivery.

`max_age_seconds` defaults to one day (60 seconds to 30 days allowed). Receipt evidence expires
from its original observation, so requesting verification again cannot renew an old receipt.
Configuration is re-read for each check; changed definitions, another scope, stale preparations
and uncomposed probes fail closed. Provider errors expose an error category, never response
bodies or credentials. Public attestations cannot substitute for a declared probe method.

Every production preflight checks the current installed release attestation through the trusted
Application Binding. Chain relays use the same guard. Trusted technical launcher composition
must supply `application_binding`; an absent binding blocks launch. A knowledge-repository alias
includes its resolved installation repository in the evidence identity, so repointing the alias
requires fresh evidence. Generated cloud-environment wizard steps capture a public environment
ID and submit it with the current definition digest.

## The record

| Field | Meaning |
| --- | --- |
| `id`, `provider`, `scope` | e.g. `claude_cloud.environment.envkit-python-uv-node-1`; scope is account, org, repo, environment, host or user |
| `blocks` | the lane profiles and features (`launch`, `observation`) an unmet item blocks |
| `steps` | text, or `{paste, content_ref}` naming one generated item |
| `verify` | `api_probe`, `probe_mission`, `file_check` (strongest first) or `attestation`, with the probe it runs |
| `freshness` | `revalidate_after`, `expires_after`, `warn_before` (7 days by default), `on_change_of` (`kit_digest`, `policy_digest`) |
| `generated_from`, `generated` | the binding's kit pin and network policy digest, and each item's ref, media type, exact text and sha256 |

A step pastes only generated content, and every generated item is pasted by a step. The
record's `digest` is the definition's identity; evidence cites it.

## Generated content

`generate_owner_prerequisites(profile, GenerationInputs)` (`application/prerequisites/generators.py`)
renders from the lane's `mc.environment_binding.v1` (`setup_pin`, `network`, `secret_refs`), the
kit's catalog definition and its base-layer files (each checked against the kit's file manifest)
and the provider environment strategy:

| Lane | Items |
| --- | --- |
| `cursor_cloud` | under `generate`: `environment.json` with `install` (base layer), `start` (services and the Bootstrap Entrypoint) and the projected `egressMode`/`egressAllowlist`; Build Secret names for setup-phase secrets (C6); the broker store |
| `claude_cloud` | unless `bind`: network level, `domains.txt`, `setup.sh`, `env.template` (A4); `claude auth login`, 30-day expiry (A6) |
| `codex_cloud` | unless `bind`: `install.sh`, `start-skill.md`, `env.template`, agent internet access and `domains.txt` (X3); `codex login`, revalidated every 8 days (X4) |
| `claude_managed`, `codex_agents` | the webhook URL on the Signal Ingress host, `/v1/ingress/provider/{anthropic,openai}` (MA2, OA2); the broker store |

The base layer is the kit's system packages plus its base install script; network fields are
`project_network_policy`'s settings for the lane. Templates name variables only (`NAME=`), minted credentials are
left out, and the same inputs always render the same digests. `screen_generated_content` runs the broker's commit
scan over every item and raises `SecretInGeneratedContent` for a minted token or a supplied secret value.

## The store and its evidence

`OwnerPrerequisiteRecord` holds the current definition, its `definition_digest`, a state and the evidence that set
it. `attestation` makes it `attested`; the other methods make it `verified`. `OwnerPrerequisiteService`
(`application/prerequisites/service.py`): `register_for_binding` generates, stores and assesses against the binding
(a changed definition replaces the stored one and keeps its evidence, which now proves an older definition);
`attest` (an identifier such as `env_...`, never a secret) and `verify` (a probe's evidence ref) record evidence for
the stored definition or the `definition_digest` the owner followed, refused when it changed (a credential's expiry
is the earlier of its own and `recorded_at + expires_after`); `assess` returns one Prerequisite Standing per record.
`PostgresOwnerPrerequisiteRepository` (`adapters/postgres/prerequisites/`) writes migration 0038's
`owner_prerequisite`: one row per prerequisite per installation scope, merges under the row lock, versions
advancing by one.

## Standings

| Standing | When | Blocks |
| --- | --- | --- |
| `unmet` | no evidence | yes |
| `drifted` | the evidence proves another definition, or the binding's kit or policy differs from `generated_from` for an input in `on_change_of` | yes |
| `expired` | now is at or after `expires_at` | yes |
| `expiring` | within `warn_before` of `expires_at` | no |
| `stale` | `revalidate_after` has passed since the evidence | no |
| `met` | none of the above | no |

## Proof

`tests/unit/prerequisites/test_owner_prerequisites.py` (record rules and every standing), `test_generators.py`
(each lane's items equal what the binding projects; same binding, same digests; refusals for a foreign kit or file
and for secret values), `test_service.py` and `tests/integration/postgres/test_owner_prerequisites.py` (real
PostgreSQL: register, attest, verify, the 30-day login flagged expiring then expired, drift after a kit change,
grants, RLS, checks and guard).

Built / specified / goal: definitions, generators, probes, standings, wizard and the preflight guard are
implemented and tested; no paid probe was run and no hosted-lane prerequisite is attested live.

## Citations

- `src/mission_control/domain/prerequisites/`, `src/mission_control/application/prerequisites/`,
  `src/mission_control/adapters/postgres/prerequisites/`,
  `packages/mission-control-db-contract/releases/1.4.1/component/migrations/0038_owner_prerequisites.sql`.
- History: [SPEC-05](../specs/archive/materialization-observation-2026-10/SPEC-05-owner-prerequisites.md),
  [SPEC-06](../specs/archive/materialization-observation-2026-10/SPEC-06-hosted-api-lanes.md) section 10,
  research notes under `docs/specs/archive/materialization-observation-2026-10/research/` (claude-code, codex, cursor).
