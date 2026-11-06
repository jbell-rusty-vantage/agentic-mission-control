# AI Engineer ingestion guide

Promoted from the `aieng_schema(section='guide')` result of the AI Engineer fixture bridge
(`tests/fixtures/aieng_knowledge.py`, `GUIDE`). The live guide returned by `aieng_schema` is
authoritative when the two differ.

Purpose: write verified AI Engineer knowledge (entities, identifiers, relationships and the
claims an independent judge fully supported). Read first, preview, then apply.

## Procedure

1. `aieng_knowledge_read`: resolve each intended subject (`entity.resolve {text}`,
   `entity.by_identifier {scheme, value}`); keep the returned `snapshot.snapshotId`.
2. Reuse existing entities with `mode='resolved'` and their `entityId`; create only what the read
   did not find (`mode='new'`, `onMatch='use_existing'` or `'review'`).
3. Read `evidence_report_read(section='frozen', json_pointer='/assertions')` and select only
   assertions whose judgments are all `full_support` (`claims[].assertionId`).
4. Author subjects and domain proposals (`relationship.assert`, `entity.identifier`,
   `entity.alias`, `fact.assert_state`, `event.assert`). Cite evidence as
   `[{claimId: <selected assertionId>}]`; the host binds the verification run.
5. `aieng_ingest(mode='preview')`: read `plan.errors`, failed `ruleChecks` and proposal outcomes;
   repair and preview again with the same report.
6. `aieng_ingest(mode='apply')` with the identical previewed `native_input`. KS seals, decides on
   the exact previewed effect and applies; the host reads rows back.

## Host-owned

- claim text and verdicts (copied from the frozen report);
- `claim.materialize`, `report.publish` and `support.admit` proposals;
- verification run, read snapshot, context, declared use and exact-use binding.

## Example `native_input` shape

Every string is a placeholder, never evidence.

```json
{
  "intentId": "author-a-unique-intent-id",
  "snapshotId": "COPY_FROM_aieng_knowledge_read",
  "subjects": [
    {
      "ref": "org",
      "mode": "new",
      "kind": "organization",
      "displayName": "AUTHOR_ACTUAL_ORGANIZATION_NAME",
      "identifiers": [{"scheme": "github", "value": "AUTHOR_ACTUAL_GITHUB_ORG"}],
      "onMatch": "use_existing",
      "evidence": [{"claimId": "COPY_A_FULLY_SUPPORTED_ASSERTION_ID"}]
    }
  ],
  "proposals": [
    {
      "proposalId": "org-develops-lib",
      "kind": "relationship.assert",
      "relationshipKind": "develops",
      "fromRef": "org",
      "toRef": "lib",
      "evidence": [{"claimId": "COPY_A_FULLY_SUPPORTED_ASSERTION_ID"}]
    }
  ],
  "claims": [
    {
      "assertionId": "COPY_A_FULLY_SUPPORTED_ASSERTION_ID",
      "claimType": "relationship",
      "subjects": [{"ref": "org", "role": "subject"}]
    }
  ]
}
```

## Rules

- Placeholders are not facts. Every value must be justified by a selected claim.
- Relationship kinds constrain endpoint entity kinds: read `section='relationship_kinds'`.
- Entity kinds and their typed payload columns: `section='entity_kinds'` and
  `section='relation', name='corpus/<kind>'`.
- A new subject carries its kind's NOT NULL typed columns in `typedPayload`, taken from evidence
  (for example `paper.title`; repository name, owner and host). Read
  `section='relation', name='corpus/<kind>'`; the host refuses a new subject without them.
- Never cite search or discovery listings; only judged assertions are evidence.
- `verify_evidence` is evaluation, not admission. `aieng_ingest` returns held or refused feedback
  unless exact-use admission, native apply and row readback all succeed.
