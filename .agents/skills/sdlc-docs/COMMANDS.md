# Commands per repository

The repository's `AGENTS.md` **Verify** line is authoritative; this table is the map as of
2026-11-02. When the `sdlc` CLI (slice S1) is vendored, every row becomes `node .sdlc/cli.mjs <cmd>`.

| Repository | Search | Regenerate AGENTS.md and index | Checks | Bench |
| --- | --- | --- | --- | --- |
| `platform/mission-control` | `python docs/tools/okf_search.py "<terms>"` | `python docs/tools/agents_docs_index.py` (`--check`) | `python docs/tools/check_docs.py`; `python docs/tools/program_ledger.py check --program <dir>` | `python docs/tools/bench_retrieval.py --gate` (`--out` to re-record) |
| `platform/knowledge-services` | `node .agent-docs/knowledge.mjs search "<terms>"` / `context "<question>"` | `node .agent-docs/cli.mjs build --repo .` | `node .agent-docs/cli.mjs check --repo .` | `node .agent-docs/retrieval-benchmark.mjs` |
| `biotech/biotech-knowledge-services`, `aiengineer/ai-engineer-db-contract` | grep `docs/`; the agent-docs CLI where present | `node .agent-docs/cli.mjs build --repo .` where present | the repository's own check | none yet |
| after S1, every repository | `node .sdlc/cli.mjs search` / `context` | `node .sdlc/cli.mjs build` | `node .sdlc/cli.mjs check` | `node .sdlc/cli.mjs bench --gate` |

Cross-repository: today, open the sibling checkout's `AGENTS.md` (the `applications` or boundaries
concept names it); after S1, `search --workspace`.
