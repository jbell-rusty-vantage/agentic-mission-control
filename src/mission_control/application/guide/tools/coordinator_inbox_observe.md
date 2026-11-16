---
id: coordinator_inbox_observe
title: coordinator_inbox_observe: attest what the host observed about a notice
summary: Record the host's attested idle wake and the moment a delivered notice became visible to the model.
---
Attest what this host observed about one notice (`mc.coordinator_host_observation.v2`).

Echo the `delivery_nonce` the delivered page carried for that notice (it is in that payload only). Send two stages:

- `stage: wake` first, with `idle_since` and the wake `channel`: background_task_exit, monitor_event, session_prompt, or connected_poll when the host was not idle.
- Then `stage: visible` with the `channel` the payload reached the model through (tool_result, task_output or session_prompt) and no `idle_since`.

`observed_at` and `idle_since` are attested data; ordering uses the server's receive time. Idempotent by `observation_key`. An attestation, never acknowledgment: acknowledge with coordinator_inbox_ack.
