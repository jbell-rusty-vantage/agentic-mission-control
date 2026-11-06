---
type: Concept
category: domain-model
title: Mission chains (linked workflows)
description: How a manifest with missions and links compiles into independent missions joined by typed links, how the chain reducer releases the next mission through the outbox in the commit that satisfies the link, what exact exports transfer, what is never adopted, cancellation policy and the production relay; plus Child Mission Invocation, Portals and Spawn Grants as specified-not-built.
tags: [mission-control, chains, mission-chain, linked-workflows, outbox, reducer, implementation]
aliases: [linked workflows, chain links, linked missions, mission chaining, child mission invocation]
questions:
  - How does one mission release the next and transfer state?
  - What exactly does a chain link transfer and does it adopt obligations?
  - What happens to a running consumer when its upstream mission is cancelled?
  - How do I author two linked workflows in one manifest?
  - Is Child Mission Invocation or a Portal built?
updated: 2026-11-01
---

# Mission chains (linked workflows)

The owner's phrase "linked workflows" is the glossary's [Mission Chain](../../GLOSSARY.md): an ordered set of missions
authored in one manifest and joined by [Chain Links](../../GLOSSARY.md). Each member is a whole mission with its own
revision, run, budget, grants and acceptance; nothing is shared except what a link transfers. Decision: ADR-0029.
Links stay inside one application and qualify separately for AI Engineer and Biotech. Compile and submit belong to
[mission manifest](mission-manifest.md); the system comparison is in [workflow systems](workflow-systems.md).
Do not confuse chains with the lower-level *linked runs* a family can launch as a unit (`application/programs/linked_runs.py`,
workflow `LinkedRunWorkflow`; the manifest lowers one `manifest_link` slot, `domain/authoring/manifest_lowering.py:339`), or with nested
bodies ([recursive composition](recursive-composition.md)).

## 1. Scheduling

**Contracts.** `mc.chain.v1` and `mc.chain_link.v1` (`domain/composition/chain.py:134`; JSON schemas under
`contracts/schemas/`). A link has kind `supplies` or `depends_on`, typed `bindings`, a `ReleaseCondition`
(`goal_accepted{goal_key}`, `mission_accepted` or `execution_complete`) and `on_upstream_cancel`:

<!-- snippet: src/mission_control/domain/composition/chain.py:94-98 -->
```python
class OnUpstreamCancel(StrEnum):
    CONTINUE = "continue"
    CANCEL_DOWNSTREAM = "cancel_downstream"
    DETACH = "detach"

```

`compile_chain` validates the link graph and bindings against the parsed manifest and returns the topological order
and blockers with JSON pointers (`application/chains/service.py::ManifestStructureService`).

**Release through the outbox.** `ChainReleaseHook` (`adapters/postgres/chains/store.py`) is the post-append hook of
`canonical.append_events`. On the same connection, before the ledger commit, it runs the pure
`ChainReducer` (`application/chains/reducer.py`) over chain rows and the supplier run's state and applies the
transition: link and chain state (compare-and-swap), the consumer's admission from its frozen request (receipt, run,
budget, effect ledger), the sealed link packet, `mission_relationship` rows, the `mc.chain.start_run` /
`mc.chain.cancel_run` outbox intents and the `chain_link.released|blocked|detached|cancelled` and `chain.completed`
events. Link states are forward-only (`armed` to `released`, `blocked`, `detached` or `cancelled`), enforced by a
trigger. A `supplies` link also waits for accepted output evidence; a terminal supplier that does not satisfy the
condition blocks it (`upstream_not_accepted`, `upstream_execution_failed`); a consumer is admitted when every
incoming link is released (`consumer_already_started` blocks). A replayed commit reaches the same decision.

**Production relay.** The worker runs `ChainRelayPump` when `CHAIN_RELAY_ENABLED=1` (`bootstrap/worker.py`); it
leases intents and starts the consumer through `ChainLaunchInputPort` over `ManifestChainLaunchInputs`, refusing
startup without `MANIFEST_LAUNCH_BINDINGS_PATH`. A redelivered start attaches to the consumer's existing workflow.

**Cancellation.** The default `on_upstream_cancel` is `continue` (release 1.10.0): an already-running consumer
finishes on its valid sealed inputs; `cancel_downstream` propagates governed cancellation (a consumer that never
started is closed with zero cognition and no liabilities); `detach` severs. Spawned children keep parent-cancel,
attached missions keep detach; not-yet-started consumers still need their release gates. Reading: `GET
/v1/applications/{app}/chains/{chain_id}`, `missionctl chain inspect`, MCP `mission_chain_inspect`.

## 2. Output-contract obligations

Delivery never adopts obligations. A binding reads the promise the supplier's root output is: a Goal Loop root's own
`<root>.<output>`, or for a Stage Graph root the producing stage's promise at that stage (`source_position` is the
stage, `output_key` `<stage>.<output>`; `domain/composition/chain.py::_supplier_promise`, OVE-169). A `supplies` link releases after owning-Goal acceptance (or explicit Mission
Acceptance) plus the receiver's use eligibility; an explicitly authorized *repair/review* link
(`receiving_purpose: repair`, `selector: finalized_snapshot`, `on: execution_complete`) may deliver exact held
or draft exports with status and findings intact, and required repair bytes stay required. Adoption is a separate
host act: `LinkedOutputAdoptionService` re-submits the exact source revision through the ordinary submission act
under the receiver's invocation, preserving the original producer; the receiver's assessment, promotion and
fulfillment still decide (`application/outputs/linked_adoption.py`, `adoption.py`). Launch readiness, child
execution completion, result eligibility, parent fulfillment and final acceptance are distinct. See
[output contracts](output-contracts.md).

## 3. Context transfer

At release the store creates export authority (`linked.export/1` documents, migration 0068, with a receiver index)
and the consumer's first Context Packet (`purpose: chain_link`, `application/chains/packet.py`): per supplied
output the artifact as a `chain_supply` item bound `<from_mission_key>.<output_name>`, per supplier the acceptance
disposition, final checkpoint and journal-digest references, and the chain identity; nothing from a supplier's
workspace is restored. For exact transfer, `attach_linked_context` (`application/programs/linked_context.py`) calls
`transfer_builders.linked_mission`, freezing the released exports beside the receiver's local inputs in the sealed
plan (`LinkedExportResolver`, `application/context/linked_transfer.py`): the pinned source bytes are read under the
receiver's own current authority, a source correction that demotes the head is caught at promotion time, and a
link never replaces a pinned revision with a newer head. Independent evaluators do not inherit linked exports.
Releases 1.10.0 (`0068`) and 1.11.0 (`0069`, family-writer grants) carry this
(`packages/mission-control-db-contract/releases/README.md:299-340`).

## 4. Agent runtime and capability configuration

Every member has its own effective environment, lane, model profile and sealed templates; a chain says nothing about
them. Members on Claude, Codex or Cursor lanes start through the same launch author once the bindings file binds them
([mission manifest](mission-manifest.md)); a linked child family that concluded failed is recorded `failed` (patch
`mp20-linked-child-concluded-failed`). Cross-provider chains are proven with FIXTURE providers on real PostgreSQL and
Temporal (MP-20). The fixture Mission 2 (Cursor Cloud research Goal Loop supplying a Deep Agents ingestion Goal Loop)
still cannot start as authored: its verifier is on `deep_agents` where no sandbox profile or hook-script launch
binding exists.

## Child Mission Invocation (not built)

Specified in annex `workflow-types/06` (harvested at `66185d2e`), not implemented: a Child Mission Invocation node
creates (`spawn`) or attaches (`adopt_as_child`, `depend_on`, `use_outputs`) a mission from inside a program, from a
`definition_template`, `template` or `agent_authored` source within a Spawn Grant (`max_depth`, `max_children_per_node`,
`max_descendants`, `budget_share`, `allowed_operations`). `await { until }`, `track` or `detach` set the node's
lifecycle, `await` mirrors the child's outcome (`child_outcome(<value>)`), `on_parent_cancel` is `cancel_child`
(spawn default), `detach_child` (attach default) or `block`. A Portal is the parent-side projection: child identity,
lifecycle and outcome, projected output refs, open Human Tasks and budget, never transcripts or artifact bodies
(`peek` or `peek_and_command`). Child success supplies evidence, never parent acceptance. Code today: the manifest
parses `ChildMissionInvocationNode` (`mode`, `child`, `await`, `portal`; `domain/authoring/manifest.py:1094`) and
requires `governors.depth`; there is no Portal, SpawnGrant or invocation runtime (grep: no hit), and
`mission_relationship` rows record only chain, link and fork edges.

Built / specified / goal: chains, release, relay, exact linked exports, adoption and cancellation policy built and integrated locally (1.10.0/1.11.0), not qualified; Child Mission Invocation, Portals and Spawn Grants specified only.

# Citations

- ADRs: [0029](../adr/0029-mission-chains-compile-to-linked-missions-released-by-outbox.md), [0004](../adr/0004-temporal-sole-scheduler-transactional-outbox.md),
  [0034](../adr/0034-mission-manifest-v1-settled-environment-inheritance-chains-agents-hooks.md).
- Spec (archive and harvest): [SPEC-04](../specs/archive/fast-track-2026-10/SPEC-04-mission-chains.md); deleted pack `workflow-types/06-MISSION_INVOCATION.md`, OUTPUT-CONTRACTS §10 at `66185d2e`.
- Code: [contracts and compile](../../src/mission_control/domain/composition/chain.py), [structure service](../../src/mission_control/application/chains/service.py),
  [reducer](../../src/mission_control/application/chains/reducer.py), [packet](../../src/mission_control/application/chains/packet.py),
  [relay](../../src/mission_control/application/chains/relay.py), [PostgreSQL store](../../src/mission_control/adapters/postgres/chains/store.py),
  [linked transfer](../../src/mission_control/application/context/linked_transfer.py), [linked context](../../src/mission_control/application/programs/linked_context.py),
  [linked adoption](../../src/mission_control/application/outputs/linked_adoption.py), [routes](../../src/mission_control/interfaces/http/chains.py),
  [migration 0028](../../packages/mission-control-db-contract/component/migrations/0028_mission_chains.sql).
- Tests: [compile](../../tests/unit/chains/test_chain_compile.py), [reducer](../../tests/unit/chains/test_chain_reducer.py), [interfaces](../../tests/unit/chains/test_chain_interfaces.py),
  [tables](../../tests/integration/postgres/test_mission_chain_tables.py), [release](../../tests/integration/postgres/test_chain_release.py),
  [idempotent start](../../tests/integration/temporal/test_chain_start_idempotent.py), [two linked Goal Loops](../../tests/acceptance/mission_control/test_chain_two_goal_loops.py),
  [MP-20 parity](../../tests/integration/temporal/test_mp20_workflow_parity.py), [release 1.10.0](../../tests/integration/postgres/test_sprint_oc_release_1100.py).
- Proof status: [control board](../specs/provider-consolidation-2026-10/sprint-oc/NEXT-SESSION.md) (`:285-312` linked runs 2-14, `:370` commit `abac1fde`).
