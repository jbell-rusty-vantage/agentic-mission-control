---
type: Decision Record
title: "Owner prerequisites are typed, generated from the binding, verified with freshness, and block launch"
description: "Accepted for the materialization-observation packet (SPEC-05, MO-20, gap G4): every human-only step a lane needs is an mc.owner_prerequisite.v1 record with steps, paste-ready content generated from the same Environment Kit and network policy the mission binds, a verification method ranked strongest first and freshness; the store keeps each per installation scope as unmet, attested or verified, and a preflight assesses it so drifted, expired or unmet prerequisites block launch while expiring and stale ones warn."
tags: [mission-control, adr, accepted, owner-prerequisites, preflight, environments, providers]
status: accepted
source: docs/specs/archive/materialization-observation-2026-10/SPEC-05-owner-prerequisites.md (sections 1 to 4); SPEC-01 section 7; SPEC-06 section 10; GAP-REPORT G4; research/cursor.md section 8; research/claude-code.md Q8; research/codex.md section 7; ADR-0042; ADR-0043; domain/prerequisites/; application/prerequisites/; adapters/postgres/prerequisites/; migration 0038
---

# Owner prerequisites are typed, generated from the binding, verified with freshness, and block launch

**Status: accepted 2026-11-01; implemented by the materialization-observation Run 2 finish (`b95ae4aa` completion summary; `152a3dcb` finish records, 2026-10-20) and the 1.4 database release (`b434e573`).** Previously proposed. 

Some steps only the owner can take: a paid plan and its spend-limit prompt, a GitHub App install,
a cloud environment created in a web UI, an interactive `claude auth login` whose refresh grant
ends after 30 days. Today they surface late, as a failed or silently degraded launch, and the text
the owner pastes into a provider is written by hand, so nothing ties it to the kit and network
policy the mission actually binds.

We make each such step an **Owner Prerequisite**, `mc.owner_prerequisite.v1`: an id, provider and
scope (account, org, repo, environment, host, user), the lane features it blocks, ordered steps,
a verification method and freshness. A step is either text or a paste block naming a **generated
content** item. Mission Control renders those items from the same inputs the lane binding seals
(the Environment Kit pin and its base-layer files verified against the kit's file manifest, the
resolved network policy, the Secret Broker declarations): setup and install scripts, the Codex
Start skill, allowed-domain lists, the Cursor environment fields, variable-name templates, Build
Secret names, the broker references to fill and provider webhook URLs. Every item carries the
sha256 of its exact text and the record names the kit pin and policy digest it was
`generated_from`, so what the owner pastes is what the binding expects and a changed binding is
detected. Generated content names variables and secret references only: generators receive no
secret value, and the Secret Broker's commit scan refuses any item carrying a minted token or a
value the caller knows to be secret.

Verification is ranked strongest first: `api_probe` (Mission Control reads provider state),
`probe_mission` (a minimal launch emits a readiness signal), `file_check` (a local file or
credential exists and has not expired) and `attestation` (the owner says so). An attestation only
ever makes a prerequisite `attested`; the other three make it `verified`, and the store's checks
refuse any other pairing. Evidence cites the definition digest it proved, so re-registering
changed steps or content keeps the evidence but leaves it proving an older definition.

Freshness has three parts: `revalidate_after` makes old evidence **stale** (a warning),
`expires_after` bounds a credential's life and is flagged **expiring** `warn_before` it ends
(seven days by default) and **expired** after, and `on_change_of` names the binding inputs
(`kit_digest`, `policy_digest`) whose change makes the generated content **drifted**. A preflight
reports a **Prerequisite Standing** per record; drifted, expired and unmet block launch, expiring
and stale warn. The store (migration 0038, `owner_prerequisite`) keeps one row per prerequisite
per installation scope under forced RLS, with typed columns for the definition digest, state,
method and expiry, and a guard that fixes identity, advances versions by one, never moves back in
time and never deletes.

We rejected free-text runbooks (they drift from the binding and cannot be verified), storing
secret values with the prerequisite (the Secret Broker and the provider UIs hold values; ADR-0043),
treating an attestation as verification (it is the weakest evidence and is recorded as such) and
letting an agent work around an unmet prerequisite (it must relay the steps to the human).

## Consequences

- Preflight (`missionctl preflight`, the HTTP endpoint and MCP tool) and the launch refusal with
  `PREREQUISITES_UNMET` are MO-21; the setup wizard, probe missions and `missionctl prereq attest`
  are MO-22; the API-lane catalog entries MA1-MA5, OA1-OA4, SH1-SH2 are HL-19. They consume this
  store. MO-21 now composes it in the manifest facade, direct launch service and chain relay.
- Generators exist for `cursor_cloud` (the `generate` strategy's environment fields, Build
  Secrets), `claude_cloud` (A4, A6), `codex_cloud` (X3, X4), `claude_managed` (MA2) and
  `codex_agents` (OA2), plus the Secret Broker store items for the lanes the broker delivers to.
  Account-level items without generated content (plans, privacy mode, app installs) are catalog
  entries added beside them. Probe mission ids are named here and built by MO-22.
- Prerequisite ids carry the kit id and version, not its digest or the policy: a republished kit
  or a changed allowlist drifts the same environment item, so missions that bind one kit with
  different network policies contend for one provider environment and the drift says so.
- The Cursor `sync` strategy's environment (MO-13) needs no owner prerequisite; under `bind` the
  bound environment is the owner's and only its host prerequisites are generated.
