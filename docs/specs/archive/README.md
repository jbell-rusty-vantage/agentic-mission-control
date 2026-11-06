---
type: Archive Index
title: "Specification archive: finished programs and finished documents, in one place"
description: "The single archive for docs/specs: whole programs that are finished (table below, each keeps its internal structure) and, under archive/<program>/<kind>/, single documents archived out of an active program (found through that program's LEDGER.md). Nothing here is executed, loaded by tests, or indexed in AGENTS.md; code and ADRs are the current authority."
tags: [mission-control, archive, provenance]
---
# Specification archive

One archive for everything under `docs/specs/`. Owner decision 2026-10-23.

| Holds | Where | Found through |
| --- | --- | --- |
| A finished program | `archive/<program>/`, original structure kept | The table below |
| A finished document of an active program | `archive/<program>/<kind>/<file>.md`, kinds: proposals, docs, specs, issues, interview-instructions, interview-answers, sessions | The `archived` row in that program's `LEDGER.md` |

Rules:

- **Inert.** No test, code path or tool reads a file here. Files a test loads (mission manifests) live under `tests/fixtures/`.
- **Provenance only.** Where an archived document disagrees with the code, an ADR or an OKF concept, those win ([precedence](../../../AGENTS.md)).
- **Move with the tool.** `python docs/tools/program_ledger.py archive-program docs/specs/<program> --reason "..."` or `archive <file> --kind <kind>`; both rewrite links and add the entry. Convention: [program-workspace.md](../../agents/program-workspace.md).
- **Not indexed.** The compiled index in `AGENTS.md` lists one line for this folder; use search (`python docs/tools/okf_search.py`) or the table.

## Finished programs

| Program | Archived | Why |
| --- | --- | --- |
| [fast-track-2026-10](fast-track-2026-10/README.md) | 2026-10-23 | completed packet; owner archived it whole 2026-10-23 |
| [multi-provider-2026-10](multi-provider-2026-10/README.md) | 2026-10-23 | completed packet; handoffs historical; owner archived it whole 2026-10-23 |
| [materialization-observation-2026-10](materialization-observation-2026-10/README.md) | 2026-10-23 | Run 2 finished 2026-10-20 and integrated on main; owner archived it whole 2026-10-23 |
<!-- archived-programs:end -->

## Finished document sets (2026-11-01, OVE-206)

| Set | Where | What it holds |
| --- | --- | --- |
| Mission Control surfaces | [mc-surfaces-2026-10](mc-surfaces-2026-10/README.md) | dated implementation status, removal guide, lifecycle report, the two-project rollout plans, eight qualification files, the cloud-runtime approval plan, an experiment handoff and the archived test notes; each file's original path is in its README |
| Coordinator MCP plans | [coordinator-surface-2026-10/mcp-plans](coordinator-surface-2026-10/mcp-plans/COORDINATOR_ARCHITECTURE_AND_PLAN.md) | ten July 2026 implementation plans that sat inside `src/mission_control/interfaces/mcp/`; reasoning for coordinator round R8 |
| Provider consolidation, finished documents | [provider-consolidation-2026-10](provider-consolidation-2026-10/docs/SPRINT-OC-LOG-2026-10-29-31.md) | kind folders (`proposals`, `docs`, `specs`, `interview-instructions`, `sessions`), `sprint-v/`, `sprint-oc/provenance-2026-10-31/` and `answer-sets/` (five interview answer sets with their working files); every row is `archived` in the program ledger |
| Spec pack | git history only | `mission-control-general/` was deleted on 2026-11-01; read it with `git show 66185d2e:mission-control-general/<path>`; its contracts are in the ADRs and `docs/knowledge/`, its product ideas in [SPEC-PACK-IDEAS](../proposals-2026-10/SPEC-PACK-IDEAS-2026-11.md) |

## Sealed artifacts that cite old paths

Some artifacts are digest-pinned or applied to live projects and cannot be edited in place: the catalog seed bundles under `packages/mission-control-db-contract/seeds/` (and the `tests/fixtures/mcp/*.json` they are built from), the skill bundle sources under `packages/mission-control-db-contract/bundle-sources/`, and the shipped bundles under `skills/`. They cite packet documents as `docs/specs/<packet>/...` from before 2026-10-23. **Read any such path as `docs/specs/archive/<packet>/...`** (and, since 2026-11-01, `docs/specs/provider-consolidation-2026-10/SPRINT-V-DESIGN.md` as `archive/provider-consolidation-2026-10/specs/SPRINT-V-DESIGN.md`; `sprint-oc/PROOFS.md` is still in place; the lane describe strings and migrations 0033, 0040 and 0046 cite the deleted `mission-control-general/` files, readable at commit `66185d2e`): the three archived packets are `fast-track-2026-10`, `multi-provider-2026-10` and `materialization-observation-2026-10`, and their mission manifests moved to `tests/fixtures/manifests/`. The strings are corrected when each seed or bundle next gets a version for another reason (owner decision 2026-10-23).

Where each program's outcome lives now: fast-track is cited by ADRs 0023-0032 and the knowledge concepts for capabilities, context, manifests, chains, interventions and the Cursor lane; multi-provider by ADRs 0035-0041 and [the release qualification](mc-surfaces-2026-10/docs/qualification/release/multi-provider-2026-10.md); materialization-observation by ADRs 0042-0053 and its completion summary and finish disposition under `materialization-observation-2026-10/runs/`.
