---
id: mission_run_list
title: mission_run_list: list runs
summary: The runs you may see, newest first, optionally filtered.
---
List the runs you may see, newest first.

Use it to find a run id, then call mission_run_inspect.

`query` is optional: clauses `key='value'` joined by AND. Keys:

- lane (a lane profile such as deep_agents)
- phase (executing, cancelling, in_doubt, completed, cancelled, failed)
- mission_id
- forked_from (a run id)
- status (running, completed, failed, canceled, terminated, timed_out, paused, continued_as_new)
- started_after (`=` or `>` an ISO-8601 instant with a timezone)

Example: lane='deep_agents' AND phase='executing'.

Returns up to `limit` (at most 500) `rows` with run_id, mission_id, lanes, phases, lifecycle, terminal_outcome and run_version, and `truncated`.
