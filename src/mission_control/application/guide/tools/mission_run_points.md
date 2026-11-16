---
id: mission_run_points
title: mission_run_points: list a run's cognition points
summary: The recorded positions in an agent's work where its state can be read back and a fork can start.
---
List a run's cognition points: recorded positions in an agent's work where its state can be read back and a fork can start.

Use it to get a `point_id` for mission_run_state_as_of, mission_run_point_frames or mission_run_replay, or a seed for mission_run_fork.

Filters: `node` (a node key), `iteration`, `cycle`, `session_generation`, `unit_key`, `kind`, `seedable` (only points a fork can start from) and `role` (input, intermediate, leaf, result, source, interrupted, replacement_start, fork_seed, rollover_start, cycle_start, reused, subagent_root).

Returns up to `limit` (at most 500) `entries`, each with its `point_id` and `coordinate`, and a `next_cursor` to pass back as `cursor`.

A seedable point seeds a fork only once the run has a Snapshot: every fork starts from one (`tool:mission_run_fork`).
