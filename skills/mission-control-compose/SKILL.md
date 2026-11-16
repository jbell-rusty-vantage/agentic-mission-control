---
name: mission-control-compose
description: Compose several missions into a Mission Chain (missions plus links in one manifest), choose between a chain, a nested Goal Loop or Stage Graph and a child mission, and move accepted outputs across a link. Use when one mission should feed or release another, for research then ingestion, or when the user asks how state moves between linked missions.
---

# Compose missions

Pick the shape by governance boundary, not by size.

| Need | Shape | Because |
| --- | --- | --- |
| Adaptive steps toward one objective | A `goal_loop` node in the program | Same mission, budget and acceptance |
| A known route with dependencies | A `stage_graph` node | Same mission; typed bindings between stages |
| Independent goals, each with its own budget and acceptance, started in order | A Mission Chain: `missions` plus `links` | Each mission is admitted and judged on its own; a link releases the next |
| A program that waits on another mission | A `child_mission_invocation` node | The parent blocks on the child |

Facts come from the server: `missionctl describe manifest:ChainLinkDeclaration` prints every
link field with its allowed values and defaults, `missionctl describe manifest:InputBinding` an
input, `missionctl describe manifest:ChildMissionInvocationNode` the child node.

## Order of work

1. **Write the chain.** One manifest with `missions` (two or more) and `links`; the
   [patterns](references/chain-patterns.md) show whole links. A `supplies` link names the
   supplier's root `outputs`; the consumer declares a node input `from: <mission key>.<output>`
   for each. A `depends_on` link orders two missions and carries no data.
2. **Compile.** `missionctl mission compile FILE`. Done when the report has no blockers; a
   chain blocker names its link (`/links/N`) and its reason.
3. **Stop for approval, then submit.** `missionctl mission submit FILE` returns the `chain_id`
   and each `mission_id`. Only the first mission, the one no link enters, has an admitted
   `run_id`.
4. **Start the first run** on the user's word: `missionctl mission start RUN_ID`. A later
   mission is admitted with its Context Packet when every link into it is released.
5. **Follow it.** `missionctl chain inspect CHAIN_ID` lists each mission and each link's state
   (`armed`, `released`, `blocked`, `detached`, `cancelled`); a blocked link says why. Wait on
   each member run with `mission-control-observe`.

## How state moves

When a link's condition holds, Mission Control builds the consumer's Context Packet from the
supplier's accepted output revisions and admits the consumer's run with it. Nothing mutable
crosses: no workspace, no transcript, no grant.

## Rules that never bend

- A chain never widens authority: each mission keeps its own grants, budget and side effects.
- Only accepted outputs release an ordinary `supplies` link. Unaccepted outputs travel only on
  a repair link (`receiving_purpose: repair`), labelled as such.
- Every mission but the first needs a link into it; links join missions of the same manifest.
- A changed link after submit is a new revision of the chain.

## Common mistakes

- Chaining to split one goal for budget accounting: narrow a node's `environment.budget`.
- Writing the output into the link's ends: `from` and `to` are mission keys, `outputs` names
  what is supplied.
- Leaving out the consumer's `from:` input, or the supplier's root output: both are
  `unbound_chain_output`.
- Expecting a cancelled supplier to stop its consumer: `on_upstream_cancel` defaults to
  `continue`; say `cancel_downstream` or `detach` when you mean it.
- Hiding a chain inside a subagent: independent goals need independent admission.
