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
updated: 2026-11-01
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
| `mc.app.<app>.cognition-profiles` | 1.0.0 | portable cognition profiles over the `mc-cognition-*` skills (`tdd`, `code-review`, `pr`, `diagnosing-bugs`; `research`, `cite-and-verify`, `ingest`, `knowledge-services`) |
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

Built / specified / goal: seeds generated, validated (`scripts/seeds_validate.py`) and applied to the W0 remotes with recorded limitations (`release/RELEASE-BUNDLE.md:264-271`); agent-skills 1.0.4 and the `mission-payloads` seed are built, not yet applied remotely; Selection Workspace guidance is not in any skill bundle.

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

`skills/mission-control/` (manifest 0.5.0, `skills/mission-control/manifest.json:4`) is the router over `mission-control-author`,
`-catalog`, `-compose`, `-intervene` and `-observe` (SPEC-08, ADR-0033). Digests in each
`skills/*/manifest.json` are LF-canonical; `make skills-check` fails on drift and
`make skills-manifest` rewrites them (`scripts/skills_manifest.py`,
`tests/unit/skills/test_skills_manifest.py`). The coordinator design helper
`.agents/skills/mission-control-coordinator/` is a distinct authoring workflow, not a second
runtime authority.

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
  [seed validation](../../scripts/seeds_validate.py),
  [capability pins adapter](../../src/mission_control/adapters/capabilities/capability_pins.py).
- Tests: [capability seeds](../../tests/unit/capability/test_agent_capability_seeds.py),
  [skill seeds](../../tests/unit/capability/test_agent_skill_seeds.py),
  [skills manifest](../../tests/unit/skills/test_skills_manifest.py).
- Test stand-ins (not reviewed capabilities): `tests/fixtures/catalog/fast_track_seeds.json`.
- Pin file: `infra/capability-pins/research-capabilities.json`; skills: `skills/`.
