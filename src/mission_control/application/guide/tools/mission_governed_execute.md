---
id: mission_governed_execute
title: mission_governed_execute: execute a prepared Governed Effect
summary: Run a prepared Governed Effect once; `arguments` is optional and must equal the prepared ones.
---
`intent_id` comes from mission_governed_prepare.

`arguments` is optional. It is the governed tool's own JSON object, the same object `arguments` carried in mission_governed_prepare (`tool:mission_governed_prepare` shows its shape). When given it must equal the prepared arguments; different arguments are refused and need their own prepare.
