# Report/source context profiles

These versioned fixture profiles compose shared Knowledge Services operational report,
fragment, assertion, support and task contracts with read-only domain navigation. They
grant no native ingestion authority and do not establish W1/W2 qualification.

From Mission Control, after the normal BKS `pnpm build`:

```powershell
python scripts/report_source_context.py --profile ai-engineer --out .scratch/foundation-aie
python scripts/report_source_context.py --profile biotech --out .scratch/foundation-biotech
```

Each output must be fresh. The composer invokes the existing AIDB scope CLI or BKS slice
CLI against canonical committed workspaces. It does not query databases or load schema
IR itself. AIDB retains all vocabularies: these remain in hashed materializer evidence,
while only the selected task cards enter the runtime context. Their omitted links are
explicit navigation references, not missing operational contract definitions. BKS slice
closure, omissions, mandatory rules and its noncompileable advisory status are preserved.

Shared source dependencies resolve recursively from canonical KS TypeScript, including
named protocol exports. Missing modules/symbols fail closed. External `zod` and
`node:crypto` references remain explicit. The complete qualifier discriminator and the
report port's derivation types are retained dependencies, not permission to derive/apply.

`manifest.json` records source and artifact fingerprints, selection, omissions, exact
file digests and actual UTF-8 context bytes. `shared/` preserves raw canonical bytes;
`context.txt` is the separately digested `utf8-lf.v1` representation so the Deep Agents
text backend can read it exactly. A hard 196,608-byte ceiling applies to the complete
runtime context, not merely the domain slicer's token estimate. No token-fit claim is made.

Consumers call `verify_context(output, expected_manifest_digest)` with the digest retained
at materialization and read `context.txt`. The manifest's self-digest alone is integrity
checking, not external authentication. Unit tests exercise tamper/missing/budget refusal;
the Deep Agents integration test invokes the real backend and paginates every line,
reassembles exact bytes, and checks its delivery receipt using a local scripted model.
That test establishes context delivery, not semantic understanding, independent judgment,
remote services, search acquisition or native application.
