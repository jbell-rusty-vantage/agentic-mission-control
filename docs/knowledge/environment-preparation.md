---
type: Concept
category: operations
title: Environment Kits, the mission layer and readiness records
description: "Environment Kits, provider provisioning, guarded mission setup, persisted readiness and per-lane discovery evidence."
tags: [mission-control, environments, lanes, readiness, persistence, implementation]
aliases: [readiness level, mission layer, kit provisioning, environment preparation]
questions:
  - Why was this session refused as not ready?
  - What are the six readiness levels?
  - How does the mission layer prepare a session?
updated: 2026-11-01
---

# Environment Kits, the mission layer and readiness records

The environment a manifest declares ([environments](environments.md)) names a kit pin; this
concept is what a lane does with it before agent work, and how far each attempt proves its
environment ready.

## Environment Kits and the mission layer

An Environment Kit (`environment_kit`, [ADR-0042](../adr/0042-environment-kits-and-two-layer-base-mission-setup-with-one-bootstrap-entrypoint.md))
is a custody bundle whose `kit.json` is `mc.environment_kit.v1` (`domain/authoring/environment_kits.py`):
toolchains from a closed probe table, system packages, a base layer (install script, services),
a mission layer (steps with `exists('<path>')` conditions, health checks, `timeout_s`) and
`requires`. Its `EnvironmentKitDefinition` derives host support and secret names from `kit.json`;
the asset row is a `profile`, so no SQL changed. Host support is `supported` on the local
lanes (`cursor_local`, `claude_agent_sdk`, `codex`); the hosted profiles are `unqualified`, with
overlay `base_layer: mission_control | owner`.

| Step | Readiness |
| --- | --- |
| The binding pins the kit (`setup_pin`) | `declared` |
| `.mission/setup/run` and `kit.json` rendered, deterministic, names only | `rendered` |
| Written into the leased worktree, earlier receipt removed | `delivered` |
| The script ran; `.mission/setup/receipt.json` is for this pin and every step and health check passed | `prepared` |

`MissionLayerService` (`application/environments/mission_layer.py`) does this through the
`BashMissionSetupRunner` (`adapters/workspaces/mission_setup.py`) with the allowlisted child
environment plus `setup`-phase secrets; output is discarded. The Claude and Codex harnesses call
`prepare_lane_environment` in `prepare`, and `cursor_local` calls `run_mission_layer` with the
bridge's allowlist (its binding's `setup_pin`, no broker secrets); all refuse anything below
`prepared` (`ENVIRONMENT_NOT_PREPARED`), and the prepared session records `setup_digest` and
`setup_receipt_digest`. `entrypoint_command` renders the guarded start line hosted base layers
run. Starter kits live in `envkits/` and ship as `mc.app.<app>.environment-kits@1.0.0`
(`packages/mission-control-db-contract/seeds/environment_kits.py`);
`envkit.mission-control-dev` adopts the owned `.cursor/` environment byte for byte.

## Provider environments on cursor_cloud

The manifest's `provider_environment` is sealed on the cloud options
(`CursorProviderEnvironment`: strategy, `ref`, kit pin, secret declarations). In `prepare`,
before anything is published, `CursorEnvironmentProvisioner` (`adapters/cursor/environments.py`)
reads `.cursor/environment.json` on the default branch (the one Cursor's Builds use, whatever
the run's base ref), which overrides every saved environment. `check_environment_file`
(`application/environments/provider_environments.py`) calls it `mc_owned` (its `name` is this
kit's marker `mc:<kit id>@<version>` and its canonical digest equals the kit's rendering),
`foreign` (refused, `PROVIDER_ENVIRONMENT_REFUSED`, unless `bind` names the file; the marker
over stale content is foreign) or `absent`.

| Strategy | Committed file absent | mc-owned file |
| --- | --- | --- |
| `sync` | `ProviderEnvironmentService` creates or reuses `mc-<kit id>-<digest8>` for the target repository | the file is the base layer; nothing is synced |
| `bind` | the named environment is read (digest, version); nothing is written | refused: bind the file instead |
| `generate` | the owner applies generated content | the file is used |

The name's digest covers the rendered `environmentJson` (`render_environment_json`: kit marker
as `name`, the kit's base install script from custody under `bash -c`, the entrypoint as
`start`, the projected egress, `agentCanUpdateSnapshot: false`) and the sorted target
repositories, so one kit, policy and repository share one environment and another repository
gets its own. A taken name (`409`) is read back from the version history: a matching digest is
reused with no write, a dashboard edit is replaced, and a read-back that differs, or one that
no longer covers the target repository, is `PROVIDER_ENVIRONMENT_DRIFT`. Secrets resolve through the Secret Broker before any write and
are written by name (`runtime_secret`); a reused environment receives only missing names, and
`mint:` credentials never enter it. The run branch carries `.mission/setup/run`. The create
never names the environment, because Cursor refuses `env.name` with `repos` and the agent must
start on the run branch. Any refusal on the way (provider, missing secret, kit bytes) is a
`LaneProjectionError`. The handle records `provider_environment*` details (secret names
written and omitted included); the record gains the `mission_layer` and `base_layer`
deliveries (`provider_environment`, or `repository_file` for a committed file) and lists the
declared secrets on `cursor_environment_secret` only when a synced environment holds them,
otherwise as `owner_prerequisite`.

## Preparation records and the readiness gate

`mc.environment_preparation.v1` (`domain/execution/environment_preparation.py`, SPEC-01 §8) is
one record per harness execution generation. Its Readiness Level climbs `declared` (the sealed
binding) → `rendered` (projection digests: the observed configuration digest) → `delivered`
(written to the leased worktree or committed on the cloud branch) → `prepared` (a preparation
receipt) → `discovered` (a Discovery Proof, below) → `exercised` (a hook frame). It never regresses, is contiguous up to `prepared` and carries the delivery channels,
secret names with their Secret Broker channels, the receipt digest, omissions and degradations.

`LaneTurnService` hands each `PreparedSession` to `EnvironmentPreparationService.admit_start`
before `start` (`application/environments/preparation.py`). A worker-hosted prepare is
`prepared` by its prepare receipt when the binding declares no kit, and by the passing
`.mission/setup/receipt.json` its kit's mission layer wrote (`setup_receipt_digest`) when it
does; without that receipt it stops at `delivered`. A cloud lane is prepared only by a receipt
signal, so it stops at `delivered` with the omission recorded. Deep Agents is not on this gate: its nodes do not pass through `LaneTurnService` and no `deep_agents` preparation receipt exists (`adapters/deep_agents` has no `admit_start`); its network grant is in [environments](environments.md). `LaunchReadinessPolicy`
requires `prepared` on worker-hosted lanes and `delivered` on cloud lanes. It decides on what
this prepare proved, not on the stored record. Below the minimum the session never starts and
the unit settles `failed(environment_not_ready)`. A generation prepared again (a worker
restarted before its native session was recorded) keeps the receipt recorded first. A
preparation the stored record contradicts settles the same way instead of failing every
retry. A Cursor binding carries no environment binding, so its record declares the lane alone
and says so, unless its cloud options carry a provider environment (kit, secrets, policy).

The record's `declaration_digest` covers the kit pin, secret declarations, network policy and lane
of the sealed binding. `environment_readiness` names the minimum each node role needs and a
declaration digest (`application/environments/requirements.py`). The start receipt reads the run's
sealed launch templates (`declaration_source: sealed_binding`), so every record carries its digest
and is found by `(run_key, declaration_digest)`. The Validation Report is compiled before any
deployment binding is applied and cites what the manifest declares (`declaration_source:
manifest`). A host binding that adds a kit, secret or network policy (the multi-provider example
sets a network policy on every local host profile) gives the records another digest, and so does a
declared `network`, which resolves into exact hosts only at launch ([network
policy](environments.md#network-policy)). Records persist in
`mission_control.environment_preparation` (migration 0037, release 1.4.1) through
`PostgresEnvironmentPreparationRepository`, merged under the row lock. A guard refuses a regressed
level, a changed receipt or identity, an update back in time and deletes.

## Discovery Proof

A written file is delivered, not loaded (gap G14). `discovered` needs a **Discovery Proof**, a
`mc.discovery_report.v1` (`domain/execution/discovery.py`) gathered by mechanism, never by
asking the model. Each prepare records a `DiscoveryExpectation` on its `PreparedSession` and so
on the record (`discovery`): the mission items of the layering receipt the lane's mechanism
can name, plus, for a mechanism that reads files, the digests of the overlay and hook config as
placed (`application/environments/discovery.py`). A report proves it when it names every item
and reads every digest; it may name more (repository, user, bundled cognition).

| Lane | Mechanism | Reports |
| --- | --- | --- |
| `claude_agent_sdk` | `system/init`, emitted as a `materialization.discovered` frame | skills, agents, connected MCP servers |
| `codex` | app-server `skills/list`, `hooks/list`, `config/read` after `thread/start` | skills, trusted hook events, MCP servers |
| `cursor_local` | SDK `get_agent` read-back: the agent's project root is the lease | skills and overlay/hook digests there |
| `cursor_cloud` | Telemetry Hook Pack's `materialization.observed` signal (in the VM) | skill listing and overlay/hook digests |
| `claude_managed`, `codex_agents` | API read-back of the agent (and template) a session runs | pinned skills, MCP servers, pack digest |

Read-back lanes implement `DiscoveringLane.discover`; `lane.turn` calls it once the new native
session exists and persists the report as a status frame. `EnvironmentPreparationService.discovered`
compares the report with the recorded expectation (`proof_gaps`) and changes nothing on a gap.
On a cloud lane with no mission layer, a provider-side proof (`materialization_signal`,
`api_readback`) is also the preparation receipt, so it lifts `prepared` and `discovered`
together; a declared mission layer still waits for its receipt signal. `codex_cloud` proves
`delivered` only. The `materialization.observed` signal reaches the service through the
IngressDrainer (MO-75), and the hosted harnesses (HL-08, HL-12) call the read-backs.

## Citations

- History: [SPEC-01](../specs/archive/materialization-observation-2026-10/SPEC-01-environments.md) §1, §2, §7, §8.
- ADRs: [0042](../adr/0042-environment-kits-and-two-layer-base-mission-setup-with-one-bootstrap-entrypoint.md).
- Code: [kit manifest and mission layer](../../src/mission_control/domain/authoring/environment_kits.py), [kit catalog](../../src/mission_control/application/environments/kits.py), [mission layer service](../../src/mission_control/application/environments/mission_layer.py), [provider environments](../../src/mission_control/application/environments/provider_environments.py), [Cursor environments](../../src/mission_control/adapters/cursor/environments.py), [kit seeds](../../packages/mission-control-db-contract/seeds/environment_kits.py), [preparation record](../../src/mission_control/domain/execution/environment_preparation.py), [preparation gate](../../src/mission_control/application/environments/preparation.py), [readiness requirements](../../src/mission_control/application/environments/requirements.py), [Discovery Proof](../../src/mission_control/domain/execution/discovery.py), [per-lane mechanisms](../../src/mission_control/application/environments/discovery.py), [repository](../../src/mission_control/adapters/postgres/environments/preparation_repository.py), [migration 0037](../../packages/mission-control-db-contract/component/migrations/0037_environment_preparation.sql).
- Tests: [kits](../../tests/unit/capability/test_environment_kits.py), [mission layer](../../tests/unit/workspaces/test_mission_layer.py), [Cursor environments](../../tests/unit/cursor/test_cloud_environments.py), [cloud lane](../../tests/unit/cursor/test_cloud_provider_environment.py), [sync on PostgreSQL](../../tests/integration/postgres/test_cursor_cloud_environment_sync.py), [kits on PostgreSQL](../../tests/integration/postgres/test_environment_kits_postgres.py), [readiness ladder](../../tests/unit/agentic_components/test_environment_preparation.py), [lane gate](../../tests/unit/harness/test_lane_turn_environment_readiness.py), [Discovery Proof](../../tests/unit/agentic_components/test_discovery_proof.py), [recorded Codex discovery](../../tests/fixtures/projections/discovery/codex.recorded.json), [PostgreSQL](../../tests/integration/postgres/test_environment_preparation.py), [Temporal](../../tests/integration/temporal/test_environment_readiness_gate.py).
