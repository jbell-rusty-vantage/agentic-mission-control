---
type: Concept
category: operations
title: Mission environments and materialization inputs
description: "The mission/v2 environment additions of materialization SPEC-01 (Environment Kit pin, variables, secrets, network, git and provider environment strategy), their lane and no-widening rules, the offline compile check of a kit's requirements, how they populate mc.environment_binding.v1, the per-profile repository requirement (MO-10), and how the network policy resolves to exact hosts and projects per lane with an honest enforcement record (MO-15)."
tags: [mission-control, authoring, manifest, environments, secrets, implementation]
aliases: [Environment Kit, environment binding, network policy, materialization]
questions:
  - How do I declare a kit, secrets and network for a mission?
  - Why was my node refused for network or sandbox?
  - What does a Deep Agents node get for network grants?
updated: 2026-11-01
---

# Mission environments and materialization inputs

A `mission/v2` environment declares what a lane must materialize beside the multi-provider
selections of the [Mission Manifest](mission-manifest.md)
([SPEC-01 §3](../specs/archive/materialization-observation-2026-10/SPEC-01-environments.md)). The
shapes and pure rules live in `domain/authoring/mission_environment.py`; `EnvironmentV2` mixes
them in and `EnvironmentSelections` carries them, additively, on every definition node role.

| Field | Meaning |
| --- | --- |
| `kit: {pin}` | An exact Environment Kit pin (`id@version#sha256:…`); the kit is the setup pin |
| `variables` | Non-secret `name` with an inline `value` or `value_ref: config:<key>` |
| `secrets` | `name`, `ref` (`secret:<path>` or `mint:signal_token`), `phases` (`setup`, `agent`); never a value |
| `network` | `mode` (`allow_all`, `allowlist`, `none`), `allow` hosts (`*.` wildcard), `include_kit`, `include_signal_ingress` |
| `git` | `repos` (`target`, `dependency` read-only, `knowledge`) and `write` (`none`, `branch`, `branch_and_pr`; branch `mc/{run}/…`; `pr`) |
| `provider_environment` | `bind` (with `ref`), `sync` (`cursor_cloud` only) or `generate` (cloud lanes); worker lanes take none |

## Validation

Every failure is a manifest issue with a JSON pointer to the environment an author edits:

- **Lane rules** (`environment_lane_issues`): a strategy the lane does not offer, `sync` or
  `generate` without a kit, a kit that differs from `execution_environment.setup.pin`, a git
  target that is not `workspace.repo`, a write policy without a target, and a `claude_cloud`
  mission with dependency repositories plus callbacks (multi-repo sessions load no repo hooks).
  Cross-field rules (`allow` outside `allowlist`, ingress with `none`, `pr` outside
  `branch_and_pr`, a name that is both variable and secret) are checked on the merged
  environment, so an overlay never crashes the merge.
- **Inheritance**: a child cannot widen `network` (mode, hosts, include flags), add secrets
  beyond the parent's grant (absent means none granted) or relax `git.write` (mode, ready PR,
  provider PR). An explicit `null` for an inherited `network`, `git` or `git.write` widens
  too (the deployment default would apply). Another network or write mode replaces the
  inherited policy, as another `provider_environment` strategy or `execution_environment`
  kind does. A node that switches the kit its allowlist includes is compared host by host at
  compile (`admit_kit_switches`) once both kits resolve: only a host the parent's entries or
  kit do not allow widens.
- **Compile** (`ManifestCompileService`, `manifest_v2_admission.admit_environment_inputs`):
  kit pins and `config:` keys resolve offline through `EnvironmentInputsPort`; an unresolved
  kit (`CAPABILITY_UNAVAILABLE`) or key is a blocker, and no port composed means both block.
  The kit's `requires` must be met by the declared variables, required secrets (a trailing `?`
  is optional), egress (unless the policy includes the kit or allows the host) and git
  dependencies. A Deep Agents node materializes none of the kit additions (it warns `not_materialized`; its sandbox profile governs) except `network`, which must be exact worker-tool hosts and is sealed as an operation grant (`manifest_v2_admission.py:234-245`, table below).

Production compile resolves kits through the catalog (`CatalogEnvironmentInputs`, composed in
`bootstrap/manifests.py`) and `config:` keys through installation configuration (P1): the
operator-reviewed `mc.installation_config.v1` JSON file at
`MISSION_CONTROL_INSTALLATION_CONFIG_PATH` (`bootstrap/installation_config.py`, example
`deployments/examples/installation-config.example.json`) maps each Application id to its values,
and each Application's composition selects its own mapping (an Application not listed has none).
Unset, every `value_ref` still blocks (`config_unresolved`); a set file that is missing or
invalid, or one no Application can be selected from, fails composition. Keys follow the
`config:` grammar; a key containing `key|token|secret|password|passwd|dsn|credential` (a plain
substring match, so e.g. `keyboard.layout` is refused too) is refused at load and, on the key
alone, at compile (`config_secret_like`, same pointer, its value never read). Compile checks
only that a key resolves: values never enter the report, resolution, definitions or digests,
and errors name keys only (`InstallationConfig.value_digests()` gives SHA-256 digests to a
caller that needs a record). Nothing delivers a configuration value to a lane's runtime yet.

## Environment Kits and readiness

A kit's mission layer, its setup receipt, the Readiness Level ladder each attempt persists as
`mc.environment_preparation.v1` and the launch gate on it are in
[environment preparation](environment-preparation.md) (MO-12, MO-16).

## Binding population

`EnvironmentSelections.binding_fields()` is what `mc.environment_binding.v1` takes from the
manifest alone: `setup_pin` (the kit, now allowed on a local binding too) and `secret_refs` as
`NAME=ref` entries (the binding validator admits nothing else). The provider launch author
applies them to the deployment's host binding (`manifest_launch_inputs._populated_environment`)
with the resolved network policy below, so they enter the sealed `mc.execution_binding.v2`
digest. `resolve_environment` given a preparation attestation adds `observed_config_digest` and
`readiness`; what preparation observes is the preparation record
([environment preparation](environment-preparation.md)).

## Network policy

`domain/execution/network_policy.py` resolves the declared `network` per node role at launch
([SPEC-01 §5](../specs/archive/materialization-observation-2026-10/SPEC-01-environments.md)): an
`allowlist` becomes the sorted declared hosts, the kit's `requires.egress` under `include_kit`
(read through the author's kit port) and every Mission Control host the run requires. The
Signal Ingress host is required whenever callbacks are (`include_signal_ingress` or a
`mint:signal_token` secret), the Model Gateway host when a harness reaches its model through it
(a Sandbox Host placement). Both come from the installation (`NetworkHosts`); a required host the
installation does not configure, a closed network that forbids one, or kit egress that did not
resolve fails the launch at its pointer. The resolved policy is sealed as
`mc.environment_binding.v1` `network` (and on the Cursor binding) with its digest as
`network_policy_ref`.

`application/environments/network.py` projects it per lane into provider-native settings and
records `enforced`, `advisory` or `unsupported`, the delivery and any hosts the lane cannot reach
(an unreachable ingress degrades observation to the provider API):

| Lane | Projection | Allowlist enforcement |
| --- | --- | --- |
| `codex` | `-c sandbox_workspace_write.network_access` at launch | advisory (on or off only); `none` enforced |
| `claude_agent_sdk` | `ClaudeAgentOptions.sandbox` (`allowedDomains`; no unsandboxed or auto-approved Bash) | advisory (Bash only) |
| `cursor_local` | the deployment's sandbox flag | advisory with it, unsupported without |
| `cursor_cloud` | `egressMode` and `egressAllowlist` | enforced through `sync` or `generate`; advisory while bound |
| `claude_cloud`, `codex_cloud` | generated network level and domains | enforced once the owner applies them |
| `claude_managed`, `codex_agents` | environment `networking` or `network` (exact domains only) | enforced; self-hosted tools defer to the Sandbox Host |
| `deep_agents` | sealed `network_hosts` in the operation's capability grant (`operation_grant`, `network.py:20,72,403`) | advisory: governs worker-mediated tools that consume the grant and `agent_browser_page`; executable sandbox networking and third-party tool or MCP egress are unchanged |
| Sandbox Host | `project_sandbox_egress` by its egress control | enforced per sandbox; an organisation-only list is advisory or refused |

The `codex`, `claude_agent_sdk` and both Cursor lanes record the projection with their native
session identity (`network_policy_ref`, `network_enforcement`, `network_delivery`). A
`cursor_cloud` `sync` writes its fields into the synced environment
([provider environments](environment-preparation.md#provider-environments-on-cursor_cloud)).

## Repository requirement

`bindings.REPOSITORY_BOUND_PROFILES` (`cursor_local`, `claude_agent_sdk`, `codex`,
`claude_cloud`, `codex_cloud`) is the one per-profile table
([SPEC-03 §4](../specs/archive/materialization-observation-2026-10/SPEC-03-workspaces-and-placement.md)):
the v2 manifest and the hosted binding rule read it; `cursor_cloud` compiles repo-less and its
launch is refused at the pointer until a repo-less binding exists (CM-22). `mission/v1` keeps
requiring a repository on both Cursor lanes.

The public schema `contracts/schemas/mc.mission_manifest.v2.json` is generated:
`make manifest-schemas` writes it and `make manifest-schemas-check` fails on drift.

Built / specified / goal: kit inheritance, compile admission and the per-lane network projections are implemented and
tested; the Deep Agents network grant ran in the Qualia fixtures (integrated, live paid, NEXT-SESSION line 89); cloud
sandbox tiers and remote placement are proposals ([deployment](deployment.md)).

## Citations

- Spec: [SPEC-01](../specs/archive/materialization-observation-2026-10/SPEC-01-environments.md) §1-3, §5-8;
  [SPEC-03](../specs/archive/materialization-observation-2026-10/SPEC-03-workspaces-and-placement.md) §4.
- Code: [environment additions](../../src/mission_control/domain/authoring/mission_environment.py),
  [mission/v2](../../src/mission_control/domain/authoring/manifest_v2.py),
  [selections](../../src/mission_control/domain/authoring/mission_definition.py),
  [bindings](../../src/mission_control/domain/execution/bindings.py),
  [network policy](../../src/mission_control/domain/execution/network_policy.py),
  [network projection](../../src/mission_control/application/environments/network.py),
  [admission](../../src/mission_control/application/authoring/manifest_v2_admission.py),
  [compile](../../src/mission_control/application/authoring/manifest_service.py),
  [launch author](../../src/mission_control/application/authoring/manifest_launch_inputs.py),
  [schema generator](../../scripts/manifest_schemas.py).
- Tests: [environment additions](../../tests/unit/authoring/test_manifest_v2_environment.py),
  [network policy](../../tests/unit/agentic_components/test_network_policy.py),
  [lane network projection](../../tests/unit/harness/test_lane_network_projection.py).
