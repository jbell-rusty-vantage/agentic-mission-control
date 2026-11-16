---
type: Concept
category: execution
title: Capability seeds and skill bundles
description: Which MCP servers, skill bundles and hooks the seed bundles admit, the router skill and its five bundles with their LF-canonical digests, and the capabilities the three fixture manifests need that no reviewed seed provides yet (blockers B2 to B4).
tags: [mission-control, capabilities, seeds, skills, implementation]
aliases: [seed bundles, router skill bundles, agent-capabilities seed, skill bundles of this repository]
questions:
  - Which MCP servers, skills and hooks are seeded today?
  - Which seed families exist beyond agent-capabilities and what does each hold?
  - Which version is the mission-control router skill at?
  - Which capabilities do the fixture manifests need that no seed provides?
updated: 2026-11-16
---

# Capability seeds and skill bundles

How a capability is stored, pinned, searched and projected is in
[capabilities](capabilities.md). This concept lists what is actually admitted and what is not.

## Seeds

`mc.catalog.agent-capabilities@1.0.0` (common) holds `mcp.tavily`, `mcp.firecrawl`
and `mcp.agent-browser`, `skill.agent-browser`, the router `skill.mission-control` and its five
bundles (`-author`, `-catalog`, `-compose`, `-intervene`, `-observe`) and `hook.mc-policy-template`;
the `biotech` bundle adds `mcp.pubmed` and `mcp.biomcp` (+ `skill.biomcp`), `ai-engineer` adds
`mcp.edgartools` (+ `skill.edgartools`) (`packages/mission-control-db-contract/seeds/`, notes
in `AGENT_CAPABILITY_SEED_NOTES.md`). The per-application skill rows ship in
`mc.app.<app>.agent-skills`: 1.0.0 to 1.0.3 are frozen with their sources under
`bundle-sources/agent-skills-<version>/` (1.0.3, OC-R7, carries `skill.mission-control-author`
0.3.2, the Model Catalog authoring guidance, as revision 4), and 1.0.4 (OVE-204) adds each
application's knowledge charter (`skill.biotech-knowledge-charter`, `skill.ai-engineer-knowledge-charter`
0.1.0 from `skills/`, revision 1, admitted to its own application only; `seeds/agent_skills.py`
`APPLICATION_SKILLS`). The Application Profile names it (`[knowledge] charter_skill`) and manifest
compile mounts its latest row on every knowledge mission (provenance `application:charter`).
**1.0.5** (2026-11-16) publishes the six coordinator bundles regenerated from the guide, each at its next
revision ([coordinator surface](coordinator-surface.md#the-skill-router)), and the **imported method
skills** as new ids: from Knowledge Services, in both applications, `skill.knowledge-research` (the
research and verification method with tool playbooks), `skill.knowledge-verify` (the executor's evidence
capture), `skill.knowledge-acquisition-and-vetting`, `skill.knowledge-verification`,
`skill.knowledge-ingest`, `skill.knowledge-db` and `skill.schema-explore`; from the AI Engineer service,
in `ai-engineer` only, `skill.content-authoring` and `skill.ai-engineer-knowledge-charter` as revision 2
of that id, so the charter mount takes the service's own charter. Each import is an exact copy at one
commit under `bundle-sources/imported/<source>/<commit7>/<skill>/`, recorded in `IMPORTS.json` (source
repository, commit, path, per-file sha256 and git blob id) and held to it by `scripts/skills_import.py
--check`; its row carries `source_provenance.source: belllabs`, the slug `<source>/<skill>`, a version
ending in the commit and the commit digest (CAP-D1). Mission Control never edits a copy: an update is a
new import and a new seed version. Seeds cannot retire a row (a seed appends a decision, it never moves
`asset_version.status`), so revision 1 of the charter stays admitted beside revision 2; `@latest` is the
import.
Custody upload and remote apply are separate steps. `mc.app.<app>.environment-kits@1.0.0` holds the six starter
Environment Kits built from `envkits/` ([environment preparation](environment-preparation.md)). Tool lists are transcribed, not captured live. The
operational catalog surfaces are unchanged: `missionctl catalog list|resolve|search|discover|inspect|components`
plus the new `pin`, `render` and `publish` ([interfaces](interfaces.md)).

**Other seed families** (`packages/mission-control-db-contract/seeds/`; each versioned seed is frozen once applied and succeeded by a new file):

| Seed | Versions | Holds |
| --- | --- | --- |
| `mc.catalog.knowledge-tools` | 1.0.0, 1.1.0, **1.2.0** | the lane-neutral knowledge tools as `tool` rows; 1.2.0 adds `knowledge_read_intent` (OVE-204 slice 4) |
| `mc.catalog.workflow-parity` | 1.0.0 to **1.0.5** | workflow-family vocabulary registered by the compiler and worker: StageGraph and GoalDirected only |
| `mc.catalog.runtime-profiles` | 1.0.0, **1.0.1** | runtime persistence descriptor and Agent Server graph pins, 1.0.1 adding the sealed async child graph; pins only |
| `mc.catalog.artifact-schemas`, `approved-assets` | 1.0.0 to 1.0.2 | common report schemas and approved assets |
| `mc.app.<app>.cognition-profiles` | 1.0.0, **1.0.1** | portable cognition profiles. 1.0.0: the three plugins over the eight `mc-cognition-*` skills. 1.0.1: revision 2 of `plugin.cognition-knowledge` and `plugin.cognition-mixed`, whose knowledge members are `skill.knowledge-research`, `skill.knowledge-verify` and the application's charter in place of the four eight-line knowledge skills; `plugin.cognition-sdlc` stays at revision 1 |
| `mc.app.<app>.signal-skills`, `watchers` | 1.0.0 | the `mc-signals` bundles and the standard watcher templates (MO-46) |
| `mc.storage.capability-bundles`, `mission-payloads` | 1.0.0 | the private `capability-bundles` bucket; the private `mission-payloads` bucket (50 MiB per object, OVE-204 slice 7) |

`mc.app.ai-engineer.artifact-schemas@1.0.0` (Run 2 D5, an additive application slot) holds
`schema.sdlc-diagnosis-report@1`, `schema.sdlc-patch-report@1` and `schema.sdlc-review-report@1`
for the SDLC diagnose → patch → review missions
(`packages/mission-control-db-contract/seeds/sdlc_report_schemas.py`, the generated
`seeds/ai-engineer/mc.app.ai-engineer.artifact-schemas-1.0.0.json`, seed digest
`sha256:ce8b5c92…`). It is frozen in `FROZEN_BUNDLES` and was applied once to the live AI Engineer
installation on 2026-10-19, after a dry run and a backup record, with readback
([status ledger](../specs/archive/materialization-observation-2026-10/runs/RUN-2-CLOSE-STATUS.md), P2/D5).

Built / specified / goal: seeds generated, validated (`scripts/seeds_validate.py`) and applied to the W0 remotes with recorded limitations (`release/RELEASE-BUNDLE.md:264-271`); agent-skills 1.0.4 and the `mission-payloads` seed are built, not yet applied remotely; agent-skills 1.0.5, cognition-profiles 1.0.1 and approved-assets 1.0.3 are built and unit-tested, applied to no remote installation, and no mission has run with the imported skills mounted.

## Not wired or not published

- The production seeds lack many capabilities the three fixture manifests search for (the
  Biotech `kg_ingest` tool, a literature-review skill, a cloud-qualified PubMed endpoint,
  verifier subagents, shell-policy hook, `test_run` and `git_snapshot` executors). The
  stand-in rows in `tests/fixtures/catalog/fast_track_seeds.json` are test data, not reviewed
  capabilities (blocker B2 in the [owner runbook](../specs/archive/fast-track-2026-10/OWNER-FIXTURE-RUNBOOK.md)).
- The worker launches only components in its pin file `infra/capability-pins/research-capabilities.json`
  (one OpenAI model, `mcp.tavily`, `mcp.firecrawl`, the `agent-browser` skill) (B3). Since W1
  (D4) the Skill pin is the `bytes_v1` `capability-bundles://` custody form of
  `tests/fixtures/skills/agent-browser` (`scripts/pin_research_capabilities.py
  --upgrade-skill-custody`); a worker resolves it only after `register_supabase_skill_bundle.py`
  (Supabase) or `DirectoryBundleStore.publish` (local) stages and admits those bytes.
- Live bucket policies, the storage claim name `mc_capability_role` and executable read-only
  mounts are unqualified. Secure pathname validation does not prove an operating-system
  read-only mount.
- Text-only backends reject binary content explicitly. Bundle text cannot choose privileged
  bootstrap modules, credentials, application scope or additional authority.

## Skill bundles of this repository

`skills/mission-control/` (manifest 0.6.0, `skills/mission-control/manifest.json:4`) is the router over `mission-control-author`,
`-catalog`, `-compose`, `-intervene` and `-observe` (SPEC-08, ADR-0033). Digests in each
`skills/*/manifest.json` are LF-canonical; `make skills-check` fails on drift and
`make skills-manifest` rewrites them (`scripts/skills_manifest.py`,
`tests/unit/skills/test_skills_manifest.py`). The same check fails when a coordinator bundle's generated
`references/guide-*.md` differs from the guide (`scripts/skills_from_guide.py`) or an imported copy
differs from its record (`scripts/skills_import.py`). `skills/` also holds `mc-signals`, the eight
`mc-cognition-*` bundles (sources of the applied cognition-profiles 1.0.0) and the Biotech charter; the
0.1.0 AI Engineer charter left it for `bundle-sources/agent-skills-1.0.4/`, the archive of the frozen
seed that published it.

`skill.mission-control-coordinator` was retired by ADR-0033. It is no live skill: its bytes moved from
`.agents/skills/` to `bundle-sources/approved-assets-1.0.0/`, the archive of the applied seed that
published it, and `mc.catalog.approved-assets@1.0.3` publishes only the router manifest. Its catalog row
stays admitted on every installation that applied 1.0.0, because seeds cannot retire a row and the legacy
coordinator launch path still resolves it (`bootstrap/coordinator_composition.py`); retiring it is the
catalog's retire operation together with that consumer change (CS-D12).

## Citations

- Spec: [SPEC-01](../specs/archive/fast-track-2026-10/SPEC-01-capabilities-catalog.md),
  [SPEC-08](../specs/archive/fast-track-2026-10/SPEC-08-agent-skills.md),
  [seed capabilities and formats](../specs/archive/fast-track-2026-10/research/seed-capabilities-and-formats.md),
  [owner runbook](../specs/archive/fast-track-2026-10/OWNER-FIXTURE-RUNBOOK.md) (B2 to B4).
- ADRs: [0023](../adr/0023-capability-kinds-provider-neutral-core-host-projection.md),
  [0033](../adr/0033-mission-control-skill-is-a-router-over-specific-skill-bundles.md).
- Code: [seed generator](../../packages/mission-control-db-contract/seeds/generate_catalog_seeds.py),
  [capability definitions](../../packages/mission-control-db-contract/seeds/agent_capabilities.py),
  [seed notes](../../packages/mission-control-db-contract/seeds/AGENT_CAPABILITY_SEED_NOTES.md),
  [skills manifest tool](../../scripts/skills_manifest.py),
  [reference generator](../../scripts/skills_from_guide.py),
  [skill import and its check](../../scripts/skills_import.py),
  [import record](../../packages/mission-control-db-contract/bundle-sources/imported/IMPORTS.json),
  [skill seed definitions](../../packages/mission-control-db-contract/seeds/agent_skills.py),
  [cognition profile seeds](../../packages/mission-control-db-contract/seeds/cognition_profiles.py),
  [seed validation](../../scripts/seeds_validate.py),
  [capability pins adapter](../../src/mission_control/adapters/capabilities/capability_pins.py).
- Tests: [capability seeds](../../tests/unit/capability/test_agent_capability_seeds.py),
  [skill seeds](../../tests/unit/capability/test_agent_skill_seeds.py),
  [cognition profile seeds](../../tests/unit/capability/test_cognition_profile_seeds.py),
  [skills manifest](../../tests/unit/skills/test_skills_manifest.py),
  [coordinator bundles](../../tests/unit/skills/test_coordinator_bundles.py),
  [skill import](../../tests/unit/skills/test_skills_import.py).
- Test stand-ins (not reviewed capabilities): `tests/fixtures/catalog/fast_track_seeds.json`.
- Pin file: `infra/capability-pins/research-capabilities.json`; skills: `skills/`.
