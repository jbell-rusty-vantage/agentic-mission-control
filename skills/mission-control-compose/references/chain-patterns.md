# Chain patterns

Hand-written, checked against the manifest model and the chain compiler. Field names, allowed
values and defaults are the server's: `missionctl describe manifest:ChainLinkDeclaration`.

## The shape of a chain

```yaml
manifest: mission/v2
missions:
  - key: research
    # title, application, goals, environment ...
    program:
      key: root
      behavior: goal_loop
      # objective, action_space ...
      outputs:
        - {name: sources, form: reference}
  - key: ingestion
    # title, application, goals, environment ...
    program:
      key: root
      behavior: goal_loop
      # objective, action_space ...
      inputs:
        - {name: sources, from: research.sources, expand: materialize}
links:
  - {from: research, to: ingestion, kind: supplies, outputs: [sources]}
```

- `from` and `to` are mission keys of this manifest.
- A `supplies` link names one or more outputs of the supplier's program root. For each, the
  consumer declares a node input whose `from` is `<supplier mission key>.<output name>`.
- One link per pair of missions and kind: several outputs travel on one link's `outputs`.
- A consumer with several links into it is admitted when all of them are released.

## When a link releases (`on`)

| `on` | Releases when |
| --- | --- |
| `goal_accepted` (default) | the supplier's run accepted the goal that owns the supplied outputs. Name the goal with `on: {goal_accepted: {goal_key: KEY}}` where it cannot be inferred. |
| `mission_accepted` | the supplier's run completed with every required obligation accepted. Use it for outputs that belong to different goals. |
| `execution_complete` | the supplier's run ended with any outcome but cancelled. On a `supplies` link only as a repair link. |

A supplier that ends without satisfying the condition blocks the link
(`upstream_not_accepted` or `upstream_execution_failed`).

## Research then ingestion

```yaml
links:
  - {from: research, to: ingestion, kind: supplies, outputs: [sources, claims], on: mission_accepted}
```

`sources` and `claims` are owned by different goals of `research`, so the link waits for the
whole mission.

## Gate before an irreversible mission

```yaml
links:
  - {from: implement, to: release, kind: depends_on, on: mission_accepted}
```

No data crosses. `release` starts only after `implement` is accepted, human gates included, and
carries its own side-effect grant and its own gate.

## Repair from an unaccepted result

```yaml
links:
  - {from: draft, to: repair, kind: supplies, outputs: [report],
     receiving_purpose: repair, selector: finalized_snapshot, on: execution_complete}
```

The three fields go together: a repair link reads the finalized snapshot once execution ends,
and the consumer's packet labels what was not accepted. An ordinary link keeps the defaults
(`accepted_snapshot`, an acceptance condition).

## When the supplier is cancelled (`on_upstream_cancel`)

| Value | Link still armed | Link already released |
| --- | --- | --- |
| `continue` (default) | the link is `cancelled`; the consumer is never admitted | a consumer that started keeps running |
| `cancel_downstream` | the link is `cancelled` | a consumer that has not ended receives a cancel |
| `detach` | the link is `detached` | the link is `detached`; the consumer is left alone |

## Compile blockers of a chain

| `reason` | Fix |
| --- | --- |
| `unknown_mission_key` | `from` or `to` names no mission of this manifest. |
| `unbound_chain_output` | Declare the output on the supplier's program root, and the consumer's `from:` input, and the `supplies` link that carries it. |
| `schema_mismatch` | The consumer input's `schema` differs from the supplier output's. |
| `unresolved_release_goal`, `unknown_goal` | Name a goal of the supplier in `on: {goal_accepted: {goal_key: KEY}}`. |
| `export_release_goal_mismatch` | The outputs belong to different goals: use `mission_accepted`. |
| `duplicate_link` | Put the outputs on one link. |
| `chain_cycle` | Links must form no cycle, and none joins a mission to itself. |
| `missing_incoming_link` | Only the first mission is admitted at submit: give every other one a link into it. |
| `ambiguous_chain_source` | A mission key equals a sibling stage key: rename one. |

## Anti-patterns

- A chain that splits one goal across missions.
- A link whose supplier output no criterion's `evidence` names, on a supplier with several
  goals: the releasing goal cannot be inferred.
- Reading a released link as an accepted consumer: the consumer is its own run, judged on its
  own.
