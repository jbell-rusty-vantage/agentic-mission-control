---
type: Decision Record
title: "One sealed transfer plan and attempt-specific receipts"
description: "One sealed transfer plan resolves exact named sources through profile, mission, unit and input preferences and renders prompt, index, files and handles from it, with separate per-attempt delivery and readiness receipts."
tags: [mission-control, adr, outputs, knowledge, context]
status: accepted
date: 2026-10-26
---

# One sealed transfer plan and attempt-specific receipts

Accepted target under the owner's final synthesis directive (2026-10-26). Implementation and qualification are separate claims; the built state is in docs/knowledge/output-contracts.md and context-and-continuation.md.

**Decision.** Extend the existing effective configuration path. Profile or inline definitions are
admitted/pinned, preferences specialize profile→mission→unit→input, and hard constraints combine.
Resolve exact eligible named sources into one sealed receiver plan. Render prompt/index/files/handles
from that plan and append separate attempt-specific delivery/readiness receipts. Required host state
and workflow-specific state builders remain authoritative.

**Why.** Competing selection and materialization authorities can deliver unrelated or stale sources,
silently weaken placement, or claim access from a path string. One plan makes exact replay, resource
accounting and inspection meaningful.

**Alternatives not selected.** Run-wide report loading; filename/stem/output-position guesses;
unbounded history; hidden lossy summaries; submission-time changes to receiver policy; a copied
credential/permission freeze.

**Consequences.** Aggregate prompt/file accounting includes reserves and later tool reads. Use only
authored satisfying placement alternatives; otherwise refuse/repair. Maintain current access/use and
explicit revision boundaries. Held/draft linked repair is permitted only within one application under
its admitted purpose; ordinary cross-mission supply retains source acceptance and use gates.
Already-running chain consumers continue on upstream cancellation unless propagation was selected.
Child spawn/attach cancellation defaults remain distinct.

**Provenance.** DC-XFER; OC-D52..61/99/101/116/119/121–124/133–148/165–167.
Partially supersedes ADR-0027 placement simplifications and ADR-0029's running-consumer cancellation default.

The [canonical output contract](../knowledge/output-contracts.md) defines the typed behavior. [Decision reconciliation](../specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md) maps original answers and work. Existing unrelated proposed ADRs remain proposed.
