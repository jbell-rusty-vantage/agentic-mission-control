---
type: Decision Record
title: "Authenticated origin and native receipt provenance"
description: "The receiving service binds origin from authenticated invocation credentials before sealing a native intent, rejects conflicting supplied origin and keeps producer, caller, receipt, adopter and assessor roles distinct; origin slices 1-3 are built (OVE-204)."
tags: [mission-control, adr, outputs, knowledge, context]
status: accepted
date: 2026-10-26
---

# Authenticated origin and native receipt provenance

Accepted target under the owner's final synthesis directive (2026-10-26). Implementation and qualification are separate claims; the built state is in docs/knowledge/knowledge-services.md; OVE-204 commits 03f11594 and 0d9806aa.

**Decision.** The receiving service binds live origin from authenticated invocation credentials before
native intent canonicalization/sealing, rejects conflicting supplied origin and retains exact
producer/caller/receipt/revision/adopter/assessor/consumer roles. Propagate admitted child and durable
origins through the same trust boundary. Reconcile an uncertain native effect before re-execution.

**Why.** Coordinates copied by a model, a content digest, or a declared role cannot establish trusted
authorship, authority or a completed write. Distinct roles are necessary when work is repaired, revised,
adopted, assessed or reused.

**Alternatives not selected.** Trust model-supplied mission identity; seal first and append unbound
origin later; collapse producer and adopter; treat a pending dispatch or permission as effect proof.

**Consequences.** Standalone self-origin remains service-authenticated standalone work, not a means
to assert MC identity. Exact receipt/effect mappings join native and orchestration records; byte equality
alone proves neither semantic equivalence nor identity/admission. Required readback is independent.

**Provenance.** DC-KOP/DC-ROLES; OC-D79/80/84/85/89/99/101/108–113/117.

The [canonical output contract](../knowledge/output-contracts.md) defines the typed behavior. [Decision reconciliation](../specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md) maps original answers and work. Existing unrelated proposed ADRs remain proposed.
