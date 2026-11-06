---
name: report-source-procedure
description: Turn KS-captured model documentation into a producer-authored evidence report and MC submission, stopping before independent acceptance or native writes.
---

# Captured evidence to report submission

Read `/skills/report-source-procedure/references/START_HERE.md` and `/skills/report-source-procedure/references/SCHEMA_ROUTE.md`. The task is to compare what two sources
explicitly state about model parameter count. The agent chooses queries, source selections,
quotes, assertions, caveats and report prose. Do not infer missing numbers or equate active
and total parameters. The fixture supplies procedure and bounded context, not the answer.

1. Inspect host-provided tools, bindings, run identity and output obligations. Record a
   short plan. Skills grant no tools, credentials, database rights or publication authority.
2. Discover using exactly one host-selected route: managed KS discovery OR direct provider
   tools plus KS import. Preserve attempt/selection receipts, including omitted candidates.
3. Follow `knowledge-verify` for capture/read/search/locate. Record captured byte identities,
   final URLs, exact quotes and resolved selectors. Discovery artifacts are preserved for
   provenance but must not be mislabeled as evidentiary captures.
4. Require a host-supported, tested conversion from capture/locator receipts into the exact
   K01 fragment references. These services may use different custody stores. If that bridge
   is absent or a digest cannot be read back, stop with `capture_to_report_bridge_unproved`.
   Do not repair it by replacing bytes or inventing K01 references.
5. Read the report, fragment, assertion, support-set and task contracts under `/skills/report-source-procedure/references/context/`.
   Author two to four source-attributed claims and an evidence_report body. Use captured
   selectors as support; distinguish unsupported statements and report missing information.
   Entity labels are descriptive navigation hints, not new canonical entities or guessed IDs.
6. Call the admitted `report_register` tool with task, fragments, assertions, supportSets
   and report. Host scope, digests and pin authority stay host-owned. The first report has
   revision 1 and no predecessor. Correct structured refusals within a maximum of three
   attempts. Use fresh IDs for changed immutable records; identical retries reuse their call ID.
7. Submit the returned report handle and digest to the discovered report obligation via
   `submit_output`. Preserve registration and submission receipts and typed findings.
   Acknowledgement means recorded/submitted; this fixture does not claim independent acceptance.

Stop at submission. Return a compact trace from discovery attempt → selection → capture →
located fragment → assertion/support → report receipt → submission receipt. Leave any broken
edge explicitly unmet. No native entity writes, ingestion, publication or consumer stage.
