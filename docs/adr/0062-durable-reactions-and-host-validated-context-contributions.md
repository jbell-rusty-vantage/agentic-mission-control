---
type: Decision Record
title: "Durable reactions and host-validated context contributions"
description: "Durable-transition reactions run as ordinary admitted execution scheduled by Temporal; hook scripts get bounded snapshots and scoped host-mediated reads and stage candidates for host validation; no second scheduler or effect executor."
tags: [mission-control, adr, outputs, knowledge, context]
status: accepted
date: 2026-10-26
---

# Durable reactions and host-validated context contributions

Accepted target under the owner's final synthesis directive (2026-10-26). Implementation and qualification are separate claims; the built state is in docs/knowledge/durable-reactions.md and hook-contributions.md.

**Decision.** Attach bounded durable-transition reactions through ordinary admitted execution,
scheduled by Temporal. Hook scripts receive bounded event snapshots and scoped host-mediated reads;
they stage candidate files for host validation/installation. Model work/external writes use separate
ordinary operations. Compaction can consume bounded preservation proposals under host validation.
Persistent candidate notes follow this output path when configured.

**Why.** Turning scripts into an additional scheduler, effect executor or authoritative state store
would duplicate budgets, permission, reconciliation and replay machinery. Event-specific capabilities
make the actual guard/observation/post-effect behavior explicit.

**Alternatives not selected.** Implicit whole-workspace/KS access, direct live-file mutation, directly
effectful script execution, arbitrary summary replacement, a second automatic memory system, or a claim
that a late denial reverses an already committed effect.

**Consequences.** Preserve kernel-first execution and catalog admission. Before-effect guards can block;
post-effect/observation events cannot undo committed work. Separate compaction from continuation and
keep mandatory state independently preserved. Reconcile ADR-0026's unconditional denial wording with
this event-specific matrix.

**Provenance.** OC-D171–175, with OC-D137/138 and retained kernel invariants.

The [canonical output contract](../knowledge/output-contracts.md) defines the typed behavior. [Decision reconciliation](../specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md) maps original answers and work. Existing unrelated proposed ADRs remain proposed.
