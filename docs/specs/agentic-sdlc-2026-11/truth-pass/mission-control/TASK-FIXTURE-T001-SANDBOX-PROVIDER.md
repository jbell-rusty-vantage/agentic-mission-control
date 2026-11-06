---
type: Working Draft
title: "Task fixture T001: add a sandbox provider configuration to Deep Agents across active workflow types"
description: "The first task-shaped retrieval fixture (AS-D32), run 2026-11-01 against today's Mission Control search (okf_search.py): the task, what an agent needs (ground truth from the code), what search returned, set recall, and the hidden gap facts a task fixture must surface."
tags: [mission-control, truth-pass, retrieval, fixtures, sdlc]
date: 2026-11-01
status: draft
---

# T001: add a sandbox provider to Deep Agents across active workflow types

**Task (owner's words):** "Add a new sandbox provider configuration to deep agents and make sure it
works across all active workflow types".

## Ground truth: what the agent must reach (from the code, 2026-11-01)

| # | Kind | Item | Why the task needs it |
| --- | --- | --- | --- |
| G1 | code | `src/mission_control/domain/execution/contracts.py:684` `DeepAgentSandboxComponent` (`backend: Literal["langsmith","daytona","docker","state"]`), `:1207` `sandbox_backends` | the contract a new backend must join |
| G2 | code | `src/mission_control/application/authoring/manifest_launch_inputs.py:514` `sandbox_profiles`; `deployments/examples/manifest-launch-bindings.deep-agents.example.json` | the operator-facing configuration |
| G3 | code | `src/mission_control/adapters/deep_agents/compile.py:565-582` | where a node's `sandbox_profile` is resolved |
| G4 | code | `src/mission_control/adapters/deep_agents/materializer.py:18,294,491-510`, `docker_sandbox.py` | the factories; a new provider needs one |
| G5 | code | `src/mission_control/adapters/deep_agents/describe.py:131-153` | the lane capability matrix (`sandbox_profile: native`) |
| G6 | code | `src/mission_control/domain/execution/workspace_closure.py:45`, `adapters/deep_agents/workspace_closure.py:97` | closure capture per backend |
| G7 | code | `src/mission_control/application/environments/network.py` | network tiering per sandbox provider |
| G8 | code | `src/mission_control/bootstrap/preflight.py:533` | the worker must serve the sandbox digest |
| G9 | code | `src/mission_control/domain/frames/body.py:41` | provider API key names redacted from frames |
| G10 | code | `src/mission_control/adapters/agent_server/async_subagents/bindings.py:254` | async children carry their own sandbox profile |
| G11 | code | `src/mission_control/application/selection/workspace.py:79-116,587-616` | Selection Workspace `sandbox_profile` facet |
| G12 | tests | `tests/conformance/lanes/compile/deep_agents.py`, `tests/unit/authoring/test_manifest_launch_inputs.py`, `tests/acceptance/mission_control/test_overnight_stagegraph.py`, `test_manifest_async_child.py`, `tests/integration/temporal/test_manifest_launch_production.py` | "works across all active workflow types" = StageGraph and GoalDirected (Goal Loop) runs plus async children |
| G13 | concept | `deep-agents-lane`, `agent-configuration`, `environments`, `workspace-closure`, `async-children`, `selection-workspace`, `workflow-systems` (which systems are active) | the why and the contracts |
| G14 | research | provider facts for the new sandbox (e.g. Daytona tiers, network policy) | `network.py:31` cites `research/daytona.md`, **which does not exist** |
| G15 | module block | `src/mission_control/adapters/deep_agents/AGENTS.md:16,22` | the file-role table that names the factories |

**Hidden gap facts a good answer must surface:**
- H1: `daytona` is admitted by the contract (G1), handled by closure (G6) and network (G7), redacted
  (G9), but **has no factory in the materializer** (G4 has zero `daytona` matches). The concept says
  factories are State, LangSmith and Docker (`deep-agents-lane.md:29-31`); nothing says Daytona is
  half-wired.
- H2: only StageGraph and GoalDirected run today; Parallel Swarm and Evaluator Optimizer are not in
  primary (`workflow-systems.md`), so "all active workflow types" means two systems plus async children.
- H3: the research note the code cites is missing (G14).

## What today's search returned

`python docs/tools/okf_search.py "<task>" --limit 10`:

| Rank | Document | In ground truth? |
| --- | --- | --- |
| 1 | `mission-control-general/.../SPECIFICATION.md` | no (normative history) |
| 2 | `workflow-types/08-CONTINUATION_COMPACTION_AND_TRANSFER.md` | no |
| 3 | `runtime-facts/EVE_FACTS.md` | no |
| 4 | `general-mission-control/DOCUMENTATION-CLEANUP.md` | no |
| 5 | `expansion/ARCHITECTURE-AND-ADRS.md` | no |
| 6 | GLOSSARY "Mission Control" | no |
| 7 | `docs/knowledge/deep-agents-lane.md` | **yes** (G13) |
| 8 | `sprint-oc/NEXT-SESSION.md` | weak |
| 9 | `docs/knowledge/operations.md` | no |
| 10 | `general-mission-control/RUNTIME-CONTRACTS.md` | no |

Decomposed queries did better ("agent configuration manifest deep agents" → `agent-configuration`,
`deep-agents-lane`, Resolution Seam, `model-catalog`, `async-children`; "environment preparation
sandbox" → `environments`, ADR-0042, `environment-preparation`), but an agent must already know the
decomposition.

**Set recall at 10 for the whole task:** concepts 1 of 7; code entrypoints 0 of 11 (code and module
blocks are not in the corpus); research 0 of 1; hidden facts 0 of 3. Precision at 5: 0.

## Causes

1. The `mission-control-general` spec pack dominates long queries (dense, vocabulary-rich, historical).
2. No code-entrypoint documents: module `AGENTS.md` blocks and `modules.json` entrypoints are not indexed.
3. No research dimension: the Daytona note the code cites is absent.
4. No concept states the half-wired backend (H1); a freshness check comparing the concept's factory list
   with the materializer would have caught it.
5. Long natural-language tasks are not decomposed; `context` should expand a task into facets
   (lane, configuration, environment, workflow systems, tests) before ranking.

## As a fixture (proposed `kind: task` case)

```json
{
  "id": "T001",
  "kind": "task",
  "task": "Add a new sandbox provider configuration to deep agents and make sure it works across all active workflow types",
  "expect": {
    "concepts": ["deep-agents-lane", "agent-configuration", "environments", "workspace-closure", "async-children", "selection-workspace", "workflow-systems"],
    "modules": ["src/mission_control/adapters/deep_agents", "src/mission_control/domain/execution", "src/mission_control/application/authoring", "src/mission_control/application/environments"],
    "research": ["deep-agents/sandbox-providers"],
    "facts": ["daytona admitted by contract but no materializer factory", "active systems: StageGraph, GoalDirected"]
  },
  "gate": {"concepts_recall_at_10": 0.7, "modules_recall_at_10": 0.75, "facts": "all"},
  "critical": true
}
```
