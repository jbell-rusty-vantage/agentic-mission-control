# Deep Agents lane agent guide

This adapter is the first execution lane (ADR-0005): bounded operation cognition on Deep Agents
0.7.5 over LangGraph, extended through public interfaces, never forked. Read the root
`GLOSSARY.md` (Lane, Harness, Execution Binding, Materialization, Subordinate) and
`docs/knowledge/lanes-and-harness.md` first.

## Where things are

| Concern | Start |
| --- | --- |
| Compile a node through the resolution seam (ADR-0063); the package registration | compile.py (`DeepAgentsCompileAdapter`, `deep_agents_lane`), lane.py (`DeepAgentsLaneAdapter`: children, options, receipt), binding.py (the lane's own bytes: seal, unseal and envelope check, the template step and the per-attempt rebind) |
| The lane's describe matrix and `LaneDeclaration` (pure data the application aggregates) | describe.py |
| The harness protocol over the runtime adapter; its Host Projection writer | harness.py (`DeepAgentsHarness`), host_files.py |
| Run an operation; observe; cancel | adapter.py (`DeepAgentRuntimeAdapter`) |
| Turn an execution binding into a real agent, model client and sandbox | materializer.py (`ExactDeepAgentMaterializer`, model factory, State and LangSmith sandbox factories); the Docker factory is docker_sandbox.py; Daytona is admitted by the contract but has no factory ([deep agents lane](../../../../docs/knowledge/deep-agents-lane.md)) |
| Async subordinates and parent effects | async_subagents.py; application/subordinates |
| Checkpoints, lineage and verification | checkpoint_history.py, checkpoint_reads.py, checkpoint_verifier.py; domain/execution/checkpoint_lineage.py |
| LangGraph saver/store in the runtime schema | persistence.py, runtime_persistence_verifier.py |
| Capability lineage recorded on the attempt | capability_lineage.py |
| Provider frames (Native Event Store, SPEC-03) from `astream` v2 parts | frames.py; application/frames |
| Browser and Docker sandbox tools | browser_tool.py, docker_sandbox.py |

## Invariants

The adapter executes what the binding pins and refuses mismatches; it never chooses a model,
tool or skill the binding did not name. Model clients and capability credentials stay
server-side; nothing secret enters prompts, files, checkpoints or artifacts. Deep Agents
schedules nothing: Temporal owns scheduling, the reducer owns lifecycle, and native messages
or checkpoints are recovery state, not mission truth (ADR-0004, ADR-0007). An uncertain
provider state is reconciled, never re-launched. Fork only through the ADR-0005 dossier.

## Verify

`uv run pytest tests/integration/deep_agents` (needs the real local stack) plus the unit
selections under tests/unit that name deep agents, materialization and subordinates;
`uv run mypy src/mission_control` and `ruff check`. Paid provider calls need authorization.

<!-- BEGIN:sdlc-module id=adapters.deep_agents -->
## Deep Agents lane adapter
Deep Agents lane (ADR-0005): bounded cognition over LangGraph, never forked. It runs on deepagents extended through public interfaces, executes what the binding pins and schedules nothing.
Entrypoints:
- compile.py — The Deep Agents lane's compile and its package registration
- lane.py — Deep Agents lane adapter: a compiled node configuration → the Deep Agents exact…
- binding.py — The Deep Agents lane's own bytes: seal, unseal, template and rebind
- describe.py — The Deep Agents lane's declared describe matrix and declaration
Also: harness.py, adapter.py, materializer.py, docker_sandbox.py, hooks.py, budget.py, async_subagents.py, time_travel.py, routes.py, frames.py, evaluators.py, cognition_points.py, compaction.py, features/, workspace_closure.py, child_binding.py, output_format.py, hook_contributions.py (+15)
Tests: tests/unit/deep_agents, tests/integration/deep_agents, tests/conformance/lanes
Invariants:
- Never choose a model, tool or skill the binding did not name; refuse mismatches.
- Model clients and credentials stay server-side, never in prompts, files, checkpoints or artifacts.
- An uncertain provider state is reconciled, never relaunched; checkpoints are recovery state, not mission truth.
Explained by (docs/knowledge): deep-agents-lane, agent-configuration, budgets-and-usage, deep-agents-children, hook-contributions, model-catalog
Decided by (docs/adr): ADR-0006, ADR-0063, ADR-0005, ADR-0011, ADR-0017
Depends on: domain, application, domain.execution, domain.authoring, contracts, domain.frames (+4) · Used by: bootstrap, adapters.temporal, adapters.agent_server, adapters.capabilities, application
Verify: uv run pytest tests/unit/deep_agents tests/conformance/lanes; uv run pytest tests/integration/deep_agents (real local stack; paid calls need authorization)
Program: docs/specs/provider-consolidation-2026-10/providers/deep_agents/CHANGES.md
<!-- END:sdlc-module -->
