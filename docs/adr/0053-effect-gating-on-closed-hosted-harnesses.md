---
type: Decision Record
title: Effect gating on closed hosted harnesses
description: Proposed credential isolation, durable native-call intents, approvals and output custody for provider-run agent loops.
tags: [mission-control, adr, proposed, hosted, effects, approvals]
status: proposed
---

# Effect gating on closed hosted harnesses

**Status: proposed.** Follows

**Held 2026-11-01 (not accepted with 0042-0057):** the call identity is bound in approvals (`application/execution/approvals_governed.py:220,418`, `hosted_tools.py:191`), but no durable native-call intent row bound to session, turn and call identity was found in `src/`; accept when the intent store is located or built.
[SPEC-06](../specs/archive/materialization-observation-2026-10/SPEC-06-hosted-api-lanes.md)
and extends the existing Stop Fence, Hook Effect Intent, Human Task and Governed Effect
contracts. Implementation and live qualification remain separate claims.

The hosted provider owns its agent loop. Mission Control cannot claim local hook enforcement
over a closed native shell merely because it exposes function tools. Sandboxes receive no
organization API credential or repository write credential. Repository access is read-only;
egress and effectful tools follow the declared provider environment and pack.

External effects execute through trusted Mission Control tool handlers. Before an effect or
approval answer, the handler checks the Stop Fence and records an intent bound to the native
session, turn and call identity. Repeated delivery reconciles that same call; two distinct
calls with equal arguments must not accidentally share an intent. Provider action messages
are data, never authorization.

Managed Agents uses its supported permission confirmation protocol and durable Human Tasks.
Reviewer-edited input is denied when the native protocol cannot apply the edit. A bounded
approval wait leaves the provider request pending and its durable task open; replay binds
the same native call identity. A timeout never implies approval.
Preparation gates restrict tools until an attributable setup receipt proves readiness; policy
replacement happens only in the provider state that supports it. Agents API function calls
wait for a trusted result. Unsupported native shell/file blocking stays declared unsupported.

Publishing downloads a provider-produced bundle, verifies its contents and branch identity,
then executes a separately governed push or pull-request operation. Artifact upload similarly
registers verified custody. A tool result alone cannot claim that an external effect applied.
Git publication checks the exact mission branch and pinned base ancestry, scans every
intermediate commit/tree for forbidden paths and known secrets, rejects additional refs,
pushes without force and reads back the exact head.
Cancellation preserves available closing frames before settlement, with durable retry when
the observation owner or provider outcome remains unresolved.
Agents API interruption uses cancellation and replacement; it does not claim cooperative
steering. Native usage tokens remain separate from cost, which is unknown without an
admitted price table.

Fake-provider conformance proves adapter behavior. Real PostgreSQL and Temporal prove durable
recovery. Only an exact live provider/placement drill can establish qualification; none of
those proofs substitutes for another. Missing owner credentials, provider capability or
deployment bindings remain explicit blockers.
