---
id: mission_run_points_reconcile
title: mission_run_points_reconcile: repair a run's cognition point records
summary: Add the points and frame ranges that are missing for work that already settled.
---
Repair a run's cognition point records: add the points and frame ranges that are missing for work that already settled.

Use it when mission_run_inspect lists units under `points_incomplete`, or when mission_run_points lacks steps you expect. It changes only the point records and is safe to repeat; `unit_key` limits it to one unit.

Returns `points_added`, `frame_ranges_filled`, `pruned`, `walks_completed` and `saver_unreachable` (units whose saved state did not answer). Then call mission_run_points again.
