---
type: Decision Record
title: "One resolution seam over declared lane, model and application registries"
description: "Proposed: provider, model, blueprint and application variation is resolved by one function over three bootstrap-populated registries; lanes are one package each implementing a compile port and the harness; applications and models are data; model is an independent axis paired with the lane at admission; the core keeps no lane vocabulary beyond the profile name."
tags: [mission-control, adr, proposed, lanes, applications, resolution, architecture]
status: accepted
source: docs/specs/archive/provider-consolidation-2026-10/specs/SELECTION-AND-ROUTING-DESIGN.md; owner request 2026-10-27 (OC-D197); PROCESS.md §2 (discriminator-and-router rule); ADR-0005; ADR-0023; ADR-0026; ADR-0035; ADR-0050; ADR-0052; ADR-0059
---

# One resolution seam over declared lane, model and application registries

**Status: accepted 2026-10-27** (owner answers OC-D198 to OC-D202 to the design's open questions). The seam is not
built; its issues are OVE-194 (parent) and OVE-195 to OVE-202. PROCESS §2 remains the rule for work that lands
before the seam exists.

## Context

Nine Lane Profiles share one runtime protocol and one registry, and every lane runs one conformance
suite. At compile and launch, however, lane knowledge sits in three resolvers of one module, one file
renderer that switches on lane, two static behavior tables and about thirty other non-adapter files;
only Deep Agents has a dedicated compile adapter. The neutral operation request carries three
lane-shaped binding slots. The two applications are bound by a settings map and a branch in the
knowledge gateway; the Knowledge Services host closes the binding set in an enum and imports both
bindings statically. Model ids are declared once per lane in a deployment file. The owner asked for the
adaptation mechanism to be decided before implementation so that Deep Agents stays optimized without
its concepts shaping shared interfaces.

## Decision

1. **One seam.** `resolve_runtime(selection) -> ResolvedRuntime | ResolutionRefused` in
   `application/resolution/` takes (lane profile, model profile, blueprint family and role,
   application id, the node's neutral configuration) and returns a fully resolved runtime: neutral agent
   configuration, an opaque sealed lane binding, the knowledge port binding, the output contract profile,
   the transfer profile and the materialization receipt. Callers never branch on lane or application.
2. **Three registries, populated only in bootstrap.** `LaneRegistry` (exists, moved), `ApplicationRegistry`
   (new, from `deployments/<app>/application.toml`), `ModelCatalog` (new, from
   `deployments/<app>/models.toml`). No discovery; one registration line per variant.
3. **A lane is one package** under `adapters/<lane>/` exporting a registration: its declaration (the
   describe plus model routes, item support, family support and pins), a pure `compile` adapter, a
   harness factory and its conformance adapter. The core's lane vocabulary is the profile name, the hook
   event vocabulary, the configuration item kinds, the verdict set and the vendor set.
4. **Model is an independent axis in data and a dependent axis at admission.** A model profile names
   vendor, id, window and cost and no lane; a lane declares routes per vendor; the resolver pairs them
   and refuses `MODEL_ROUTE_UNSUPPORTED` otherwise.
5. **Application variation is data.** The application profile carries the knowledge binding and apply
   contract, data class ceiling, output minimums, transfer defaults and retention. Mission Control
   reads the profile from the resolved runtime, never the application id.
6. **One sealed lane binding slot** replaces the three typed slots on the operation request.
7. **Failure is loud and typed at resolution time**; degradation exists only for items the mission did
   not require and only as a receipt row.
8. **The same conformance suites verify every variant**, selected by its declarations, with declared
   exceptions citing proof: lane compile, lane runtime (exists), resolver, knowledge backend (KS),
   application profile.

## Rejected

A strategy object per concern; capability negotiation as the sole mechanism; entry-point discovery;
a provider abstraction over the agent lifecycle (already rejected by P1-S4); model as a sub-axis of
provider; an `ApplicationAdapter` class per application; keeping the three binding slots and adding
one per lane; keeping the Deep Agents feature vocabulary (`FeatureAxis`, `Mechanism`) as the shared
vocabulary.

## Consequences

- `application/authoring/lanes/`, the three per-lane resolvers, the lane switch in `render_host_files`,
  `V2_LANE_BEHAVIORS` / `LANE_BEHAVIORS`, `settings.knowledge_binding_ids`, `settings.anthropic_model` /
  `openai_model`, `gateway.APPLY_CONTRACTS`, the manifest's closed application literal and the KS binding
  enum are deleted when the moves land, not shimmed.
- Adding a provider is one package and one registration line; adding an application is one profile file
  and one KS binding package export. The design records on paper which files change for Claude Code and
  for Biotech.
- The seam is proven by one real lane until a second lane passes the compile suite; the sprint breakdown
  makes the second lane mandatory. Swarm and Evaluator Optimizer family support stays `unqualified`
  until WI-14 and WI-15.
- No accepted ADR changes. ADR-0023's host projection becomes each lane's `project`; ADR-0026's hook
  projection becomes each lane's slot table; ADR-0052's remote session base is unaffected; ADR-0059's
  ownership boundary is unchanged and enforced by the knowledge port's "never crosses" list.
