---
type: Concept
category: surfaces
title: The Selection Workspace
description: "How a coordinator searches capabilities, lanes, models, sandbox profiles and Workflow Types in one ranked answer and checks a draft lane/model/capability selection against the resolution seam's admission, host support and the Workflow Type's authority ceiling before writing a manifest, over HTTP, missionctl and the coordinator MCP tools."
tags: [mission-control, selection, resolution, capabilities, lanes, models, interfaces, implementation]
aliases: [selection check, resolution seam search, ranked search, keyword semantic navigation search]
questions:
  - Which lane, model and capabilities should this node use?
  - How does Mission Control search workflows, providers and configuration?
  - Why did selection check refuse my draft?
  - How do I list every skill, MCP server or Workflow Type, and why was a search empty?
updated: 2026-11-16
---

# The Selection Workspace

The owner's picture: Mission Control finds workflows, agent providers and configuration through
**keyword, semantic and workspace-navigation search**. In code:

| Mode | What implements it | State |
| --- | --- | --- |
| keyword | PostgreSQL full-text (`websearch_to_tsquery`) and trigram over capability names in the catalog projection; weighted token overlap over lane and model declarations (`workspace.py::_score`) | implemented, tested |
| semantic | pgvector cosine over `search_document.embedding`, fused with the keyword rankings by weighted RRF (ADR-0025); on only when `CAPABILITY_EMBEDDING_PROFILE` names an embedding route, else `search_mode: lexical` | implemented, tested with fixtures (`tests/fixtures/capability_search_eval.json`); live embedding projection on a remote not checked |
| workspace navigation | this concept: one ranked answer across capability, lane, model, sandbox-profile and Workflow Type facets, then `check` of a draft against the resolution seam | implemented, tested on in-memory ports |

Lane and model facets are keyword-only; semantic ranking applies to catalog kinds. Hybrid catalog search
itself is described in [capabilities](capabilities.md).

`application/selection/workspace.py::SelectionWorkspace` answers the coordinator's "where and
with what does this node run" before a manifest is written. `search(query, facets, lane_profile)`
asks Capability Search (kinds per facet: capability, `sandbox_profile`, `workflow_type`), the
Lane Registry (each registered Lane Declaration and describe) and the Model Catalog, and merges
the per-facet rankings by reciprocal rank (`1/(60 + rank)`), since the facets score on different
scales. Each hit carries the ref a draft names (a Capability Pin, `lane:<profile>` or
`model:<profile>`) and why it matched; a catalog facet that cannot answer is listed under
`unavailable`. `lane_profile` narrows capabilities to that lane's `supported` host support and
models to vendors the lane routes.

A search is never silently empty (2026-11-15). **Listing:** an empty query lists the requested facets by
name instead of ranking them: every lane, every Model Profile and every published definition of the facet's
kinds, read from the published definitions (cached 30 s), never from the Search Projection, behind `offset`
and `limit` with a `total`. `kinds` names the catalog kinds the capability facet answers with (any kind:
`skill`, `mcp_server`, `watcher` ...); kinds without facets ask that facet only. A listed hit is `facet`,
`ref`, `title` and a 60-character `summary` (`kind` where the facet holds several): fifty Workflow Types
list in about 3,000 tokens. **Definition scan:** when the catalog search answers a query with nothing, the
workspace searches one published definition by its own title; if the projection does not return it, the
projection is not built (or is stale) for that kind, so the workspace scans the published definitions
itself (name, kind, description) and says so: scanned hits carry the reason `definition scan`, `notes` names
the scanned facets, and `catalog_search_mode` is `definition_scan` when no facet was ranked by the catalog
(`definition_listing` for a listing). A scan has no semantic ranking and applies no selection policy.
The Mission Manifest compiler falls back to the same scan (`application/capabilities/definition_scan.py`)
for a `search` capability entry the projection answers with nothing: it scans the admitted rows a pin
could name (kind, namespace, lane support), probes the projection the same way, and records
`search_mode: definition_scan` on the entry of `resolution.resolved` with a warning; a projection that
answers keeps its own mode and its own empty answer (`search_no_admitted_hits`).

Three answers are not reusable catalog rows as such (2026-11-15). **Templates:** the `template` facet lists
the curated mission templates the composition hands in (`template:<id>`, read with the guide's describe).
**Sandbox profiles:** the `sandbox_profile` facet lists first the profiles the deployment's launch bindings
bind (`sandbox:<name>`, the name a manifest writes in `environment.sandbox.profile`), then the catalog's
sandbox definitions; `check` accepts a bound profile by name. **Lowered definitions:** a submitted manifest
lowers into a Workflow Type of its own with its blueprint and four profiles
(`manifest_lowering.manifest_lowered_refs`: the Workflow Type admits only the manifest input contract, and the
rest are the rows it allows). A listing, a ranked search and a scan leave those rows out, report
`lowered_hidden` with a note, and return them only for `include_lowered`.

`check(draft)` reads a draft (`lane_profile`, `model_profile`, `family`, optional `data_class`,
`capabilities` pins, `sandbox_profile` and `workflow_type` pins) and returns
`mc.selection_check.v1`: the resolution seam's admission (`RuntimeResolver.admit`), the lane
qualification refusal `resolve` would give, the model's Data Class ceiling, each pin's host
support on the lane (the compiler's `pin_lane_unsupported` rule for host-filtered kinds), the
lane's declared support for the pin's item kind, and each pin's `required_capabilities` against
the Workflow Type's authority ceiling. Refusals carry the seam's codes or the workspace's
(`CAPABILITY_LANE_UNSUPPORTED`, `AUTHORITY_CEILING_EXCEEDED`, `CAPABILITY_NOT_FOUND`,
`CAPABILITY_KIND_MISMATCH` ...) with pointers into the draft. It never launches, and lists what
it does not check: the lane compile and seal (`resolve` steps 3-6 need the compiled node and the
launch process's deployment facts), served digests, prerequisites and the KS apply contract;
`mission compile` and `preflight` stay the authority. The API composes one workspace per tenant
(`bootstrap/selection.py`); the CLI exits 6 on a refused draft. Proof:
`tests/unit/selection/` (in-memory ports; no database or live catalog).

## Interfaces

| Transport | Search | Check |
| --- | --- | --- |
| HTTP (`interfaces/http/selection.py`, `catalog.read`) | `POST /v1/applications/{app}/selection/search` | `POST .../selection/check` |
| missionctl (`interfaces/cli/selection.py`) | `search [QUERY] [--facet F]... [--kind K]... [--lane P] [--limit N] [--offset N] [--include-lowered]` | `workspace check DRAFT.json\|yaml` (exit 6 when refused) |
| MCP (`interfaces/mcp/selection_tools.py`, `catalog.read`) | `mission_search` | `selection_check` |

The coordinator MCP server registers both tools when a workspace is composed
(`interfaces/mcp/__main__.py` composes one from settings); the operator MCP reads the API's
per-tenant workspaces.

## Not the Catalog Workspace

The Selection Workspace is an API: `missionctl search` and `missionctl workspace check` are thin HTTP clients
(`interfaces/cli/selection.py`) that post to the same routes as the MCP tools `mission_search` and
`selection_check`. The **Catalog Workspace** (owner, AS-D38) is a different thing and is not built: a
generated, read-only filesystem rendering of the same registries, mounted into a sandboxed agent's
Workspace and navigated like the AI Engineer schema workspace
(`aiengineer/ai-engineer-db-contract/workspace/START_HERE.md`). It adds a filesystem path for sandboxed
agents beside the API, MCP and CLI; it replaces none of them ([goals](goals.md#goal-catalog-workspace)).

## Limits

The agent skills do not yet teach `missionctl search` or `workspace check`: no `skills/mission-control*` file
names them, and the agent-skills seed carrying that guidance (1.0.4) is not the released W0 bundle
([coordinator surface](coordinator-surface.md), STATE D11). `docs/tools/okf_search.py` searches documentation,
not the product; a workspace-wide documentation search across repositories is specified, not built
([applications](applications.md)).

Built / specified / goal: search, listing, the definition scan and check are implemented and unit-tested
(in-memory ports); none of the listing or scan has run on a deployed server; the live qualification of a
populated embedding projection and skill guidance are open; the dashboard use of search is a goal.

## Citations

- Code: [workspace](../../src/mission_control/application/selection/workspace.py),
  [composition](../../src/mission_control/bootstrap/selection.py),
  [HTTP](../../src/mission_control/interfaces/http/selection.py),
  [catalog search](../../src/mission_control/application/capabilities/capability_search.py),
  [embeddings](../../src/mission_control/adapters/capabilities/capability_embeddings.py).
- ADR: [0013](../adr/0013-catalog-search-postgres-fulltext-first.md),
  [0025](../adr/0025-hybrid-capability-search-rrf-with-lexical-fallback.md),
  [0063](../adr/0063-one-resolution-seam-over-declared-lane-model-and-application-registries.md).
- See also: [Model Catalog and model routes](model-catalog.md), [public interfaces](interfaces.md).
- Tests: [workspace](../../tests/unit/selection/test_selection_workspace.py),
  [interfaces](../../tests/unit/selection/test_selection_interfaces.py) (in-memory ports; no database),
  [search evaluation set](../../tests/fixtures/capability_search_eval.json).
