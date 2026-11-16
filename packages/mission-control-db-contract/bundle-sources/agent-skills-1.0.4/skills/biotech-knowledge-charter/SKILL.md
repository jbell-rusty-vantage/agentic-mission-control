---
name: biotech-knowledge-charter
description: The Biotech knowledge charter - what the biotech/longevity knowledge graph holds, which entities and registered relationships a mission may author, the evidence bar, forbidden inferences and what counts as proof of ingestion. Use before researching, verifying or ingesting Biotech knowledge, when choosing what to capture from a source, or when a biotech_ingest preview refuses.
---

# Biotech knowledge charter

The Biotech application keeps a provenance-bound knowledge graph of the biotech, biohacking and
longevity ecosystem: companies, brands, products and their labels, ingredients and substances,
studies and their results, and the claims and assessments that tie them to sources. Every node
answers "who said this, where, and how well is it supported". The graph supports structured
inquiry and product evaluation; it is never clinical advice, diagnosis or a dosing
recommendation.

The graph is Neo4j behind Biotech Knowledge Services (BKS) on the pinned release
`biotech-schema-v2.2.0` (69 node types, 106 relationship types). The release is the schema
authority; you author intents against it and BKS plans, admits and writes.

## Charter: what belongs in the graph

| Area | Entities you may author | Notes |
| --- | --- | --- |
| Actors | `Organization`, public `Person` | A Person carries `privacyClass: PUBLIC` and a sourced `publicActorBasis` (for example `AUTHOR_OR_INVESTIGATOR`). |
| Commerce | `Brand`, `Product`, `ProductVariant`, `Package`, `LabelVersion` | A `LabelVersion` is immutable: a changed label is a new version, never an edit. |
| Composition | `IngredientMaterial` (with its `MaterialKind`), `ChemicalSubstance` | Choose the `MaterialKind` the source supports; `UNRESOLVED` is a valid answer. |
| Evidence | studies and `StudyResult`, `Claim`, `Assessment`, the evidence `Report` | Claims, assessments and the report are host-built from the frozen verification report (section 4). |

Roadmap areas (interventions, lab tests, devices, protocols, practitioner playbooks) are product
direction in `biotech/BellLabs/index.md`, not registered schema: record them only where the pinned
release already has a node type for them.

Relationships you may author: product state (product, variant, package, label version),
`DECLARES_COMPONENT` (label to ingredient), branding, corporate ownership and public roles. Use
only predicates and relationship triples registered in the pinned `native-vocabulary.json`; the
v2 proposal for every structural or asserted edge is `edge.assert`.

## 1. Plan the capture

Before acquiring sources, name the subjects the mission's goal needs and the fact each one must
carry. Done when every intended subject has a node type from the table above and a source kind
you expect to quote (label page, registry, paper, preprint, company filing).

## 2. Acquire and verify evidence

Follow [references/research-procedure.md](references/research-procedure.md): the stage's assigned
tools only, complete text captures, exact quotes. Hold every fact to the evidence standard:

- Quote exact text from a retained capture; a search listing is discovery, never evidence.
- Keep the distinctions explicit: current label versus trial formulation, finished product versus
  ingredient study, peer review versus preprint, primary versus exploratory outcome, biomarker
  versus clinical or longevity endpoint.
- Record funding, author organizations, missing data, multiplicity and null findings beside the
  result they qualify.

## 3. Forbidden inferences

Each of these is a separate fact that needs its own quote; the source of the first never proves
the second:

- a brand does not establish the legal corporation behind it;
- an ingredient name does not establish a chemical salt or form;
- a serving name does not establish a dose;
- a product page does not establish corporate ownership;
- NAD or SASP signals do not establish lifespan extension.

## 4. Author the intent and ingest

Follow [references/ingestion-guide.md](references/ingestion-guide.md) step by step. The report
rule: exactly one primary Claim, and `reportProjection` covers every frozen assertion once. The
host copies propositions into Claims and KS judgments into `PROPOSED VETTING` Assessments; they
stay proposed. Done when `biotech_ingest` preview reports an applicable plan with every subject
and proposal applicable.

## 5. Proof of ingestion

Ingestion is proven only by all three: an exact-use admission decision, a real graph receipt, and
a post-write readback of that effect. A preview, an offline plan check, `verify_evidence` or a
pending outbox receipt is evaluation, not ingestion; report it as such.

## Boundaries

- Schema: author against the pinned release; schema changes belong to a BKS release, outside a
  mission.
- Graph lifecycle: no deletion, bootstrap or automatic promotion of claims or assessments.
- Data: public sources only; no PHI. The application's data class ceiling is `internal`.

## Navigation

- `biotech_schema(section='guide')` first; then `section='canonical_schema'` for exact intent
  fields and `section='native_vocabulary'` with RFC6901 pointers (`/nodes/LabelVersion`,
  `/predicates/LEGAL_NAME`, `/relationships/DECLARES_COMPONENT`) for registered predicates and
  enums. Paginate instead of guessing.
- BKS skills for depth: `biotech-kg-ingest` (proposal matrix and v2 contract) and
  `biotech-schema-explore` (schema cards and search).

Sources: `biotech/README.md`, `biotech/biotech-knowledge-services/docs/NAVIGATION.md`,
`biotech/biotech-knowledge-services/scripts/fixtures/qualia/README.md`,
`biotech/BellLabs/index.md`.
