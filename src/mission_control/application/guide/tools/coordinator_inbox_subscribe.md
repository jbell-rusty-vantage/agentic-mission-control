---
id: coordinator_inbox_subscribe
title: coordinator_inbox_subscribe: register a coordinator inbox
summary: Register a durable inbox over a mission or run; `profile` narrows what it delivers.
---
`profile` is optional: omit it for the default filter, which delivers every notification kind except `rate_limited` and leaves deltas off. Every field of the schema below has a default, so name only what you change.

- `kinds`: the notification kinds this inbox delivers. `rate_limited` cannot be selected; the rate cap produces it.
- `rate_limit_per_run` within `rate_window_seconds`, and `max_recursion_depth`: the bounds coordinator_inbox_command enforces on Commands sent because of a notification.
- `batch_window_seconds` and `batch_max_events`: how events are batched into one notification.
- `prompt_mode`: `off` (default), `queue_instruction` or `add_context`.

A start already subscribes the launcher's inbox, so call this only for a run or mission you did not start.
