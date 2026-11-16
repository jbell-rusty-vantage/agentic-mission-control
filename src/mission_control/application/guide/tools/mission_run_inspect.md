---
id: mission_run_inspect
title: mission_run_inspect: read a run's current state
summary: Lifecycle, phase, outcome, budget, estimated cost and the control sections of one run.
---
Read a run's current state: lifecycle, phase, outcome and its control sections.

Call it before mission_command_send (it gives the `version` and `execution_generation` a Command must name) and afterwards to see the delivery. To read what the run did, use mission_run_transcript.

Returns `lifecycle` (pending, running, paused, completed), `phase`, `execution_outcome` (how execution ended, not whether the mission was accepted) and, where the run has them, `lane`, `sessions`, `mailbox`, `delivery_reports`, `frames_cursor`, `chain`, `stop_fence`, `points_incomplete`, `unit_failures`, `budget`, `cost` and fork `lineage`.

`cost` (`mc.run_cost.v1`) is what the run's recorded model calls cost at this installation's Model Catalog list prices: `estimated_micros` (US dollar micros), `estimated_usd`, the calls and tokens, and `by_model`. It is an estimate: every input token is priced at the list price (a provider's cache discount is not applied, so it is an upper bound where prompts were cached) and it is not an invoice. `disposition` is `estimated` when every call was priced, `partial` when some calls name a model the catalog does not price (`unpriced_calls`; never counted as zero) and `unknown` when no call could be priced.

`budget` is a separate account. Its token, turn and tool-call dimensions are charged as work settles; its currency dimensions (`currency.estimated_micros`, `currency.actual_micros`) are charged only by a lane that settles a provider's own billed amount, so for a run whose lane reports tokens alone they read 0 and the manifest's `usd` ceiling is not enforced from them. Read the money a run spent from `cost`.
