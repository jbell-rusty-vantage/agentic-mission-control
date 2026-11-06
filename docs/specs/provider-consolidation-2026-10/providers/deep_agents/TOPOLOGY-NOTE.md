---
type: ADR Candidate
title: "Saver and Agent Server topology note: the standalone checkpoint saver, the in-memory Agent Server, and the proposed separation (WP-TR-5)"
description: "What is built (one AsyncPostgresSaver per process over the mission_control_runtime schema; the Agent Server in its in-memory edition) and what is proposed for the Agent Server's persistence, with each paragraph labelled built or proposed. An ADR candidate awaiting an owner decision, not an accepted decision."
tags: [mission-control, providers, consolidation, deep-agents, topology, adr-candidate]
---

# Saver and Agent Server topology note (WP-TR-5, TRACING-PROPOSAL §P6.4)

ADR candidate, not an accepted decision. Each paragraph says whether it describes what is
built or what is proposed. Sources: [TRACING-PROPOSAL §P6](../../../archive/provider-consolidation-2026-10/proposals/TRACING-PROPOSAL.md),
[ADR 0017](../../../../adr/0017-agent-server-runtime-persistence-separate-database.md) and the
db-contract's [AGENT_SERVER_TOPOLOGY.md](../../../../../packages/mission-control-db-contract/runtime/AGENT_SERVER_TOPOLOGY.md).

## The standalone saver today (built)

Every Mission Control process that touches native cognition state (each worker, the API)
opens one LangGraph `AsyncPostgresSaver` for its lifespan over one psycopg `AsyncConnection`
(`adapters/deep_agents/persistence.py`, `StandalonePersistenceLifespan`): no pool, every
operation serialized by the saver's lock. Its conninfo is the runtime DSN bound to the
`mission_control_runtime` schema of the runtime database through a single libpq `options`
value (`runtime_checkpoint_conninfo`); a DSN that already carries `options` or a
`search_path` is refused. The schema is provisioned only by `mission-db runtime-apply`.

## The Agent Server today (built: in-memory; not installed: Postgres edition)

The pinned Agent Server (`langgraph-api` 0.12) runs as `langgraph dev` in its in-memory
edition (pickle files). Its Postgres edition is a separate package that is not installed: it
applies its own unqualified migrations at startup, creating `checkpoints`,
`checkpoint_blobs`, `checkpoint_writes` and `store` with a different shape from the
standalone saver's tables of the same names, needs `CREATE` and extension privileges, and has
no schema or namespace setting (AGENT_SERVER_TOPOLOGY.md, "Evidence"). It therefore cannot
share `mission_control_runtime` and cannot be confined to a private schema of the runtime or
business database by any supported setting.

## Recommendation (proposal)

Keep ADR 0017's position when the server moves to its Postgres edition: two databases on
the same remote server, never a shared schema. The parent saver stays in
`mission_control_runtime` of the runtime database; the Agent Server gets its own database
with its own owner and login role, `CONNECT` to that database only and no membership in any
`mission_control_*` role (the db-contract note's preferred topology). Until a read of
async-child state through the server's API exists (`threads.get_state` and
`threads.get_history` on the child's `native_thread_ref`, which
`mission_control.subordinate_execution` already records), child points are written as
`lifecycle_only` entries carrying the server thread ref, never by reading the server's
tables. The server's thread TTL is enabled only after TR-2 closes TR-G1 and TR-G2 (every
input and output the Transcript must hold is in Mission Control's own tables first).

## Naming the saver on every point

Built (1.4.4): every `QualifiedCheckpointKey` carries `checkpointer_ref_digest`, the catalog
definition digest of the pinned checkpointer (`pins.checkpointers`). It does not change with
the DSN, so it names *which* checkpointer definition wrote the point, not *where*.

Built (WP-TR-5, §P6.2): `saver_locator_digest = sha256(host, port, dbname, schema)` is
computed at composition from the bound conninfo (`adapters/deep_agents/persistence.py::
saver_locator_digest`; no user, password or options enter the digest), held by the process's
`StandalonePersistence` and handed to the Deep Agents lane and the adapter as the locator of
each pinned checkpointer digest. Every cognition point written at settlement, by the
reconciler or by a fork seed carries it on its key (`QualifiedCheckpointKey.saver_locator_digest`;
lineage keys, which the adapter compares by value, do not). `state-as-of`, `seed_fork` and the
reconciler's walk refuse a point whose locator digest the process's registry does not serve
with the typed outcome `saver_not_served`, distinct from `saver_unreachable` (the served saver
did not answer). `PinnedPersistence.locator_digest` is declared for a pin revision that wants to
record it; the pins file does not carry it today.

Consequence: moving the saver (a new host, port, database or schema) is a new locator; points
written before the move keep naming the old location, so a read after the move degrades
honestly (`saver_not_served`) instead of silently reading a different saver. FX-TR-REMOTE
(`tests/acceptance/mission_control/test_tracing_remote.py`) proves `saver_unreachable` and
the points budget on the production offline stack; `saver_not_served` is proven on the lane
in `tests/unit/deep_agents/test_remote_saver.py` only.
