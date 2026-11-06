---
type: Decision Record
title: "Environment Kits and two-layer base/mission setup with one bootstrap entrypoint"
description: "Accepted for the materialization-observation sprint (SPEC-01 sections 1, 2 and 8, MO-12): packages, runtimes and per-mission setup come from an Environment Kit, a pinned catalog bundle of a new capability kind environment_kit; its rarely-changing base layer is installed by Mission Control where a provider has an API and otherwise by the owner, and its mission layer is rendered into .mission/setup/run, which one bootstrap entrypoint per lane runs before agent work and which writes .mission/setup/receipt.json, the only evidence that lifts readiness to prepared."
tags: [mission-control, adr, accepted, environments, capabilities, materialization]
status: accepted
source: docs/specs/archive/materialization-observation-2026-10/SPEC-01-environments.md (sections 1, 2, 7, 8 and 10); docs/specs/archive/materialization-observation-2026-10/research/cursor.md (sections 1.1-1.3); docs/specs/archive/materialization-observation-2026-10/research/claude-code.md; docs/specs/archive/materialization-observation-2026-10/research/codex.md; DECISIONS R24 and Proposed ADRs 0042; GAP-REPORT G2, G3; MO-12; MO-10; ADR-0023; ADR-0024
---

# Environment Kits and two-layer base/mission setup with one bootstrap entrypoint

**Status: accepted 2026-11-01; implemented by the materialization-observation Run 2 finish (`b95ae4aa` completion summary; `152a3dcb` finish records, 2026-10-20) and the 1.4 database release (`b434e573`).** Previously proposed.

Before this decision nothing provisioned packages or runtimes or ran setup for a mission, and
nothing produced a readiness receipt (gaps G2, G3). The only hosted setup was a hand-written
`.cursor/environment.json`, and the alternative every lane fell back to, asking the agent to
install its own tools in the first prompt, is not enforcement. Provider-hosted environments are
slow to change and often UI-only, while missions need per-run setup.

We split setup into two layers and add one capability kind for them.

- **Environment Kit, a catalog capability kind (`environment_kit`).** A kit is a bundle whose
  `kit.json` is `mc.environment_kit.v1`: toolchains (a closed table, each with the command that
  reports its version), system packages, a base layer (install script, services), a mission
  layer (ordered steps with a closed `exists('<path>')` condition, health checks, a time bound)
  and `requires` (variables, secrets with `?` for optional, egress hosts, git dependencies). It
  is stored through the existing bundle custody (ADR-0024) and published as an
  `EnvironmentKitDefinition` whose host support and secret names are derived from `kit.json`,
  so the row never states more than the kit declares. A manifest pins it exactly
  (`envkit.<name>@<version>#sha256:<definition digest>`, the catalog's Capability Pin; the
  spec's `envkit/<name>` spelling is not a legal capability id).
- **No new SQL.** Definitions take any `definition_kind`, and the asset row uses the existing
  `profile` category (as sandbox profiles and placements do), so no migration slot is used. Its
  host support uses the profiles migration 0031 admits.
- **Host support says what is proven.** The kit's own vocabulary (`full`, `base_via_owner`,
  `unsupported`, keyed by `local` and the hosted profiles) maps onto
  `mc.capability_host_support.v1`: `supported` only where the worker's prepare step runs the
  entrypoint (`cursor_local`, `claude_agent_sdk`, `codex`); `unqualified` where the route is
  declared but not proven (every hosted profile until drills Q-C1, Q-L1 and Q-X1 answer), with
  an overlay `base_layer: mission_control | owner` naming who installs the base layer. Deep
  Agents never takes a kit; its sandbox profile governs.
- **Base layer.** Changes rarely and is keyed by the kit digest. Mission Control installs it
  through an API where one exists (Cursor environments, MO-13) and otherwise emits the generated
  text as an owner prerequisite (SPEC-05). The repository's Mission Control-owned
  `.cursor/environment.json`, `Dockerfile` and scripts (DECISIONS R24) are the base layer of
  `envkit.mission-control-dev`, adopted byte for byte. The kit marker in its `name`, which the
  cursor_cloud preflight reads for the mc-owned check (SPEC-01 section 7), is
  `mc:<kit id>@<kit version>` (`mc:envkit.mission-control-dev@1`), so it follows the id spelling
  above. Mission Control installs the base layer itself (`full`) only on `local` and
  `cursor_cloud` (the `sync` strategy); `claude_cloud` and `codex_cloud` are `base_via_owner`.
- **Mission layer and the bootstrap entrypoint.** The kit's steps render deterministically into
  one script, `.mission/setup/run` (plus `.mission/setup/kit.json`). It names variables only,
  never a value. It is idempotent, bounded by the kit's `timeout_s`, and writes
  `.mission/setup/receipt.json` (`mc.mission_setup_receipt.v1`: kit pin, phase, outcome, step
  statuses and exit codes, health results, observed toolchain versions). One guarded command per
  lane joins the layers: the worker's prepare step on the local lanes, `start` of the
  Mission Control-owned `.cursor/environment.json` on `cursor_cloud`, a `SessionStart` hook
  guarded by `CLAUDE_CODE_REMOTE=true` on `claude_cloud`, and the start skill on `codex_cloud`.
- **Readiness levels.** `declared`, `rendered`, `delivered`, `prepared`, `discovered`,
  `exercised` (SPEC-01 section 8). Only a receipt for the exact pin whose steps and health checks
  all passed reaches `prepared`; a stale receipt is removed before each run and a receipt for
  another kit never counts. Local launch requires `prepared`: a lane whose binding pins a kit
  refuses to start a session on anything less (`ENVIRONMENT_NOT_PREPARED`), and a pinned kit
  with no mission layer composed is refused rather than skipped.
- **Setup runs with the allowlist.** The setup child gets the MO-04 allowlisted environment plus
  the binding's `setup`-phase secrets from the Secret Broker (ADR-0043), never the worker's own
  environment. `cursor_local` runs it with the bridge's allowlist only: the Cursor binding
  carries the kit pin (`mc.cursor_binding.v1` `setup_pin`) but no broker-delivered secrets.
  Its output is discarded, because a step may echo a delivered value; the receipt is the
  evidence.
- **Compile stays offline.** The catalog's kit reader is the production `EnvironmentInputsPort`
  of manifest compilation (MO-10): a kit pin resolves to its `requires` without contacting a
  provider, and an unknown pin is a blocker.

We rejected a first-prompt install step (not enforcement), a provider-specific setup format per
lane (six divergent setups for one mission), a new SQL kind literal (a migration slot for a name
the existing category already carries) and treating a written setup file as readiness (a file
is `delivered`; only a receipt is `prepared`).

## Consequences

- Six starter kits ship as `mc.app.<app>.environment-kits@1.0.0` seed bundles from
  `envkits/`: `envkit.python-uv`, `envkit.node`, `envkit.python-uv-node`,
  `envkit.mission-control-dev`, `envkit.knowledge-research` (both applications) and
  `envkit.biotech-backend` (Biotech only). `scripts/seeds_publish_bundles.py` uploads their
  bytes with the skills.
- The `cursor_local`, `claude_agent_sdk` and `codex` lanes run the mission layer in `prepare`,
  record `setup_digest` and `setup_receipt_digest` beside the projection digests, and refuse a
  kit that is not `prepared`.
- Not yet delivered: `setup`-phase secrets on `cursor_local` (no broker delivery on the Cursor
  binding, ADR-0043), base-layer sync on `cursor_cloud` (MO-13), the generated owner
  prerequisites for `claude_cloud` and `codex_cloud`, persisted `mc.environment_preparation.v1`
  records and the readiness ladder on the binding (MO-16), manifest `variables` in the setup
  environment (the binding does not carry them), and an installation configuration source for
  `value_ref: config:<key>`, which therefore stays a compile blocker.
- The hosted entrypoints are rendered but unproven until the Q-C1, Q-L1 and Q-X1 drills run;
  their host support stays `unqualified` until then.
