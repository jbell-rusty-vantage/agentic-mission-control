---
type: Concept
category: domain-model
title: Mission Manifest
description: The Mission Manifest YAML authoring surface (mission/v1 and mission/v2) as the one place a workflow is declared at the four levels (program behaviors and links, output promises, input bindings, per-node environment), how it lowers to a MissionDefinition and a family, the compile, submit and start verbs, lane admission and the launch bindings start needs.
tags: [mission-control, authoring, manifest, compile, lowering, implementation]
aliases: [mission.yml, mission/v2, manifest lowering, MissionDefinition, manifest compile submit start]
questions:
  - How do I write, compile and start a Mission Manifest?
  - How does a manifest declare scheduling, outputs, inputs and runtime for a workflow?
  - What does each manifest root behavior lower to?
  - Why does start fail with 409 start_unavailable?
  - Where do I search for capabilities and lanes before authoring?
updated: 2026-11-02
---

# Mission Manifest

The [Mission Manifest](../../GLOSSARY.md) (`mission.yml`, `manifest: mission/v1` or `mission/v2`, schema `mc.mission_manifest.v1`,
exported by `missionctl mission schema`) is the human and coordinator authoring surface for one mission or for `missions`
plus `links` (a chain, [mission chains](mission-chains.md)). It compiles into a [Mission Definition](../../GLOSSARY.md) and is
never the committed revision. It is parsed with YAML 1.2 core scalars; duplicate keys, floats and unknown keys are
rejected; every failure is a `(code, JSON pointer, message)` triple (`domain/authoring/manifest.py`). ADR-0022, ADR-0034,
SPEC-05. Coordinator authoring flow and the skill router are in [coordinator surface](coordinator-surface.md);
capability and lane search before authoring is the [Selection Workspace](selection-workspace.md) (`missionctl search`,
`workspace check`).

## 1. Scheduling: program behaviors and what they lower to

The `program` is a recursive tree of nodes with a `behavior` (`Behavior`, `domain/authoring/manifest.py:403`): `stage_graph, goal_loop,
parallel_swarm, evaluator_optimizer, agent_executor, deterministic_executor, event_wait, timer, human_gate, proof_gate,
child_mission_invocation`. `manifest_lowering.py` (pure, digest-stable) maps the root:

| Root behavior | Lowers to | Notes |
| --- | --- | --- |
| `goal_loop` | `GoalDirectedBlueprint` ([goal loop](goal-loop.md)) | obligations = the required goals; `action_space` aliases checked at compile |
| `stage_graph` | `StageGraphBlueprint` via `build_stagegraph_v2` ([stage graph](stage-graph.md)) | one stage per child; `depends_on`, `join`, `release_groups`, `routes`, `revisits`, `concurrency` |
| `parallel_swarm`, `evaluator_optimizer` (any position) | nothing: compile blocks `UNSUPPORTED_BEHAVIOR` `behavior_not_built` on every lane (`UNBUILT_PROGRAM_BEHAVIORS`, `application/authoring/manifest_service.py`; OVE-215, ADR-0068) | removed when WI-14/WI-15 build the lowering |
| anything else (`agent_executor`, `event_wait`, ...) | a one-stage Stage Graph whose stage is the root | |

A human gate or event wait child becomes a stage carrying a declared wait. A nested Goal Loop or Stage Graph is never
flattened: the stage carries a sealed `NestedBody` that runs as its own child run (`domain/authoring/manifest_lowering.py:5-15`,
[recursive composition](recursive-composition.md)); the earlier `nested_goal_loop_lowered_as_stage` warning is gone.
`governors` (`depth`, `fan_out`, `iterations`, `rounds`, `patience`, `transfers`, `domain/authoring/manifest.py:587`) and a Stage Graph's `concurrency` bound the program; `controls.subscriptions` register at start.

## 2. Output-contract obligations and 3. Context transfer

`outputs` declare exact promises (`form`, `enforcement`, `schema`, `coverage`, `requirements`; [output contracts](output-contracts.md))
and `criteria` map goals to evidence. `inputs: [{name, from: <producer>.<output> | artifact | value, expand, required}]` is both a dependency and an exact
transfer binding (`required: false` by authoring only); `completion` is a closed expression. A required goal no stage serves is
refused (`unowned_goal`). Lowering is deterministic onto the existing compiler; the committed Revision is the typed
`MissionDefinition@1` (`domain/authoring/mission_definition.py`), never the YAML ([revisions](revisions.md)).

## 4. Agent runtime and capability configuration

A mission-level [Environment](../../GLOSSARY.md) is inherited by every node (mappings deep-merge, lists and scalars replace,
narrowing only, provenance of every field recorded); a node `environment` overlays it: lane (never an execution binding),
model profile (a Model Catalog row such as `producer.default`, never a raw model id; [model catalog](model-catalog.md)),
sandbox, capabilities by `search` or `pin`, MCP servers, skills, subagents, hooks, `provider_options`. Resolution runs
through the single seam of ADR-0063 ([agent configuration](agent-configuration.md), [capabilities](capabilities.md)).

- **compile** (`application/authoring/manifest_service.py`, `POST /missions:compile`, `missionctl mission compile`, MCP
  `mission_manifest_compile`) is deterministic and persists nothing: checks `application` against the authenticated scope,
  expands plugins, resolves every `search` through [Hybrid Search](capabilities.md) to the top admitted hit
  (`CAPABILITY_UNAVAILABLE` when none, `ambiguous_search` within 0.05) and every `pin` to its exact row (`CAPABILITY_DRIFT`),
  computes effective environments, validates lane host support (a static `V2_LANE_BEHAVIORS` table derived from each lane's
  declared family support), hook events, coverage, budgets and depth, and compiles through the control plane against a
  dry-run overlay. Output: the Validation Report plus `mc.manifest_resolution.v1`. `--offline` runs only the structure compile.
- **submit** (`manifest_submit.py`, `POST /missions:submit`, MCP `mission_manifest_submit`, grants `workflow_run.admit` or
  `mission.author`) refuses on blockers, publishes lowered definitions and the Effective Run Configuration
  (content-addressed, idempotent), builds the Run Request as ordinary admission does and commits revision, typed
  definition rows, authoring provenance and the admitted run (or the chain with its first run) in one transaction
  (`adapters/postgres/control_plane/manifest_submission.py`). Idempotent on `request_id`; never starts anything.
- **start** (`POST /missions:start`, `missionctl mission start`, MCP `mission_run_start`, grants `workflow_run.start` or
  `mission.start`) registers `controls.subscriptions` and launches through `RunLaunchService`, writing `mc_mission_id` to the root.

**Start needs a deployment bindings file (B1, MP-02).** `ManifestLaunchInputAuthor` (`application/authoring/manifest_launch_inputs.py`,
composed by `bootstrap/manifests.py` for the API and the worker's chain relay) resolves each node's effective environment against the
operator-reviewed `mc.manifest_launch_bindings.v1` file at `MANIFEST_LAUNCH_BINDINGS_PATH` (Deep Agent profile scaffold and
placement, `model_profiles`, `sandbox_profiles`, catalog `capabilities` to exact MCP/Skill/tool components) and persists one
template per stage or Goal Loop role under `semantic-input:manifest:{run_id}`. Anything without an exact binding (a provider
lane without a `providers` entry, an unbound model, sandbox or capability, a missing credential name, hook scripts, plugins,
context bundles) fails `409 start_unavailable` before dispatch, at its pointer. Which pinned model serves each catalog row,
which sandbox backs `research.standard`, and which secret refs each lane may use are owner decisions in that file. Subagent
profiles and lane-keyed `provider_options` adapt per lane ([Deep Agents lane](deep-agents-lane.md)).

**mission/v2 (multi-provider).** `manifest_v2.parse_manifest_yaml_versioned` dispatches on the `manifest:` literal; v2 adds
`auth`, `execution_environment`, `workspace.policy`, `continuation`, `requires`, `materialization` and lowers through the same
`MissionDefinition@1`; each node gains additive `selections` (`mc.environment_selections.v1`). v2 inheritance forbids dropping
required features, widening egress, removing fail-closed hooks or raising `continuation.max_transfers`. **V01**: compile admits
each node role's `requires` against its lane's declared matrix (`admit_requirements`, `admit_gate_coverage`); refusals are
`UNSUPPORTED_BEHAVIOR` blockers at the manifest pointer. `claude_cloud`/`codex_cloud` compile with `hosted_launch_refused`
(evidence-blocked). **Provider and Cursor launch bindings** (`mc.manifest_launch_bindings.v2`, sealed `mc.execution_binding.v2`
for `claude_agent_sdk` and `codex`; `mc.cursor_binding.v2` for Cursor, pins `claude-agent-sdk 0.2.165`, `codex-cli 0.162.1`
(`adapters/codex/describe.py:67`), `cursor-sdk 1.0.37`) are specified in [provider lanes](provider-lanes.md) and
[cursor lane](cursor-lane.md); checked examples in `tests/fixtures/manifests/multi-provider/`.

Built / specified / goal: compile, submit and start for Stage Graph and Goal Loop roots built and tested on PostgreSQL and Temporal, integrated on paid Deep Agents fixtures; Swarm and EO nodes parse and are refused at compile (`behavior_not_built`, OVE-215); mid-run manifest mutation is a goal ([revisions](revisions.md)).

# Citations

- Spec: [SPEC-05](../specs/archive/fast-track-2026-10/SPEC-05-mission-manifest.md), [owner runbook](../specs/archive/fast-track-2026-10/OWNER-FIXTURE-RUNBOOK.md); ADRs [0022](../adr/0022-mission-manifest-yaml-authoring-surface.md),
  [0034](../adr/0034-mission-manifest-v1-settled-environment-inheritance-chains-agents-hooks.md), [0063](../adr/0063-one-resolution-seam-over-declared-lane-model-and-application-registries.md).
- Code: [manifest schema](../../src/mission_control/domain/authoring/manifest.py), [mission/v2](../../src/mission_control/domain/authoring/manifest_v2.py),
  [v2 admission](../../src/mission_control/application/authoring/manifest_v2_admission.py), [definition](../../src/mission_control/domain/authoring/mission_definition.py),
  [lowering](../../src/mission_control/domain/authoring/manifest_lowering.py), [compile](../../src/mission_control/application/authoring/manifest_service.py),
  [submit and start](../../src/mission_control/application/authoring/manifest_submit.py), [launch author](../../src/mission_control/application/authoring/manifest_launch_inputs.py),
  [provider launch](../../src/mission_control/application/authoring/provider_launch.py), [composition](../../src/mission_control/bootstrap/manifests.py),
  [PostgreSQL submit](../../src/mission_control/adapters/postgres/control_plane/manifest_submission.py), [routes](../../src/mission_control/interfaces/http/missions.py),
  [MCP tools](../../src/mission_control/interfaces/mcp/mission_tools.py).
- Tests: [schema](../../tests/unit/authoring/test_manifest_schema.py), [mission/v2](../../tests/unit/authoring/test_manifest_v2.py), [compile](../../tests/unit/authoring/test_manifest_compile.py),
  [v2 launch](../../tests/unit/authoring/test_manifest_v2_launch.py), [Cursor launch](../../tests/unit/authoring/test_manifest_cursor_launch.py), [interfaces](../../tests/unit/authoring/test_manifest_interfaces.py),
  [submit in PostgreSQL](../../tests/integration/postgres/test_manifest_submit.py), [v2 provider launch](../../tests/integration/temporal/test_manifest_v2_provider_launch.py),
  [lifecycle acceptance](../../tests/acceptance/mission_control/test_manifest_lifecycle.py); fixtures `tests/fixtures/manifests/`, goldens `tests/golden/manifests/`.
