---
id: mission_governed_execute
title: mission_governed_execute: execute a prepared Governed Effect
summary: Run a prepared Governed Effect once; `arguments` is optional and must equal the prepared ones.
---
Execute a prepared Governed Effect once and return its receipt.

Call it after mission_governed_prepare, when the Human Task it opened (if any) is resolved. `intent_id` comes from mission_governed_prepare.

`arguments` is optional. It is the governed tool's own JSON object, the same object `arguments` carried in mission_governed_prepare (`tool:mission_governed_prepare` shows its shape). When given it must equal the prepared arguments; different arguments are refused and need their own prepare.

Safe to repeat: the effect runs at most once and a repeat returns the same state.

Returns `status`: executed with a `receipt` (`outcome` applied, noop, rejected or failed, and the tool's `output`), pending_approval while the review is still open, or denied, cancelled, expired, fenced, stale or in_doubt with a `reason`.
