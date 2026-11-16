---
id: mission_run_replay
title: mission_run_replay: verify that a step can be reconstructed
summary: Rebuild the input of one model call at a cognition point and compare it with what was recorded.
---
Rebuild the input of one model call at a cognition point from the run's records and compare it with what was recorded. No model is called.

Use it to verify that a step can be reconstructed exactly. `point_id` comes from mission_run_points; `call_index` picks a model call of the step (default: the last); `include_batch` adds the rebuilt message bodies. Leave `dry_run` true: a paid replay is not available and false is refused.

Returns `exact`, `first_difference` when it is false, the compared `messages` and the `model`.
