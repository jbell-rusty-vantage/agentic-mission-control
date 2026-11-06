---
type: Concept
category: execution
title: Capabilities, bundles and host projection
description: The capability kinds and their provider-neutral cores, digest-addressed bundle custody, pins, hybrid search with lexical fallback, host projection per lane profile, hook scripts and Kernel Hooks, subagent profiles and plugins. Seeds, skill bundles and what is not yet published are in capability-seeds.
tags: [mission-control, capabilities, catalog, search, skills, mcp, hooks, implementation]
aliases: [capability catalog, bundle custody, host projection, Agent Host generation]
questions:
  - How do I pin, search or project a skill, MCP server or hook?
  - How does a capability become native files for a lane?
  - What is an Agent Host and does it execute mission work?
  - Where are skill bundles stored and who may publish them?
updated: 2026-11-01
---

# Capabilities, bundles and host projection

A [Capability](../../GLOSSARY.md) is an installed, digest-pinned, admitted catalog asset a
mission may bind. The catalog is canonical for kinds (ADR-0020); agent-composition kinds, custody for directory bundles, hybrid search and one projection layer that renders any capability
into a lane's native files are ADR-0023 to ADR-0026. Search produces candidates, not authority; external discovery is quarantined and inspection evidence precedes any admitted version.

## Implemented

**Kinds and host support.** Migration 0025 extends `asset_version.kind` with `skill_bundle`,
`mcp_server`, `mcp_tool`, `hook_script`, `subagent_profile`, `plugin` and `middleware` (which no
longer maps to `hook`; the legacy literals `skill`, `tool` and `hook` stay valid for existing
rows). Each row also carries `host_support` (`mc.capability_host_support.v1`: per lane profile
`supported`, `unsupported` or `unqualified`, plus an optional overlay for fields with no
provider-neutral meaning, such as a Cursor subagent's `readonly`) and `secret_refs`, which are
names matching `^[A-Z][A-Z0-9_]*$`, never values (`domain/capabilities/host_support.py`); a row whose host support excludes a node's lane is a typed blocker, never a silent drop.

**Pins.** `<capability_id>@<version>#sha256:<manifest_digest>` is the only reference a
committed revision carries; the parser rejects a pin missing any part
(`domain/capabilities/pins.py`). `POST /catalog/pin` and `missionctl catalog pin` return
exactly one pin for a query or `AMBIGUOUS_CAPABILITY` (422); `GET /catalog/pins/{pin}`
resolves one.

**Bundle custody.** A skill bundle, hook script directory or long subagent prompt is stored once in
the private `capability-bundles` bucket under
`<application>/<kind>/<capability_id>/<version>/<manifest_sha256>/<path>`; the manifest
(`mc.capability_bundle_manifest.v1`) pins every file's sha256 and size
(`domain/capabilities/bundles.py`). `application/capabilities/bundle_custody.py` runs three
resumable steps: upload without overwrite (an existing object counts only after its bytes are
re-read and compared), register the row `proposed` (promotion to `admitted` is an operator
decision), and materialize through short-lived signed URLs with every file verified (mismatch is
`CAPABILITY_DRIFT`). Routes: `POST /catalog/publish:prepare` and `publish:complete`; `missionctl
catalog publish --dir --kind`. The settings select the backend (`CAPABILITY_BUNDLE_BACKEND`,
default `local`, filesystem store `adapters/capabilities/local_bundle_store.py`; `supabase` uses
`adapters/supabase_storage/bundles.py` with publisher or reader tokens, never the service key).
Every production rows resolver (launch author, lanes at `prepare`) materializes through one
`BundleMaterializer` (`bootstrap/bundle_custody.py`: local root or Supabase reader, signed URLs,
cached by manifest digest); without custody a launch selecting bundle bytes is refused at its
pointer (`bundle_custody_unavailable`). The configured API composes the catalog service without
custody (`CatalogService.custody`/`bundles` stay `None`), so `publish:prepare`, `publish:complete`
and rendering a bundle's bytes answer `catalog_publish_unavailable` or
`BUNDLE_CUSTODY_UNAVAILABLE`; bundles are published today by `scripts/seeds_publish_bundles.py`.
The common seed `mc.storage.capability-bundles@1.0.0` creates the bucket and policies and reports
`blocked` on plain PostgreSQL. It was applied to the W0 remotes (seed-apply `seeded`, 24 AI Engineer and 23 Biotech bundles replayed; 29 and 30 bundles uploaded to custody;
`release/RELEASE-BUNDLE.md:264-271`); the `mc.storage.mission-payloads-1.0.0` seed (provenance slice 7) is built and not yet applied remotely.

**Hybrid search.** `application/capabilities/capability_search.py` filters first (scope, admission,
kind, lane-profile host support, side-effect class), then fuses up to three ranked lists with
weighted reciprocal rank fusion (k=60; weights 1.0 full-text, 0.5 trigram over names and exact tool
names, 1.0 pgvector). Without an embedding route, or when the query embedding fails, it runs
lexical-only and reports `search_mode`; it never fails for a missing route. Hits are re-verified
against the authoritative definition digest. Migration 0026 makes `search_document.embedding`
nullable, adds `pg_trgm` surfaces (the extension must be provisioned in schema `extensions` before
the release is applied) and a partial HNSW index; `scripts/rebuild_capability_search_projection.py
--lexical-only` builds the projection without a paid embedding batch.
`CAPABILITY_EMBEDDING_PROFILE` unset means lexical search. The projection is rebuildable and never
an authorization store ([persistence](persistence.md)).

**Host projection.** `application/agentic_components/projections.py::HostProjectors.render` is a
pure renderer over each lane package's writer (`adapters/<lane>/host_files.py`, the hosted agent
APIs' in `adapters/remote_session/host_files.py`; composed in `bootstrap/host_projection.py`,
OC-R3). The lane-neutral checks and reports run first, then the profile's writer, which also places
its stdlib hook answer module (`adapters/<lane>/hook_output.py`) as `.mission/hooks/native_output.py`
for the lane-neutral `run.py` and `signal` scripts: resolved pins, a lane profile, the mission instruction, the Context Packet index
and the kernel hooks give the files the provider reads and a report of what was not projected
(`domain/agentic_components/projection.py`). Paths, delivery mode, the subagent fields each
provider carries (others are `degraded`), limits and hosted API targets are rows of the per-lane
layout table (`domain/capabilities/layouts.py`); goldens per profile live under
`tests/fixtures/projections/`. Secrets appear only as the lane's reference syntax (`${env:NAME}`
on Cursor); Kernel Hooks come first in every hook array; no lane writes `AGENTS.md` or
`CLAUDE.md`, and the projection merges into the repository's own files, never overwriting them
([instruction layering](instruction-layering.md)).

**Hooks.** One provider-neutral `HookEvent` vocabulary (`domain/capabilities/hooks.py`:
`session_start`, `before_tool`, `before_shell`, `after_compaction`, `stop` and others) maps to
each profile's native hook or a tool-name matcher; an event a profile cannot run is reported
`unsupported_on_lane` (a blocker when the hook is `fail_closed`). Each entry records, with its
evidence (`recorded`, `documented`, `unverified`), whether the native hook can `enforce` or only
`observe`, hosted support (the three hosted mappings derive from it), timeouts and the native
fail-closed form (Cursor `failClosed`, Claude `onFailure: "block"`, a Codex JSON decision with
exit 0, since a failing Codex hook fails open). Compile refuses a `fail_closed` hook its lane
cannot enforce (`unenforceable_on_lane`) and the projection reports such a gating hook degraded
(MO-31). A hook script reads `mc.hook_input.v1` on stdin and writes `mc.hook_result.v1`; exit
code 2 denies; results merge `deny` over `defer` over `allow` (`contracts/hooks.py`). File lanes
call `.mission/hooks/run.py` (`application/agentic_components/hook_runner.py`, standard library
only, scrubbed environment); Deep Agents runs `HookScriptMiddleware` ([Deep Agents lane](deep-agents-lane.md)). Mission Control's four Kernel Hooks (stop fence, operation intent, frame capture,
usage) are not catalog items and no manifest can remove them ([lanes and harness](lanes-and-harness.md), [cursor lane](cursor-lane.md)). The selectable lane features and model tools of an agent
(todo list, context editing, provider web search) are a separate registry, `domain/capabilities/features/`, not catalog items ([agent configuration](agent-configuration.md)).

**Agent Host generation.** An Agent Host (`cursor`, `codex`, `claude_code`, `agent_framework`) is a tool a human works in that reads generated configuration; it is where authoring happens, not where mission
work runs, and generation executes nothing. `domain/agentic_components/contracts.py` defines `AgentHost`, `ComponentKind`, `TrustStage` (`quarantined`, `reviewed`, `qualified`, `accepted`), an
`AgenticComponentRelease` that must carry exactly the typed binding of its kind, `MaterializationRequest`, a `MaterializationPlan` with contiguous steps and a `ReadinessReceipt`.
`application/agentic_components/projections.py::render_release_host_files` is the older MCP-only renderer used by the planner (`materialization.py`); `HostProjectors.render` is the Host Projection every
lane uses, and the Deep Agents writer is `adapters/deep_agents/host_files.py`.

**Subagent profiles and plugins.** `mc.subagent_profile.v1` is defined once and projected to
`.cursor/agents/<name>.md`, `.claude/agents`, `.codex/agents` or a Deep Agents `SubAgent`
dict (`domain/capabilities/subagents.py`). `mc.plugin_manifest.v1` is a manifest of exact
member pins with no install command or hook; compile expands members into the node's
environment with provenance `plugin:<alias>`, `capability_plugin_member` records the
expansion, and a plugin is admissible only while every member is admitted
(`domain/capabilities/plugins.py`, migration 0025).

**Seeds.** The common, `biotech` and `ai-engineer` agent-capability seed bundles admit the MCP
servers, skill bundles and the policy-template hook; see
[capability seeds and skill bundles](capability-seeds.md). The operational catalog surfaces are
unchanged (`missionctl catalog list|resolve|search|discover|inspect|components`) plus the new
`pin`, `render` and `publish` ([interfaces](interfaces.md)).

## Not wired or not published

The original fixture manifest searches and B2/B3/B4 labels are historical audit inputs;
current capability availability must be compiled against the actual installed seed release
and selected bindings. Live bucket policies and executable read-only mounts remain
placement-specific qualification gates. Detail, with the seed inventory and repository
skill bundles, is in [capability seeds and skill bundles](capability-seeds.md).

Production bundle custody is composed into [manifest authoring](../../src/mission_control/bootstrap/manifests.py) and [provider lane composition](../../src/mission_control/adapters/temporal/provider_lane_composition.py);
the API publication limit above stays distinct. Layering, allowlisted child environments and environment-preparation records also have production paths; their [Run 1 evidence](../specs/archive/materialization-observation-2026-10/runs/RUN-1-REPORT.md)
does not establish that every provider loaded or exercised every capability.

Standalone local CLI job skills live under `.agents/skills/coding-cli-jobs` and its three
provider companions. They are independent of this catalog and Mission Control lifecycle;
their fake-CLI checks do not qualify a Mission Control lane or publish a bundle.

Built / specified / goal: catalog, custody, hybrid search, projection and hooks built and tested; W0 seeds applied remotely with recorded limitations; API-side publish and live provider loading of every capability are not established.

## Citations

- Research: [capability evolution](../research/mission-control/capability-evolution-2026-10-14.md) (discovery, composition and evolution across provider runtimes).
- Spec: [SPEC-01](../specs/archive/fast-track-2026-10/SPEC-01-capabilities-catalog.md), [SPEC-08](../specs/archive/fast-track-2026-10/SPEC-08-agent-skills.md), [seed capabilities and formats](../specs/archive/fast-track-2026-10/research/seed-capabilities-and-formats.md).
- ADRs: [0013](../adr/0013-catalog-search-postgres-fulltext-first.md), [0020](../adr/0020-capability-kinds-canonical-in-catalog.md), [0023](../adr/0023-capability-kinds-provider-neutral-core-host-projection.md), [0024](../adr/0024-skill-bundle-custody-supabase-storage-digest-paths.md),
  [0025](../adr/0025-hybrid-capability-search-rrf-with-lexical-fallback.md), [0026](../adr/0026-hook-scripts-one-event-vocabulary-projected-per-lane.md), [0033](../adr/0033-mission-control-skill-is-a-router-over-specific-skill-bundles.md).
- Code: [catalog application service](../../src/mission_control/application/capabilities/catalog.py), [hybrid search](../../src/mission_control/application/capabilities/capability_search.py), [bundle custody](../../src/mission_control/application/capabilities/bundle_custody.py),
  [bundle manifests](../../src/mission_control/domain/capabilities/bundles.py), [host support](../../src/mission_control/domain/capabilities/host_support.py), [pins](../../src/mission_control/domain/capabilities/pins.py), [hook events](../../src/mission_control/domain/capabilities/hooks.py),
  [subagent profiles](../../src/mission_control/domain/capabilities/subagents.py), [plugins](../../src/mission_control/domain/capabilities/plugins.py), [hook contracts](../../src/mission_control/contracts/hooks.py), [per-lane layout table](../../src/mission_control/domain/capabilities/layouts.py),
  [host projection](../../src/mission_control/application/agentic_components/projections.py), [projection contracts](../../src/mission_control/domain/agentic_components/projection.py), [hook runner](../../src/mission_control/application/agentic_components/hook_runner.py),
  [catalog HTTP facade](../../src/mission_control/interfaces/http/catalog.py), [local bundle store](../../src/mission_control/adapters/capabilities/local_bundle_store.py), [bundle custody adapter](../../src/mission_control/adapters/capabilities/capability_bundles.py),
  [PostgreSQL bundle admission](../../src/mission_control/adapters/postgres/capability_bundles.py), [migration 0025](../../packages/mission-control-db-contract/component/migrations/0025_capability_kinds_and_host_support.sql),
  [migration 0026](../../packages/mission-control-db-contract/component/migrations/0026_search_projection_nullable_embedding.sql).
- Tests: [host projection](../../tests/unit/agentic_components/test_host_projection.py), [layout table](../../tests/unit/agentic_components/test_lane_layouts.py), [hook runner](../../tests/unit/agentic_components/test_hook_runner.py), [bundle custody](../../tests/unit/capability/test_bundle_custody.py),
  [custody in every rows resolver](../../tests/integration/postgres/test_bundle_custody_composition.py), [search](../../tests/unit/capability/test_capability_search.py), [search evaluation set](../../tests/unit/capability/test_search_eval.py), [catalog CLI](../../tests/unit/capability/test_catalog_cli.py),
  [hybrid search in PostgreSQL](../../tests/integration/postgres/test_capability_search_hybrid.py), [bundle publish in PostgreSQL](../../tests/integration/postgres/test_capability_bundles_publish.py), [bundle materialization](../../tests/integration/postgres/test_skill_bundle_materialization.py).
- Canonical runtime router: `skills/mission-control/`; its owned catalog bundles remain digest-pinned separately from standalone `.agents/skills/` source.
