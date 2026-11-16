---
id: mission_run_state_as_of
title: mission_run_state_as_of: read an agent's state at a cognition point
summary: The messages, files, pending tasks and interrupts an agent held at one recorded point.
---
Read an agent's state as it was at one cognition point of a run.

Use it to see the messages and files the agent held then; mission_run_point_frames gives the provider frames of that step. `point_id` comes from mission_run_points.

Returns the `point`, its `state` (messages, files, pending tasks, interrupts), `restore_level` (R0 to R3: how much could be read back) and `usage_to_point`.

Refusals:

- An error marked retryable means the saved state did not answer: call again.
- `reason: checkpoint_missing`: the point exists and its saved state is gone (pruned or never written).
- A `prerequisite` in the error details means this server was not deployed with what it needs to read that lane's saved state; the sentence says what is missing. It is not retryable. mission_whoami lists it under `server.time_travel` before you ask.
