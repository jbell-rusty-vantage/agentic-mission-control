---
name: tavily-discovery
description: Find candidate primary model sources with an admitted Tavily tool for the report-source partial fixture; preserve discovery receipts before KS capture.
---

# Tavily discovery — fixture adapter

This is BellLabs fixture guidance, not the upstream Tavily skill distribution. Read
`/skills/report-source-procedure/references/START_HERE.md` first. Use only the Tavily search tool actually admitted by the host;
inspect its live input schema rather than guessing arguments from the historical snapshot.
No tool installed means stop at discovery preflight, not simulate a successful search.

Search for official model documentation about the assigned parameter-count property. Start
with one narrow query; inspect identity, version and whether the number is total or active
parameters. Prefer original documentation to summaries. Choose up to two sources and explain
selection, omissions and uncertainty. Use at most three queries across all discovery providers.

Keep raw provider output as a discovery receipt with the host's custody service. A direct
Tavily/MCP call is an external, self-reported attempt when imported into KS; it is not a
managed KS dispatch. If the host instead selects managed KS discovery, do not also call
Tavily directly. Record failures and exhausted budgets; they are not evidence of absence.

Search snippets and extracted previews are leads. Pass selected URLs to the KS capture
procedure. Never manufacture capture IDs or use preview text as captured evidence. Do not
read credentials, install packages, crawl whole sites or silently switch provider routes.
