---
type: Archive Index
title: "Archived Mission Control surfaces (2026-10), moved 2026-11-01"
description: "The dated reports, finished plans, qualification files, experiment handoff and test notes that sat beside the live guides in docs/, deployments/, experiments/ and tests/, archived by the documentation truth pass (OVE-206). Inert provenance; each file keeps its original relative path under this folder."
tags: [mission-control, archive, provenance]
---
# Archived Mission Control surfaces

Moved with `program_ledger.py move` on 2026-11-01 (OVE-206, truth pass part D). Nothing here is loaded by code or tests. Where an
archived file disagrees with the code, an ADR or a concept, those win. The ten coordinator MCP implementation plans that were
archived in the same pass are in [coordinator-surface-2026-10/mcp-plans](../coordinator-surface-2026-10/mcp-plans/COORDINATOR_ARCHITECTURE_AND_PLAN.md).

| Archived path (under this folder) | Original path | Why |
| --- | --- | --- |
| `docs/MISSION_CONTROL_IMPLEMENTATION_STATUS.md` | `docs/MISSION_CONTROL_IMPLEMENTATION_STATUS.md` | marked stale 2026-11-01, nothing after 2026-10-24; the concepts and ADRs replace it in the authority chain |
| `docs/REMOVAL_GUIDE.md` | `docs/REMOVAL_GUIDE.md` | provenance of the 2026-10-03 clean break |
| `docs/LIFECYCLE_RELIABILITY_2026-10-11.md` | `docs/LIFECYCLE_RELIABILITY_2026-10-11.md` | dated handoff, no inbound links |
| `docs/plans/mission-control-two-project-rollout/` (4 documents, 3 JSON) | same path | finished 2026-10-03/12 |
| `docs/qualification/lanes/claude_cloud/`, `codex_cloud/` (feasibility and revalidation) | same path | outcome 3: not admitted; decision provenance |
| `docs/qualification/local-profiles/` | same path | multi-provider era readiness |
| `docs/qualification/parity/multi-provider-2026-10-09.md`, `docs/qualification/release/multi-provider-2026-10.md` | same path | the multi-provider packet, archived 2026-10-23 |
| `docs/qualification/two-project/LIVE_PLAN.md` | same path | titled "awaiting owner approval" although the install ran 2026-10-03 |
| `experiments/LANGGRAPH_TEMPORAL_DEEPAGENTS_STAGEGRAPH_EXPERIMENT_HANDOFF.md` | same path | experiment brief, no links |
| `deployments/cloud_runtime/APPROVAL_PLAN.md`, `INVENTORY.md` | same path | 2026-10-11 Lightsail proposal and inventory; they hold identifiers, not secrets |
| `tests/archive/` (2 documents) | same path | self-described stale notes |
