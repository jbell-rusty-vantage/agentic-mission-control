# Mission Control documentation

The code is what runs, the [decision records](adr/) are what was decided, and the [knowledge concepts](knowledge/index.md) explain both.
Program ledgers under `specs/` are working documents. The origin specification pack `mission-control-general/` was deleted on
2026-11-01 (last at commit `66185d2e`).

- [Glossary](../GLOSSARY.md): the shared language; use its terms and honour its Avoid lists.
- [Decision records](adr/): why the architecture is the way it is; numbered, short, with status.
- [Knowledge bundle](knowledge/index.md): application logic and source/test navigation (Open Knowledge Format), grouped in nine
  categories; [research notes](research/) back the decisions with dated provider facts.
- [Agent process config](agents/): issue tracker (Linear), triage labels, domain-doc rules, program workspaces and documentation surfaces.
- [Developer tooling](DEVELOPMENT.md): the Makefile and tool roles. [Operator guide](MISSION_CONTROL_LOCAL_API.md): configured API,
  worker, identity and roles. [WSL2 worker runbook](WSL2_WORKER_RUNBOOK.md): Windows host with a WSL2 worker for the local provider
  lanes. [Report/source foundation](REPORT_SOURCE_FOUNDATION.md): the Sprint OC fixture procedure.
- [Deployment options report 2026-10-12](DEPLOYMENT_OPTIONS_2026-10-12.md): where the API, MCP, workers, Agent Server and provider lanes
  can run, superseded in part by the Sprint OC cloud roadmap (see the [deployment concept](knowledge/deployment.md)).
- Active programs (each read through its `LEDGER.md`): [provider consolidation](specs/provider-consolidation-2026-10/LEDGER.md) (Deep
  Agents first; the Sprint OC control board is `sprint-oc/NEXT-SESSION.md`), [Agentic SDLC](specs/agentic-sdlc-2026-11/LEDGER.md) (the
  documentation and lifecycle system, including this truth pass), [coordinator surface](specs/coordinator-surface-2026-10/LEDGER.md),
  [proposals](specs/proposals-2026-10/LEDGER.md) (unbuilt: provider batch, the human review loop, next-stage contracts) and the
  parked [fault tolerance](specs/fault-tolerance-2026-10/LEDGER.md).
- [Specification archive](specs/archive/README.md): finished programs and documents (the fast-track, multi-provider and
  materialization-observation packets, the dated implementation status, the removal guide and the two-project rollout plans);
  provenance only.
- Tools (`tools/`): `okf_search.py` searches the corpus, `validate_okf.py` validates the bundle, `agents_docs_index.py` regenerates the
  marked blocks of the root `AGENTS.md` and `knowledge/index.md`, `okf_frontmatter.py` adds frontmatter to new documents,
  `check_links.py` checks links, `program_ledger.py` checks a program's `LEDGER.md` and archives finished documents,
  `check_docs.py` runs them all, and `bench_retrieval.py` scores the retrieval fixtures in `../.sdlc/fixtures/retrieval/`.
  Conventions: [documentation surfaces](agents/documentation-surfaces.md), [program workspaces](agents/program-workspace.md),
  [Matt Pocock skills](agents/matt-pocock-skills.md).
