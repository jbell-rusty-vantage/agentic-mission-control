---
type: Decision Record
title: "Application content ownership and shared knowledge authority"
description: "Mission Control owns orchestration and delivery evidence; shared Knowledge Services own report, evidence, verification and permitted-use semantics behind explicit ports; AIDB and BKS keep native SQL and graph authority; no universal artifact table."
tags: [mission-control, adr, outputs, knowledge, context]
status: accepted
date: 2026-10-26
---

# Application content ownership and shared knowledge authority

Accepted target under the owner's final synthesis directive (2026-10-26). Implementation and qualification are separate claims; the built state is in docs/knowledge/knowledge-services.md.

**Decision.** MC owns orchestration and its ledger/reference/delivery evidence. Shared KS owns reusable
report, evidence, verification, permitted-use and native-operation semantics behind explicit ports.
AIDB owns AI Engineer native SQL; BKS owns graph SDL and its admitted executor. The KS Biotech binding
calls that executor. Logical commonality does not create another domain schema or verification authority.

**Why.** A universal MC artifact table or separate domain-specific verification engines would duplicate
authority and make exact native identity/lineage difficult to preserve. Existing package namespaces do
not establish backend neutrality.

**Alternatives not selected.** Copy all application bytes into MC by requirement; write graph content
directly from shared KS; author domain schema in the common MC component; invent absent upstream repos.

**Consequences.** Four-owner schema-fit review/migration belongs to each affected slice. Exact current
release/schema pins are checked during implementation; old candidate version names are historical.
Cross-application linking is unadopted, not a required consequence of shared ports.

**Provenance.** DC-APP/DC-BIND; OC-D64/70/77/79..105/117/167 and the recurring schema-fit directive.

The [canonical output contract](../knowledge/output-contracts.md) defines the typed behavior. [Decision reconciliation](../specs/provider-consolidation-2026-10/sprint-oc/DECISIONS.md) maps original answers and work. Existing unrelated proposed ADRs remain proposed.
