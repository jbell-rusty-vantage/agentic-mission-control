---
type: ADR Candidate
title: "Output obligations, application delivery and sealed transfer: decision candidates"
description: "Three local ADR candidates derived from confirmed owner decisions; canonical review and implementation proof remain separate."
tags: [mission-control, adr-candidate, output-contracts, application-boundaries, context-transfer]
date: 2026-10-24
interview_id: output-obligations-gpt-6-astra-2026-10-24
interviewer_model: "GPT-6-Astra"
model_label_source: "Owner-supplied experiment label"
research_assistant_model: "GPT-6.1-Sol"
status: draft
source_commit: 8de6fab94fd5d17d79f2ecfd92e55329bb282a36
---

# Decision candidates

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../../sessions/KICKOFF.md); no new interview or runtime completion is implied.


These local candidate IDs are not canonical ADR numbers. Each candidate records owner-confirmed
direction from [ANSWERS](ANSWERS.md), elaborated in [SPECIFICATION](SPECIFICATION.md) and
[CONTEXT-TRANSFER](CONTEXT-TRANSFER.md). This file accepts no ADR, changes no existing authority and
certifies no implementation. Exact protocols and schemas remain proposed implementation design.
Each candidate's disposition is **ready for canonical ADR review**. OC-D78 confirms the product model
as a revisable checkpoint; it does not accept canonical ADRs or certify these proposed implementations.

## DC-OBL: Composable obligations with explicit, governed revisions

**Status: draft. Basis:** OC-D32, D34, D38–40, D42–44, D45–51, D73–76.

**Context and decision direction.** A report index, financial analysis, course or code project can
combine representations, application semantics and purpose-specific guarantees. Model these as
composable Output Obligations over common forms, with pinned reusable definitions or supported inline
schemas. Check every declared guarantee, including referenced content and ingestion evidence when
promised. Shape validity cannot stand in for evidence judgment, domain admission or publication.
Common acceptance semantics remain stable across providers; qualified, versioned namespaced extensions
declare their support and portability. Unsupported requirements refuse unless an authored alternative
satisfies them.

Submissions retain their exact contract revision. Governed successor revisions preserve actor,
authority, reason and impact; an executor cannot waive its own requirements. Distinct deliverable
identity is separate from revision and subject coverage. Retain usable partial results without
declaring the complete mission accepted. Assessments may be reused only where exact subjects,
evidence, purpose/policy, authority and freshness remain applicable. Report contracts distinguish
declared-assertion checks from independent material-claim/question coverage; when the latter is
promised, require a separate recorded review and its gaps.

**Alternatives and trade-offs.** Fixed business-specific kernel kinds simplify dispatch but make each
application a kernel change. Unrestricted schema/plugin execution is more flexible but lets payloads
change validation authority. A composable common model costs compilation and compatibility checking,
while retaining explicit domain ownership. Silent contract replacement is simpler but destroys the
meaning of historical failures and assessment reuse.

**Consequences and proof.** Keep immutable submission/assessment history and an explicit accepted-current
view. Prove that revising report A does not count as report B; a valid index cannot hide a missing
required report or receipt; policy weakening needs authority; changed contracts do not rewrite old
failures; and provider substitution cannot silently reduce a guarantee. Prove independent coverage
claims require their review evidence rather than only the producer's assertion ledger.

This extends the Completion Contract vocabulary and
[ADR-0010's closed typed completion expressions](../../../../../adr/0010-completion-expressions-closed-typed-ast.md).
It does not reopen [ADR-0012's separate coding publication capabilities](../../../../../adr/0012-coding-effects-are-separate-capabilities.md).

## DC-APP: Application-owned content through deterministic delivery adapters

**Status: draft. Basis:** OC-D62–70, D77.

**Context and decision direction.** Mission Control must pass application content between units
without owning each application's entity model or rediscovering knowledge during transfer. Canonical
content stays application-owned. Versioned application modules implement common typed resolution,
export and representation contracts; selected exact read results are retained in permitted custody
and reused until explicit or authored refresh creates a new result. Native entity identity/revision,
retained result identity and bytes digest remain distinct.

Deterministic delivery resolves already selected references and performs declared faithful
representations. Agent discovery, evidence selection and semantic preparation remain separate
Knowledge Services operations. Preserve source, transformation/profile and result lineage; an
unavailable revision or unsupported representation is explicit. Ingestion records the original
mission artifact and a receipt-backed mapping to native entities/revisions, including normalization
or splitting. Neither equal bytes nor an ingestion receipt alone proves semantic quality.

**Alternatives and trade-offs.** A full Mission Control content mirror improves local availability
but creates synchronization and competing-authority problems. Live references alone minimize retained
bytes but cannot guarantee replay or recovery when sources change. Selective retained results cost
storage and retention coordination while preserving truthful native consistency guarantees.

**Consequences and proof.** Adapters own native queries and access checks; the kernel owns general
scope, custody and delivery orchestration. Prove isolation between application bindings, exact replay
after source mutation, explicit refresh lineage, refusal of unavailable exact reads and one-to-many
ingestion mappings. A transfer retry must not initiate research or silently substitute current data.
Required content availability must be secured for the declared execution/recovery period.

This elaborates [ADR-0007's separation of mission authority and recovery state](../../../../../adr/0007-authoritative-state-separate-from-advisory-memory.md)
and [ADR-0009's separate application authority](../../../../../adr/0009-common-release-separate-app-authority.md),
alongside the [Knowledge Services integration boundary](../../../../../knowledge/knowledge-services.md).
It does not turn private runtime checkpoints into domain content. OC-D77 defers physical database
topology changes; this candidate authorizes no persistence relocation or migration.

## DC-XFER: Configurable sealed transfers under mandatory system constraints

**Status: draft. Basis:** OC-D49, D52–61, D64–69, D72–74, D76.

**Context and decision direction.** Consumers need different content forms and budgets, while history
must say exactly what each execution received. Clients/coordinators author versioned transfer profiles
or inline settings with input/link overrides. Deterministic assembly seals the effective selection,
exact sources and representations into a Context Packet. Required delivery forms and explicit allowed
alternatives constrain packing; budget pressure cannot silently turn a required usable file into an
unusable reference or summary.

Mandatory state/findings, authorization, scope, capability qualification, retention/recovery guarantees
and budget limits remain system constraints. Conflicts block with typed reasons. Optional preparation
is separately budgeted and attributed. Live changes apply at safe boundaries as new plans, preserving
sealed packets; authored bounded repair can select permitted alternatives and otherwise blocks.
Cross-mission mappings carry required provenance and state; broader history and obligation adoption
are explicit. Content delivery alone transfers no obligation or publication authority.

**Alternatives and trade-offs.** Unrestricted automatic packing hides degradation; immutable universal
packing defaults cannot serve varied applications. Configurable plans under hard constraints require
more admission and inspection machinery, but make effective behavior explainable and replayable.

**Consequences and proof.** Expose authored and effective settings, selected sources, delivery evidence
and refusal reasons. Prove restart/retry reuses the sealed packet; unauthorized cross-application
references fail; required inputs survive context preparation; budget conflicts block; safe-boundary
updates do not mutate prior packets; and downstream tracking marks affected results stale while
preserving exact historical provenance.

This elaborates, rather than replaces,
[ADR-0027's sealed Context Packet and four delivery tiers](../../../../../adr/0027-context-packet-tiers-and-workspace-materialization.md)
and ADR-0007's deterministic context selection. Provider extensions must preserve these guarantees.
OC-D71 defers subagent shape and special tools: no candidate here chooses child construction,
provider-native helper interfaces or a new subagent tool protocol.
