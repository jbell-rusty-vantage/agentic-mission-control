---
name: mission-control-catalog
description: Choose what a mission runs on and with - list and search lanes, Model Profiles, capabilities, templates and sandbox profiles with missionctl search, read one with missionctl describe, check a draft selection, pin a capability or publish a skill bundle. Use when a manifest needs a lane, a model or a capability, when the user asks what exists, or when something outside the catalog is found.
---

# Select lanes, models and capabilities

The Selection Workspace answers "what exists here, and would it run": one search over lanes,
Model Profiles, the capability catalog, templates and sandbox profiles, and one read-only check
of a draft. Search ranks candidates; only an exact Capability Pin is authority.

Facts come from the server: the counts, the lanes this installation binds, each lane's support
and each model's route are in `missionctl guide TOPIC` and `missionctl describe REF`. The
references are those pages as this release rendered them.

## Order of work

1. **List before you search.** `missionctl search --facet lane`, `missionctl search --facet model`
   and `missionctl search --kind skill` read the published definitions, so a listing is
   complete. Search by meaning with `missionctl search QUERY`, narrowed with `--lane PROFILE`.
   Read `catalog_search_mode` and `notes` in the answer: they say who ranked the hits.
   [capabilities](references/guide-capabilities.md)
2. **Read one.** `missionctl describe REF` with a hit's `ref`, `lane:PROFILE`, `model:PROFILE`,
   `feature:ID` or `sandbox:PROFILE`. Done when you can say what it does, which lanes support
   it and which secrets it names.
3. **Choose the lane** by what the node needs, in the order the lanes page gives: workflow
   system, model vendor, capability kinds, run controls. [lanes](references/guide-lanes.md),
   [workflows](references/guide-workflows.md)
4. **Choose the model.** A judge runs on another profile than the producer, preferably another
   vendor. [models](references/guide-models.md)
5. **Check the draft.** `missionctl workspace check DRAFT`. Done when it admits every selection
   on your lane and under the Workflow Type's authority ceiling.
6. **Write it into the manifest** as a `pin` with the hit's `ref`, or as a `search` entry that
   compile resolves. `missionctl catalog pin` resolves a query to exactly one pin or names the
   candidates.

## Publish a skill bundle

`missionctl catalog publish --dir PATH --kind skill_bundle` stores the bytes under their digest
path, then registers the row `proposed`; admission is the operator's decision. A server composed
without custody refuses the call (`catalog_publish_unavailable`): there, bundles ship through
the installation's seeds.

## Rules that never bend

- Discovered is not runnable: a hit runs only after the draft check and compile admit it.
- A result from outside the catalog (`missionctl catalog discover`, `missionctl catalog inspect`)
  is a candidate. Tell the user what you found; the installation's owner publishes it.
- Selecting an MCP server selects no tool: name the tools the node may call.
- A capability names its secrets. The installation resolves them; `missionctl preflight` lists
  what the owner still has to set up.

## Common mistakes

- Trusting rank: a high score is not admission.
- Reading an empty search as "nothing exists": list the kind.
- Starting a mission from a Workflow Type: a mission starts from a template.
- Writing a pin from memory or from a reference file: a pin comes from this server's answer.
