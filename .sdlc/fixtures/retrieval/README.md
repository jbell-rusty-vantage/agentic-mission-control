# Retrieval fixtures

Questions and tasks an agent with no context asks, each with the concepts, module guides, research notes and
facts a correct answer needs. They measure the documentation and its search (`docs/tools/okf_search.py`), not
the runtime. Run them with `python docs/tools/bench_retrieval.py` (add `--gate` in checks).

## Files

| File | What it is |
| --- | --- |
| `queries.json` | the cases |
| `baseline-before.json` | the run against the documentation before the refactor (commit `66185d2e`, the last commit before the OVE-206 truth pass) |
| `baseline.json` | the run after the refactor (2026-11-01): the baseline the next round must not fall below; its failing cases, five of them critical, are the next round's work |

## Case format

`{id, kind, partition, query|task, expect: {concepts[], modules[], research[], facts[]}, critical}`

- `kind`: `query` is a short question or keyword search; `task` is an owner-worded job whose answer needs several
  documents (concepts, module guides, research) and sometimes a fact that the documents must state.
- `partition`: `screening` cases may be used while changing the documentation or the search; `heldout` cases are
  read only to judge a change, never to tune it; `negative` cases are out of scope and search should return nothing.
- `critical`: a case that must pass; `--gate` fails when it fails and did not already fail in `baseline.json` (known failures are listed, not hidden).
- `expect.concepts` are slugs of `docs/knowledge/<slug>.md`; `modules` are code directories whose nearest
  `AGENTS.md` (at or above the directory) must be in the results; `research` are slugs under `docs/research/`;
  `facts` are statements the retrieved documents must contain, checked by the `fact_probes` substrings (all probes in
  one retrieved file). A slug that did not exist before the refactor cannot be found by the "before" run; that is
  intended.
- `gate` on a task case: `concepts_recall_at_10`, `modules_recall_at_10` and `facts: "all"` thresholds.

## Scoring

Query cases: hit@3 and hit@10 (any expected document in the top k) and the reciprocal rank of the first expected
document, averaged per partition. Task cases: set recall per `expect` field over the top 10. Negative cases pass
when search returns no result. A critical query passes at hit@3; a critical task passes when all its gate
thresholds hold.

## Rules

1. The baselines move only with a concept change in the same pull request: regenerate `baseline.json` with
   `python docs/tools/bench_retrieval.py --out .sdlc/fixtures/retrieval/baseline.json` and explain the movement.
2. Do not tune a case to pass. A failing case names a documentation gap (a missing concept, alias, question or fact)
   or a search gap; fix that, or record it as the next round's work.
3. New cases join `screening`; promote none to `heldout` after it has been used to tune anything.
4. Facts are checked by substring probes, which are weak: a pass shows the retrieved files mention the terms, not that
   they state the fact correctly. Read the document before trusting a pass.
