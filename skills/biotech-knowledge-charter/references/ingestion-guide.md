# Biotech ingestion guide

Promoted from the `biotech_schema(section='guide')` result of the Qualia fixture bridge
(`tests/fixtures/qualia_knowledge.py`) and the BKS Qualia fixture README. The live guide returned
by `biotech_schema` is authoritative when the two differ.

## Who authors what

You author actual entities, sourced fields, locators and proposals. The host supplies capture
bytes, time and custody, the context and the frozen report. KS policy decides admission.
`native_input` excludes `report`, pins, sources, bytes, `storageUri` and `retrievedAt`; the real
builder supplies them.

## Procedure

1. Read `biotech_schema(section='guide')`. Exact canonical fields are at
   `section='canonical_schema', json_pointer='/properties/subjects'`; paginate with
   `offset_chars` or use a narrower pointer.
2. Read registered node properties, predicates and enum values in
   `section='native_vocabulary'` (`/nodes/StudyResult`, `/predicates/LEGAL_NAME`,
   `/relationships/DECLARES_COMPONENT`). Never invent a predicate.
3. Read `evidence_report_read(report_digest=<actual report digest>, section='frozen',
   json_pointer='/assertions')` for the immutable assertion IDs, propositions, qualifiers and
   evidence.
4. Author `captures`: include every frozen evidence `captureId` as a native capture with
   `capture_id` and its exact `canonicalUri`. A distinct browser capture is included only when
   that exact ID occurs in this frozen report's evidence.
5. Author `subjects` with `subjectEvidence` pointing to unique exact captured quotes, and
   `proposals` with captured locator evidence, using canonical proposal fields (`edge.assert` for
   edges).
6. Author `reportProjection: {primaryAssertionId, claims: [{assertionId, claimRef, claimType}]}`
   covering every frozen assertion exactly once. `claimRef` is a unique local reference;
   `claimType` comes from the registered enum
   (`/nodes/Claim/properties/claimType/enumValues`); use `OTHER` when nothing more specific is
   justified. Do not declare the generated Claims again in `subjects`.
7. `biotech_ingest` preview; repair from the actual compiler reasons and preview again with the
   same report. Then apply.

## Minimal property examples (vocabulary, not classifications)

| Node | Example properties |
| --- | --- |
| `Product` | `productKind: DIETARY_SUPPLEMENT` |
| `ChemicalSubstance` | `substanceClass: CHEMICAL` |
| `IngredientMaterial` | `materialKind: BOTANICAL_PREPARATION` (others: `CHEMICALLY_DEFINED`, `MICROBIAL_PREPARATION`, `MATERIAL_MIXTURE`, `PROTEIN_OR_ENZYME`, `UNRESOLVED`, `OTHER`) |
| `Organization` | none required |
| `Person` | `privacyClass: PUBLIC`, `publicActorBasis: [AUTHOR_OR_INVESTIGATOR]` |

Choose only values justified by source evidence. A named public study author's
`publicActorBasis` is `AUTHOR_OR_INVESTIGATOR` only when actually sourced.

## Example `native_input` shape

Every string is a placeholder, never evidence.

```json
{
  "intentId": "author-a-unique-intent-id",
  "captures": [
    {
      "ref": "label",
      "canonicalUri": "https://www.qualialife.com/shop/qualia-nad",
      "capture_id": "COPY_ACTUAL_EVALUATED_CAPTURE_ID",
      "title": "HOST_OVERRIDES_FROM_CAPTURE",
      "locators": [
        {
          "ref": "product-name-quote",
          "exact": "AUTHOR_UNIQUE_EXACT_CAPTURE_QUOTE",
          "reportsFields": ["Product.name", "Product.marketedName"]
        }
      ]
    }
  ],
  "subjects": [
    {
      "ref": "product",
      "mode": "new",
      "nodeType": "Product",
      "name": "AUTHOR_ACTUAL_CAPTURED_PRODUCT_NAME",
      "properties": {
        "productKind": "DIETARY_SUPPLEMENT",
        "marketedName": "AUTHOR_ACTUAL_CAPTURED_PRODUCT_NAME"
      },
      "onMatch": "use_existing"
    }
  ],
  "subjectEvidence": {"product": ["product-name-quote"]},
  "proposals": [],
  "about": ["product"]
}
```

## What the host builds from the frozen report

The host creates each Claim from its exact frozen proposition and a `PROPOSED VETTING`
Assessment from each actual KS support observation. One evidence report assesses the selected
primary Claim and cites the assessments, retaining the full frozen KS bundle as context. This
makes no clinical-certainty or world-truth promotion. Do not author replacement judgments,
synthetic predicates or `report.publish`. The builder derives support locators from the frozen
evidence; supply your own exact locators only for authored entity fields and other domain
proposals.

## Capture-selection repair

Use only exact evaluated IDs from `verify_evidence.source_captures` and the frozen assertions. A
`native_admission` capture-selection refusal is recoverable before finalization: read its
report-bound allowed IDs and `referenced_paths`; remove an unused extra capture only after
resolving all references; for a referenced locator, `source_read` an allowed snapshot and author
a unique exact quote supporting the same fact. Never auto-rebind IDs or quote bytes. Retry
`biotech_ingest` with the same report and corrected `native_input`. This refusal is not an
applied graph write.

## Rules

- Placeholders are not facts; every value is justified by a captured quote.
- Every new subject needs `subjectEvidence` pointing to unique exact captured quotes.
- Every factual proposal needs captured locator evidence.
- Captures use only snapshots evaluated by `verify_evidence`; capture method, hash basis and
  completeness are host-derived.
- Keep funding, limits and formulation versions explicit.
- `verify_evidence` is evaluation, not admission. `biotech_ingest` returns held or refused
  feedback unless exact-use admission and graph readback succeed.
