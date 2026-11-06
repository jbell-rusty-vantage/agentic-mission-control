---
type: Specification
title: "Output contracts, obligation fulfillment and Mission State Transfer: specification and session instruction (P1 deep_agents, general kernel first)"
description: "Ready-to-approve specification for what a unit must submit (obligations, output kinds, submission, the fulfillment check at the reducer) and what a dependent stage, a re-run cycling stage and a Goal Loop iteration or rolled-over session receive (the transfer policy, the three depth layers, the materialization module, the dependency-kind table, the point links), with the Deep Agents context-engineering adoption, the decisions OC-D1..OC-D26 with recommendations, the build order, the proofs and the revised session instruction. Grounded in the 2026-10-22 audit. Written 2026-10-22; revision 2 the same day (end of tracing Stage 3) adds the Stage 2 live evidence, the refreshed Deep Agents surface, subagent output and communication obligations, the transfer points and the owner interview that settles the decisions. The owner statements of 2026-10-21/22 are kept verbatim at the top."
tags: [mission-control, providers, consolidation, deep-agents, specification, P1, output-contracts, obligations, submission, context-transfer, materialization, transfer-policy, context-engineering]
status: archived
archived: 2026-11-02
archived_from: providers/deep_agents/SESSION-OUTPUT-CONTRACTS-AND-CONTEXT-TRANSFER.md
archived_reason: "converted into OUTPUT-CONTRACTS and ADR-0058..0062; built by Sprint OC"
---

> **Archived 2026-11-02** (converted into OUTPUT-CONTRACTS and ADR-0058..0062; built by Sprint OC). Kept for provenance; see the [ledger](../../../provider-consolidation-2026-10/LEDGER.md) for what replaced it.

# Output contracts and Mission State Transfer

<!-- final-output-contracts-2026-10-26 -->
**Converted, 2026-10-26:** the [final implementation packet](../../../provider-consolidation-2026-10/sprint-oc/README.md) and [OVE-162](https://linear.app/overtonbell/issue/OVE-162/oc-final-output-contracts-exact-context-and-knowledge-service) supersede output/transfer planning and interview-resume instructions here. The [canonical target](../../../../knowledge/output-contracts.md) controls adopted behavior; [DECISIONS](../../../provider-consolidation-2026-10/sprint-oc/DECISIONS.md) disposes every OC/DP/CS recommendation and older ADR candidate. Retained source/proof claims remain historical and scoped. Start [KICKOFF](../sessions/KICKOFF.md); no new interview or runtime completion is implied.


**IQ-07 disposition, 2026-10-26.** Owner quotations, dated audits and original decision
recommendations below are retained as history. Current target behavior follows the
[accepted answers](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md) and
[integrated contract](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/CONTRACTS.md),
with OC-D1..26 dispositions in its §14. Local revision notices below supersede the conflicting
original rules. The old provider versions, build sequence, examples and launch instructions are
historical; they authorize no current implementation. Final integrated confirmation remains pending.

**Status.** Proposed specification, 2026-10-22, written for the owner to approve decision by
decision (§8). It replaces the audit-then-interview shape of the earlier session instruction:
the audit was done read-only on 2026-10-22 and is recorded in
[AUDIT-OUTPUT-TRANSFER-2026-10-22.md](../docs/AUDIT-OUTPUT-TRANSFER-2026-10-22.md) (cited as
`AUDIT §X`). The interview questions (a)–(j) of the earlier instruction are answered here as
recommendations; the owner confirms, amends or rejects each in one round, then the session
builds. Sequence: this work follows tracing Stage 2 (live fixtures) and Stage 3 (review, clean
code, documentation); it runs on Opus 5.5 until the owner's Fable budget resets.

**Revision 2 (2026-10-22, end of tracing Stage 3, Opus 5.5).** Four things changed since the first
version, none of them a decision:

1. **Live evidence.** Tracing Stage 2 ran the audit's facts against GPT-6 Sol and Luna; the
   parking lot ([SESSION-STAGE-2.md §4b](../sessions/SESSION-STAGE-2.md#entries-filled-2026-10-22-from-the-stage-2-transcripts))
   confirms §1 facts 2, 6 and 7 live and adds the verifier that could not read the executor's
   note (§1.1 below).
2. **The Deep Agents surface is refreshed**: [DEEP-AGENTS-SURFACE-2026-10-22.md](../../../provider-consolidation-2026-10/providers/deep_agents/DEEP-AGENTS-SURFACE-2026-10-22.md)
   (installed 0.7.5, latest 0.7.30) replaces the version statements §5 relied on; §5 is rewritten
   against it.
3. **Subagents are agent-bearing units**: the owner's point that subagents created at compilation
   owe output and communication obligations is §3.7, new; transfer points are enumerated (§4.0).
4. **The decisions move into an interview**: the owner wants to settle these questions in a
   structured interview rather than one round of approvals.
   [OWNER-INTERVIEW-2026-10-22.md](../interview-instructions/OWNER-INTERVIEW-2026-10-22.md) orders OC-D1..D26 (rounds
   R1, R1b, R2, R3) with the coordinator-surface decisions and the rest of the next sprints; its
   strawman sequence puts a Deep Agents upgrade and the agent-configuration language before OC-1
   (§6).

The owner's statements are kept verbatim because the specification must answer them.

**Supplement (2026-10-23).** The owner's architecture call added the `domain` output family
(`domain_effect`, receipt-form submission), the four-state authority table, the snapshot trigger set and the
three-facet point read: [DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md](../proposals/DOMAIN-PROVENANCE-AND-STATE-SUPPLEMENT-2026-10-23.md)
(DP-D1..D14). The sprints this specification's §6 sessions sit in are ordered by
[SPRINT-SEQUENCE-2026-10-23.md](../proposals/SPRINT-SEQUENCE-2026-10-23.md).

**Owner concern (2026-10-22, after tracing Stage 1):**

> *"I really don't think we hammered down the output contract rules and the context transfer
> enough. Think about the complexity here. Stage 2 depends on Stage 1. Let's say Stage 1's
> output contracts were evidence backed reports. Don't we want precision in context transfer --
> so providing and referencing the most important final outputs to the next session but also
> deeper storage and history so we can fork more precisely, or analyze more precisely, or even
> choose to pass on more context."*

**Owner widening (2026-10-21):**

1. *"Should we attempt to enforce output types of agent configurations for everything from a
   worthy code commit to an actual downloadable usable artifact? How well defined are our
   output contracts and how can we enforce submission. This would actually strengthen us so
   much."*
2. *"How do goal directed iterations pass all necessary context to the next iteration and how
   well is that mapped to the part of the agent instructions that refer to it, as it might
   contain mission control state and artifacts related to file references. How is the most
   important part of the output of one dependent part of our workflows (WHICH INCLUDES THE
   AGENTS) transferred to the next."*
3. *"How do stages that have cycles pass across cycles?"*
4. *"How do dependent stages get certain types of dependencies? One of the major benefits of a
   stage graph is breaking down big work into cumulative steps. That entails advancement and
   transfer. There are different types of dependencies that unlock the stage. This makes the
   transfers more complex. We need good policy and we will use heuristics."*
5. *"There are actually many more Deep Agents context engineering interfaces than we are
   using. They have things for clearing tool calls and writing tool calls to files. We need to
   take advantage of this. Stay up to date on new tools like Deep Agents so that we are
   utilizing the latest features. We are going to start that now as we now have multi-faceted
   contracts that are general and provider specific."*

**Owner goals (2026-10-22, declarative):** output contract types with enforcement and
checking; knowledge and content work and codebase work modelled distinctly and powerfully;
multiple and sometimes cumulative outputs ("n reports, a PDF with images created from the
report"); a submission process if one is needed; obligation fulfillment as one of the most
critical pieces of the system; a dedicated Mission Control materialization deep module that
owns context transfer and materialization; Goal Loop iterations and dependent stages receive
mission state and outputs so their cognition is "right on track".

---

## 1. What the audit found that drives the design

The full table is `AUDIT §D`. The eight facts the design answers:

1. The reducer checks **presence** of refs for required slots and, only when a slot has a
   resolved JSON schema binding, bytes and schema. There is no output kind, no integrity check,
   no completion AST at runtime (`AUDIT §A1`, `§A2`, `§D1–D3`). A stage that declares no outputs
   accepts an empty or prose result.
2. On Deep Agents, "submission" is **every file under the writable slot**, auto-captured as
   `workspace-candidate://` refs. The model's final JSON `output_refs` key **replaces** the
   registered refs in the Stage Graph workflow (`AUDIT §A4`, `§D4`). A model string can be an
   output today, against `context-and-continuation.md:55`.
3. The agent is instructed to use **artifact custody tools that do not exist** on this lane and
   to fetch references with **`missionctl` subcommands that do not exist**; a
   `workspace-candidate://` ref **cannot be downloaded** over HTTP (`AUDIT §D5`).
4. Stage and Goal outputs **never become `artifact` rows**; they stay candidates. The
   `artifact` table has no immutability trigger and no link to a cognition point (`AUDIT §A3`,
   `§D6`).
5. Manifest lowering keeps only **`all` + `required` edges from producer slot 0**. `join: any`
   and quorum, the other dependency classes, named producer outputs and the input `required`
   flag are dropped silently. Provisional Bindings and conditional release are absent
   (`AUDIT §B4`, `§D7`). `released_by` lists every incoming dependency, not the releasing ones.
6. A re-run cycling stage receives **only its new objective string**. Prior results, unmet
   obligations and the evaluation are recorded, never packed. The cycle cap **raises an
   exception**; progress is "the objective string changed"; manifests **cannot author cycles**
   (`AUDIT §B4`, `§D8`).
7. Goal iteration N+1 receives only what the executor's **latest handoff lists**. Verifier
   findings are never delivered (K04). A Deep Agents rollover reuses `pack_for_iteration`; the
   hydrator is unwired (`AUDIT §B5`, `§D9`). The handoff carries no `invariants` field
   (`08-CONTINUATION:54`).
8. F-T3-1: a non-parsing executor payload is re-raised as retryable with unbounded attempts;
   there is no retry classifier; the materializer silently drops `response_format` for an
   unregistered schema digest (`AUDIT §A5`, `§D10`).

### 1.1 What Stage 2 showed live (2026-10-22)

| Audit fact | Live observation (run, line of its `transcript.md`) |
| --- | --- |
| 2, the model's `output_refs` replaces registered refs | Stage Graph attempt 1 (`85a2a071-…`): the instructed `"output_refs": []` erased S1's registered outputs and the run failed (lines 301, 358). Goal Loop (`21449cb9-…`): every executor named a path in its own workspace; the verifier's packet listed it as an unresolved 0-byte reference and the verifier rejected all three iterations (line 351, 2060). Both live Goal runs failed for this alone. |
| 2, without the key | Every stage wrote exactly its instructed file; result points named only registered candidates (`cfc84d11-…`). The submission channel that works today is the file under the writable slot. |
| 5, transfer to a dependent stage | S3 received S2's brief whole and inline; the packet header says "fetch references with the listed command" and lists none (line 797). |
| 6, cycles | S2 cycle 1 received only its new objective and S1's facts; its own cycle-0 brief was in neither packet nor inputs; the model rewrote from S1 instead of revising (line 1528). |
| 7, Goal iteration | No handoff was written at any iteration; the iteration-2 packet holds the contract, the objective and the workspace map only; no findings (line 642). The operating contract asks for "a typed executor observation and handoff" with no schema in sight when no structured output is bound. |
| (new) inject | An injected message reads as an instruction to the model in every case (stage, fork, Goal fork). |
| (new) reading | Kernel hook pairs were more than half of every transcript (collapsed in `transcript.md` since Stage 3); every Responses API message carries a 1-2 KB `encrypted_content` block. |

Stage 3 also fixed two defects that touched this ground: a turn could return an **earlier**
turn's structured answer (`structured_response` persists in the thread; now only a value this
invocation wrote counts), and a Goal answer naming an unexpected `output_contract_ref` failed the
family workflow instead of settling `output_unparseable` (both in the ledger's Stage 3 entry).

What is **sound** and kept: the packet model with four tiers and the auto rules (`AUDIT §B1`),
the acceptance gate on packet items (`not_accepted` omission), the mandatory-never-truncated
rule, the candidate capture with digests, `completion_candidate` and `completion_decision`
rows, the cognition points and their cross-cycle and rollover parents, the typed Goal
observation and handoff models, the mission-branch head artifact on the lanes that have git.

## 2. Vocabulary (candidates for GLOSSARY)

**Current revision.** General forms plus pinned/inline substantive contracts replace the old
closed domain kinds. Ordinary helpers need not declare outputs (OC-D71). Submission, independent
assessment, fulfillment and invocation finalization are separate records (OC-D114). Required,
expected and optional govern enforcement, not content validity (OC-D118). The candidate wording
below is the original proposal; use current GLOSSARY and IQ-07 definitions for implementation.

| Term | Meaning |
| --- | --- |
| **Obligation** | What a unit must submit, declared on its node: a named output of one **kind**, with cardinality, level, validators and transfer defaults. Replaces `OutputDeclaration{name, schema, required}` as a superset. |
| **Output kind** | The closed set of typed things a unit can submit (§3.2). Each kind names its submission form, its mechanical checks and its default transfer tier. |
| **Deliverable** | A fulfilled obligation: the registered, digest-addressed output(s) plus the fulfillment record. Deliverables are what dependent units receive by default. |
| **Submission** | The act that makes bytes or a ref a candidate for an obligation. Two channels (§3.3), both completed by the harness, never by a table write from the agent (TRACING-PROPOSAL P7, TR-D9). |
| **Fulfillment** | The reducer's mechanical judgement per obligation: `fulfilled`, `missing`, `invalid(reason)`, `shortfall` (below cardinality min at an `expected` level). Acceptance of the unit result is derived from the fulfillment of its obligations plus the existing vetoes. |
| **Acceptance** | Unchanged: the reducer's decision on a unit result (`admit | reject | quarantine`). Verification by an agent or a human is a separate node and never collapses into acceptance. |
| **Mission State Transfer (MST)** | The whole of what a dependent unit receives: the packet (what the model reads), the materialization (what is on its filesystem), the instruction segment (where each thing is and how to fetch more) and the point links (where it came from). |
| **Depth layer** | One of three classes of transferred material: **Deliverables**, **State**, **History** (§4.1). Precision is choosing the tier per layer; depth is that every layer is reachable. |
| **Transfer tier** | Unchanged: `inline`, `materialize`, `reference`, `workspace` (ADR 0027). |
| **Release kind** | The typed fact of which dependency (and which kind of dependency) released a stage; recorded on the activation and read by the transfer policy (§4.3). |

## 3. Output contracts

### 3.1 The obligation model

**Current revision, OC-D71/114/118/119.** Responsible workflow promises are explicit; legacy
expected/document auto-obligations are removed. Ordinary helpers are optional contracted participants,
with explicit adoption and parent accountability when their results are used. Count distinct eligible
deliverables in the exact current evaluation set, with declared coverage; historical fulfillment rows
and successive revisions do not add to cardinality. The old YAML and universal-node model below are
historical notation, not the current contract or parser syntax.

Declared on every agent-bearing node: a Stage Graph stage, the Goal Loop executor and
verifier, a subagent configuration. Authoring form (manifest, superset of today's `outputs`):

```yaml
outputs:
  - name: findings_report              # Slug, unique per node
    kind: document                     # §3.2
    level: required                    # required | expected | optional
    cardinality: { min: 1, max: 1 }    # default {1,1}; max may be "n"
    accumulation: per_unit             # per_unit | across_cycles | across_iterations | mission
    collect: outputs/findings_report/**   # path glob under the writable slot; default outputs/<name>/**
    content_types: [text/markdown]     # kind-specific; defaults per kind
    validators:                        # ordered; kind-specific vocabulary, §3.4
      - evidence_backed: { min_citations: 3, resolve: registered_evidence }
      - max_bytes: 262144
    derives_from: []                   # names of obligations (same node or upstream) whose digests must appear in the lineage
    transfer:                          # defaults a consumer inherits unless its input overrides
      tier: materialize
      summary: first_heading_and_abstract
```

Runtime form: `Obligation` in `domain/programs/obligations.py` (frozen contract,
`mc.obligation.v1`), lowered into `StageOutputSlot`'s successor `ObligationSlot` on the
blueprint. The existing `validation_schema: OutputSchemaBinding` becomes the `structured_record`
kind's schema validator; `required: bool` becomes `level`. Legacy slots (`required=None`) are
compiled as `level: expected`, kind `document`, so an empty prose result becomes a recorded
shortfall instead of a silent admission (§1 fact 1). Manifest v2 validation requires at least
one obligation on every agent-bearing node (OC-D1).

Cardinality and accumulation together model "n reports": `cardinality {min: 3, max: n}`,
`accumulation: across_cycles` means the count is taken over every cycle of the stage and the
stage's cycle region closes when `min` is met. `derives_from` models "a PDF with images created
from the report": the PDF obligation's fulfillment record must name the report's digest in its
lineage (`artifact_relation` row with `relation_kind=derived_from`), which the reducer checks.

### 3.2 Output kinds (closed set v1)

**Superseded classification, OC-D115.** Use `text`, `structured`, `file`, `collection`, `reference`,
`code_change`, `effect_receipt` and `control_record`, composed with admitted versioned templates or
inline contracts. Domain nouns below are examples, not closed kernel kinds. No new catalog kind is
inferred from this notation. OC-D20's historical warning/cardinality limits remain unless revised;
they are not evidence of current installation settings.

Two families for work, one for control. Provider-specific kinds live under the discriminated
`provider_outputs.<lane>` container and are not in v1.

| Kind | Family | Submission form | Mechanical checks at the reducer | Default tier to a consumer |
| --- | --- | --- | --- | --- |
| `document` | knowledge | file(s) under `collect`, text media | media type in allowlist; UTF-8; non-empty; `max_bytes`; validators (`evidence_backed`, `sections`, `min_words`) | `materialize` whole; `reference` above the lane floor |
| `file_artifact` | knowledge | file(s) under `collect`, any media | digest matches custody; `content_types` allowlist (`application/pdf`, `image/*`, `application/zip`, ...); `max_bytes`; binary needs a sandbox backend on Deep Agents (`AUDIT §B3`) | `materialize` (binary never inline) |
| `structured_record` | knowledge | one JSON file or the `submit_output` payload | today's `OutputSchemaBinding` check (`artifact_validation.py`); a schema outside the supported subset is a **compile error**, not a silent skip (`AUDIT §A1`) | `inline` when under the inline cap, else `materialize` |
| `code_change` | codebase | `form: branch_head` (mission branch ref, base SHA, head SHA **observed by the harness**, changed-paths digest) or `form: patch` (a unified diff file for lanes without git, e.g. Deep Agents StateBackend) | head observed, not model-claimed (`MissionBranchHead`, `AUDIT §A6`); non-empty diff; changed paths within declared roots; optional `checks_receipt` validator (a named check ran and passed, receipted) | `workspace` (snapshot or branch) for a code consumer; `reference` with the head for a knowledge consumer |
| `verdict` | control | the verifier's typed observation (`GoalVerifierObservation`, or a review stage's `ReviewDisposition`) | parses; `decision` in the closed set; `findings` typed (§4.5); every `unmet_obligation` names a declared obligation | `inline`, mandatory |
| `handoff` | control | the typed `GoalHandoffDraft` plus `invariants` (new field, `08-CONTINUATION:54`) | parses; min lengths as today; every artifact ref registered; `continuation_instructions` present | `inline` (state) + `materialize` (`HANDOFF.md`, `checkpoint.json`), mandatory |
| `decision_record` | control | the cycle evaluation of a producer (`evaluation`, `cycle_scope`, `next_objective`, `invalidation_frontier`, refs) as one typed record instead of loose result keys (`AUDIT §A1`) | parses; contract refs equal the policy's; `next_objective` present when `evaluation == cycle` | `inline`, mandatory to the re-run stage |

The knowledge/codebase distinction is not cosmetic. The two families differ in **where custody
lives** (artifact store versus git), **what the harness observes** (bytes and digests versus a
head SHA read back), **the default transfer tier** (materialize bytes versus restore a
workspace) and **which lanes can produce them** (any lane produces knowledge kinds; `code_change`
needs git or a patch form). A Deep Agents node may declare `code_change` with `form: patch`
(not forbidden, as the owner directs), and the harness will not pretend it has a branch head.

**Flexibility, catalog and limits (revision 2, the owner's questions; decisions OC-D19..D21).**
Kinds stay a closed kernel set because each kind carries a mechanical checker and a transfer
default; customization lives in **instances** (any number of named obligations per node),
**validators** (parameterized) and **obligation templates**: a new catalog kind
`obligation_template` (digest-pinned like a skill bundle: "evidence-backed report", "PR-ready
change", "test report", "brief with figures") that a manifest uses by pin or search
(`template: catalog://obligations/evidence-report@2`) or overrides field by field. A node's
obligation count has a **soft limit** (default 8, a compile warning) and `cardinality.max` a
**ceiling** (default 64 items, a refusal), both installation settings; the reason is verification
and transfer cost. Codebase work is first-class from v1: `code_change` (both forms), a
`test_report` template, validators `paths_within`, `non_empty_diff`, `checks_receipt`, and the
`workspace` tier to a code consumer.

### 3.3 Submission: two channels, one ledger

**Superseded channel model, OC-D83/89/114.** `submit_output` is the one progressive/final output
submission act. Final messages and model `output_refs` are not parsed as submissions or claims.
Qualified declared files plus `SUBMISSION.json` are a degraded route through the same module, with
narrow attributable auto-association and bounded repair/refusal. Persist submission revisions,
assessment, exact-set fulfillment and invocation finalization separately. The two equal channels
and one-result-row scheme below must not be implemented from this historical text.

Both channels end in the harness registering a candidate (digest, size, media type, slot,
path, point ref) and emitting an `output_submitted` frame. The agent never writes a table and
never names a point (TR-D9 kept).

- **Channel A, declared-path collection (implicit).** At unit end the harness collects every
  file matching each obligation's `collect` glob under the writable slot, registers candidates
  and attributes them to the obligation. This is today's writable-slot capture made
  per-obligation and bounded by the obligation's cardinality and `max_bytes`. Files under the
  writable slot that match no obligation are registered as `unattributed` candidates (kept
  for the transcript, never fulfilling anything, listed in the fulfillment record).
- **Channel B, explicit submission (progressive).** A lane tool `submit_output(obligation,
  path | payload, note?)` emits one custom stream event the recorder turns into an
  `output_submitted` frame keyed `deep_agents_key(thread, ns, None, step, f"submit:{obligation}:{n}",
  "output_submitted")` (idempotent by provider key, mirrors the `progress_note` design of
  TRACING-PROPOSAL P7). The harness registers the candidate immediately and returns the
  durable ref to the agent. This enables cumulative outputs visible mid-run, a dashboard
  showing "2 of 3 reports submitted", and replaces the impossible "artifact custody tools"
  instruction (`AUDIT §D5`). A submission for an undeclared obligation returns a typed refusal
  to the agent and is recorded as a `rejected_submission` frame.
- **The final message is not a submission channel.** The model-emitted `output_refs` key is
  read as a **claim** and reconciled against registered candidates; a claim naming an
  unregistered ref is a recorded finding, never an output. The Stage Graph payload merge
  (`stagegraph.py:770-773`) is changed so registered refs win (OC-D4). This restores
  `context-and-continuation.md:55`.

The ledger: candidates (today's descriptor table), `output_submitted` frames, and one
**`obligation_fulfillment` row per obligation per unit result** (`mc.obligation_fulfillment.v1`:
run, unit key, activation, obligation name, kind, status, cardinality observed, candidate
refs, validator results, lineage refs, point ref, decided_at), written in the settlement
transaction beside `completion_candidate` and `completion_decision`. The fulfillment rows are
what a cycling stage, a Goal iteration and the coordinator read (`missionctl run outputs RUN
--at stage:S2,cycle:1`, the hook the coordinator-surface proposal reserves).

### 3.4 The fulfillment check at the reducer

**Current revision, OC-D39/75/91/108–118.** Required declared guarantees gate fulfillment; resolving
citations or counting files is insufficient for promised semantic/evidence quality. KS owns trusted
assessment/sealing/use semantics and reviewer authority; MC evaluates the obligation using exact
applicable evidence. Optional review can annotate only when no mandatory guarantee requires it.
Count distinct current eligible members and coverage. The original fixed timeout/outcome examples
below do not override admitted recovery limits or current separate record semantics.

Pure function in `domain/programs/obligations.py::check_fulfillment(obligations,
candidates, lineage, lane_caps) -> FulfillmentReport`, with custody reads done beforehand by
`application/programs/fulfillment_service.py` (which replaces the inline logic of
`output_binding_errors`, `output_slot_refs` and `validate_completion`). Per obligation, in
order, stopping at the first failure:

1. **Attribution and cardinality.** Candidates attributed by `collect` or by explicit
   submission; count within `{min, max}` for the accumulation scope (across cycles counts the
   stage's prior fulfillment rows).
2. **Custody integrity.** Each candidate's bytes present, digest and size match the
   descriptor; a `branch_head` observed by the harness for `code_change`.
3. **Kind check.** Media type, parse, schema, head and diff rules of §3.2.
4. **Declared validators**, in declared order, each a typed `ValidatorResult{name, status,
   reason_code, evidence_digest}`. v1 validator vocabulary: `max_bytes`, `min_words`,
   `sections` (required headings), `json_schema` (the `structured_record` default),
   `content_types`, `evidence_backed` (citations resolve to registered evidence refs or, when
   Knowledge Services is admitted as a capability, to its evidence ids; absent that, to
   `artifact://` refs in the run), `checks_receipt` (a named check's receipt is present and
   `passed`), `derived_from` (lineage digests present).
5. **Lineage** for `derives_from`.

Outcomes are typed, never prose. The unit's completion disposition is derived:

| Fulfillment pattern | Reducer outcome | Reason codes |
| --- | --- | --- |
| every `required` fulfilled; `expected` fulfilled or shortfall | `accepted` (`accepted_with_findings` when any shortfall) | `shortfall:<name>` recorded as findings |
| any `required` missing | `not_accepted` | `outputs_missing:<name>` |
| any `required` invalid | `not_accepted` | `outputs_invalid:<name>:<reason_code>` |
| submission for undeclared obligation only | `not_accepted` | `outputs_missing:<name>`, `undeclared_submission:<name>` |
| custody pending (publication not yet visible) | pending, as today, 15 min, then `artifact_publication_deadline_exceeded` | unchanged |

Acceptance is mechanical. Whether a report is *good* is a `verdict` from a verifier node or a
human review; the reducer never judges content. This keeps `01-STAGE_GRAPH.md:131-133`
("production is not schema conformance, which is not acceptance") and gives each its own
checkpoint.

A `not_accepted` result on a Stage Graph stage follows the existing rejection path; on the Goal
executor it becomes a typed executor observation with `disposition: failed` and the fulfillment
report attached, which the verifier sees (this is also the F-T3-1 fix shape, §3.6).

### 3.5 Accepted deliverables become artifacts

**Current revision, OC-D64/70/114.** Application-owned bytes/native identities retain their owner;
MC keeps orchestration registrations, references and delivery/custody evidence. Selective retained
results are allowed; universal copying into MC is not required. Explicit independently eligible early
exports are distinct from accepted final composite output. The release number and universal promotion
prescription below are historical, not the current migration plan.

Today accepted outputs stay `workspace-candidate://` and cannot be downloaded (`AUDIT §A3`).
On acceptance, the settlement promotes each fulfilling candidate to an `artifact` row
(`custody_state=registered`, `kind` = output kind, `schema_ref`, `media_type`, digest, size)
with two additions in release 1.4.5: `producer_point_ref` (the result point) and an
immutability trigger on `artifact` matching the sibling tables. `artifact_relation` rows carry
`derived_from` and `fulfills(obligation)`. The download route accepts `artifact://` as today;
`workspace-candidate://` becomes downloadable for inspection of unaccepted candidates
(`run artifact get`, the CLI noun the coordinator-surface proposal adds). Promotion is in the
settlement transaction so a deliverable exists exactly when its result is accepted.

### 3.6 Fixes folded into this work

**Current revision.** Retire final-message/`output_refs` parsing and legacy auto-obligation generation
rather than create a precedence rule between competing submission authorities (OC-D83/89). The
historical fixes below are dispositioned by the current contract §14 and WORK-ITEMS, not a second backlog.

- `stagegraph.py:770-773`: registered refs win over the model's `output_refs` (OC-D4).
- `stagegraph_builder.py:129-136`: legacy slot becomes `level: expected`, not `required=None`.
- `manifest_service.py:928-929`: unsupported schema subset is a compile error.
- `manifest_launch_inputs.py:1851-1858`: the contract segment names `submit_output` and the
  `collect` paths, not "artifact custody tools".
- F-T3-1 (`activities/goal_directed.py:131-138`, `workflows/goal_directed.py:1922-1929`,
  `materializer.py:404-413`): a non-parsing executor payload becomes a typed executor
  observation `disposition: failed, reason: output_unparseable` with the fulfillment report,
  settled, not retried; an unregistered schema digest for `response_format` is a compile
  error; retries are bounded. Tracing Stage 2 fixes the first of these three before its live
  Goal Loop; this work keeps the shape.

### 3.7 Subagent obligations and communication obligations (revision 2)

**Revised scope, OC-D71/72/119.** Ordinary helpers need not carry universal output/report/join/must-review
contracts. Explicit helper contracts, result adoption and parent settlement accountability remain.
Special helper construction/tools and the proposed communication shape below are not adopted current
scope. Required-child settlement does not disappear, and historical provider fork defaults are not
reintroduced by these examples.

Subagents are compiled from the mission contract, so they are agent-bearing units like stages
and iteration roles, and they owe obligations. Today they owe nothing: `mc.subagent_profile.v1`
has no result declaration, a sync child answers in free text, and an async child's
`result_schema_ref` is stored and never validated (`domain/capabilities/subagents.py:159-203`,
`application/authoring/lanes/deep_agents.py:102-106`, SUBAGENTS.md:98). Deep Agents already has
the carrier: a per-child `response_format` whose JSON becomes the child's tool result, and state
merge-back of `files` and custom keys (research sheet §3.1).

**Output obligations on a subagent profile** (`outputs:` in the node schema; kinds limited to
`structured_record`, `document`, `file_artifact`, `verdict`):

| Shape | Submission | Checked when | Recorded as |
| --- | --- | --- | --- |
| sync `task` | `structured_record` through the child's `response_format`; files under `/subagents/<name>/outputs/<obligation>/` | when the `task` tool returns (a `wrap_tool_call` on `task`) | candidates of the **parent's** unit attributed to the child, one `obligation_fulfillment` row per child obligation |
| async (Agent Server) | the same, read from the child thread | at admission, when the parent checks the task (WP-S4) | the same |
| dynamic (QuickJS `task()`) | the script's `responseSchema`, narrowed from the profile's | when the promise resolves (the bridge's tool call) | the same; a dispatch to an undeclared type is refused |

**Communication obligations** (the owner's term; checking in is a pull tool, not a callback):
the child's `report: on_return | progress(every: N model calls) | on_request` (progress through
`submit_output(progress)` or a `progress_note` frame, so it is durable and visible to the
coordinator, not only to the parent model); the parent's `join: all | any | none` before its unit
may settle (an async child still running is a typed outcome: wait, cancel or detach as
authored); `must_review: true` makes a parent obligation `derives_from` the child's deliverable.

**A child's obligation failure** is a finding on the parent's fulfillment report unless the
parent declared `must_review` or `derives_from`, in which case the parent's obligation is
`invalid(child_obligation_unmet)`.

**Inheritance defaults** (transfer point T6): `isolated` (the task description) plus the parent's
`/.mission/state.json` and the inputs the profile lists; `fork` mode (0.7.30, experimental, no
nested `task`) only by explicit choice; state merge-back only for keys the profile names (0.7.5
merges every non-excluded key back).

## 4. Mission State Transfer

### 4.0 The transfer points (revision 2)

T1 stage start, T2 cycle re-run, T3 iteration start, T4 executor to verifier, T5 session rollover,
T6 parent to subagent, T7 subagent to parent, T8 fork, T9 linked run, T10 human review. Each is a
`purpose` of the transfer policy (§4.2 adds `subagent_spawn`, `subagent_return`, `chain_link`,
`review`); their state today and the strawman for each are tabled in the interview, round R1b.

### 4.1 Three depth layers and the precision rule

**Current revision, OC-D116/123/124.** Effective consumer requirements determine required content
and forms. One sealed plan selects exact inputs; separate attempt receipts prove delivery/readiness.
Required current-set detail may be a readable index; history remains bounded opt-in. Held repair
content may be required and materialized. The original layers remain explanatory representations,
not permission to replace required bytes with a reference.

The owner's concern is two-sided: the next unit must receive **exactly the most important
outputs**, and **everything deeper must stay reachable** for a fork, an analysis or a deliberate
wider transfer. The model is three layers, each with a default tier and a handle to go deeper:

| Layer | Content | Default tier | Deeper handle |
| --- | --- | --- | --- |
| **Deliverables** | the fulfilled obligations of producers the consumer depends on, as registered artifacts | `materialize` into `/inputs/<binding>/...`; `reference` above the lane floor; `workspace` for `code_change` to a code consumer | `mission_fetch(ref)` tool and `missionctl run artifact get` |
| **State** | typed facts: the producer's fulfillment report, `released_by` with release kinds, verifier `verdict` and findings, unmet obligations, the `decision_record`, the progress observation, the handoff, budgets remaining, obligations **this** unit must submit | `inline`, mandatory, as `/.mission/state.json` plus the rendered section of `context.md` | the same file, whole; never truncated (mandatory) |
| **History** | the transcript, the cognition points, promoted tool results, conversation history archives, prior packets, workspace snapshots | `reference` always, with working fetch handles (`missionctl run transcript RUN --by step --point ID`, `mission_fetch(point)`); `materialize` only by explicit manifest `history: materialize` or an owner's fork-time instruction | `state-as-of`, `run fork --at --point` |

Precision is the default tiering above. Depth is that every layer has a handle that works
(`AUDIT §D5` is fixed by implementing `run artifact get`, `run context-item`, and the
`mission_fetch` tool on the Deep Agents lane, budget-bounded and observed as frames).

### 4.2 The transfer policy module

**Current revision.** Registered or inline profiles compile through effective configuration;
hard constraints combine. H1–H9 below are historical heuristics: H5 cannot demote required held
repair content, H7 cannot load every producer instead of an exact qualifying selection, and H9
cannot weaken required forms under budget pressure. Use only explicitly allowed satisfying
alternatives or block. No literal retrieval tool name is promised without qualification.

`domain/context/transfer_policy.py` (pure) exposes
`plan_transfer(request: TransferRequest) -> TransferPlan`:

- `TransferRequest`: `purpose` (stage_start | cycle_rerun | iteration_start | rollover |
  fork | continuation), `consumer` (node key, declared inputs with `expand` overrides, the
  instruction references found by the renderer, lane capabilities: writable, text-only,
  materialize floor, budget), `producers` (per dependency: release kind, provisional flag,
  fulfillment report, deliverables with digests and sizes), `state` (the typed facts of §4.1),
  `history_handles`, `overrides` (manifest `transfer:` block, fork-time instruction).
- `TransferPlan`: ordered `PlannedItem{binding, layer, source_kind, ref, tier, path, mandatory,
  provenance{producer point ref, release kind, provisional}, heuristic_id}`, `omissions` with
  reasons, `plan_digest`.

The heuristics are **data**: an ordered tuple `HEURISTICS` of `(id, predicate, action)`
evaluated first-match per candidate item, so a later turn reorders or adds without touching the
packer. v1 order (answers question (g) of the earlier instruction, amended):

| Id | Rule |
| --- | --- |
| H1 | A fulfilled `required` or `expected` deliverable bound by a consumer input (`inputs[].from`) is materialized whole at `/inputs/<binding>/`; a `code_change` deliverable bound by a codebase consumer is a `workspace` item (snapshot or branch restore). |
| H2 | A deliverable the consumer's instructions cite by placeholder `{{inputs.<binding>.path}}` is materialized at that path; the renderer resolves the placeholder to the real path. |
| H3 | State-layer items are inline and mandatory; they are never downgraded, so a packet that cannot hold them fails typed (`CONTEXT_BUDGET_EXCEEDED`), as today. |
| H4 | A deliverable above the lane materialize floor that is not bound by H1 or H2 is referenced with digest and summary; binary is never inline. |
| H5 | A provisional deliverable (Provisional Binding) is referenced only, flagged provisional, never mandatory (existing packet validator), and re-delivered at the producer's acceptance if the consumer is still active. |
| H6 | History-layer items are referenced, never materialized, unless `transfer.history: materialize` is authored or an owner fork instruction asks. |
| H7 | On an `any` or quorum release, deliverables of **every** satisfied producer are transferred (H1 tiering), with the releasing set named in state; unsatisfied producers are listed as pending. |
| H8 | A `derives_from` lineage source is referenced beside its derived deliverable. |
| H9 | Budget overflow downgrades optional items in reverse priority (history, then unbound deliverables, then bound deliverables to reference); mandatory items never. |

`pack_for_stage`, `pack_for_iteration` and `pack_for_continuation` become thin: build the
request, call the policy, hand the plan to the materialization service. The decision logic now
inline in `pack_service.py:304-630` moves into the heuristics.

### 4.3 Dependency kinds: what releases, what transfers

**Current revision, OC-D139–148/162.** Separate ordering, data selection, permitted use and actual
delivery. Any/quorum selects exact eligible members; optional omissions are visible. Conditional
routing chooses explicit all-matching or ordered first-match mode; unknown is not false and else
requires conclusive false. Expansion freezes membership. Incremental synthesis batches arrivals;
only the selected synthesis revision/reassessment cases gain automatic revalidation. The old
all-producer/provisional-reference-only/universal-redelivery rules below are superseded.

The accepted text (`01-STAGE_GRAPH.md:34-64`) distinguishes a Dependency Edge (ordering), a
Data Binding (typed output to input), a Provisional Binding, the expression
`all | any | quorum | conditional` and the dependency classes. The code keeps only `all` +
`required` from slot 0 (`AUDIT §B4`). This work implements lowering and release recording for
the following; the transfer column is the policy default.

| Dependency kind | Releases when | Transferred by default | Provisional propagates |
| --- | --- | --- | --- |
| Data Binding, `required` | producer **accepted** with the named obligation fulfilled | that deliverable, H1; producer state inline | no |
| Data Binding, `degradable` | producer accepted, or degraded per class rules | deliverable if present, else a typed `absent_input` state fact | no |
| Data Binding, `optional` / `advisory` | not required for release | deliverable at `reference` when present | no |
| Dependency Edge (no binding) | producer accepted | producer **state only** (fulfillment summary, verdict); deliverables at `reference` | no |
| Provisional Binding | producer **submitted** (fulfillment computed) but not yet accepted | H5: reference, provisional, re-delivered on acceptance | **yes**: the consumer's own result is marked provisional until every provisional input is accepted; provisional output never passes a gate (`01-STAGE_GRAPH:135`) |
| `join: all` (default) | every edge satisfied | union of the above | — |
| `join: any` / `quorum: n` | ≥1 / ≥n satisfied | H7: every satisfied producer's deliverables; releasing set in state | — |
| `conditional` (typed predicate on fulfillment facts, e.g. `producer.S2.outputs.report.cardinality >= 2`) | predicate true on typed facts; never prose | the facts the predicate read, inline; deliverables per binding | — |
| Human review disposition | the Human Task resolved `accepted` | the disposition and reviewer note inline, mandatory | — |

`released_by` is corrected to carry the **releasing** dependencies with their kinds (today one
entry per incoming dependency, `AUDIT §B4`), and a `release_kind` typed fact is written on the
activation so the policy and the transcript cite it. Named producer outputs (`from:
S1.findings_report`) bind that obligation, not slot 0. The input `required` flag survives
lowering. `conditional` is in v1 with a closed predicate grammar over fulfillment facts and
verdicts only (OC-D9).

### 4.4 Cycles (K05)

A re-run cycling stage receives, in addition to its upstream bindings:

- **State, inline, mandatory:** its own prior cycle's fulfillment report; unmet obligations;
  the `decision_record` that triggered the cycle; the verifier or review findings if a
  verdict triggered it; a typed **progress observation** `ProgressObservation{kind:
  objective_changed | obligations_closed | findings_resolved | none, evidence_refs}` replacing
  "the objective string changed"; the cycle ordinal and the cap.
- **Deliverables:** its own prior cycle's deliverables at `reference` by default, materialized
  when `cycles.carry: deliverables` is authored or its instructions cite them (H2).
- **Workspace:** carried from the prior cycle's result point snapshot by default for a node
  whose obligations include a `code_change` (fork from point, so edits accumulate); fresh by
  default for a knowledge-family node unless `cycles.workspace: carry`.

The cycle cap becomes a **governed outcome**: at `max_cycles` the stage settles
`not_accepted(cycle_cap_exhausted)` and the workflow applies the authored `on_cap` policy
(`fail_run | accept_best_effort | human_review`), never an exception (`interpreter.py:568-569`).
Cycles become **authorable**: a `cycle:` block on a stage (`region: [S2, S3]`, `max_cycles`,
`progress: required | advisory`, `on_cap`, `carry`), lowered to `StageCyclePolicy`, which today
nothing in the manifest sets (`AUDIT §B4`). The cycle trigger remains the producer's
`decision_record` (now a typed output kind) or a verifier `verdict`, not loose result keys.
Each cycle's input point keeps its `cycle_start` parent, and the plan digest is stamped on it.

### 4.5 Goal Loop (K04, the handoff, K02)

**Current revision, OC-D119/133/134/137/138.** Host-authoritative state accompanies each boundary;
the continuing Goal Loop profile requires a separate attributed progress note. Provide the complete
exact current-set index, selected repair inputs and bounded optional history; the verifier does not
inspect only the latest iteration's outputs. Repair forks use exact task-relevant historical drafts
and findings. A semantic note or point seed alone proves neither required delivery nor readiness.

Iteration N+1's executor receives:

- the **handoff** of iteration N as a `handoff` deliverable (mandatory inline state plus
  `HANDOFF.md` and `checkpoint.json` materialized, as today), with the new `invariants`
  field; because `handoff` is now a `required` executor obligation, a missing handoff is
  `outputs_missing:handoff` on the executor, surfaced to the verifier, not a silent
  `handoff_missing` rollover pause;
- the verifier's **verdict and findings** of iteration N, inline, mandatory (K04); findings
  are typed `Finding{obligation, severity, kind: missing | invalid | quality | scope, text,
  evidence_refs}` rather than free strings;
- iteration N's **deliverables** under `/inputs/iterations/<n>/<obligation>/` (H1 for the
  obligations the goal's `required_output_contracts` name; reference otherwise), not only
  what the executor chose to list in `handoff.artifact_refs`;
- the **mission-level cumulative obligation status** (which goal deliverables are fulfilled so
  far, by accumulation `across_iterations` or `mission`), inline;
- the unmet obligations of the accepted revision, as today.

The verifier receives the executor's deliverables as provisional (as today) plus the
executor's fulfillment report, so it verifies real outputs and not claims.

Session rollover (K02) on this lane: the fresh session is seeded from the previous session's
result point through `seed_fork` with the `rollover_start` parent (deeper history reachable)
**and** receives the handoff packet (OC-D12). `pack_for_continuation` remains the Session Lane
path; the Deep Agents hydrator is either wired for this or deleted (OC-D13).

### 4.6 The materialization deep module

**Current revision, OC-D122.** One host materialization entry point uses boundary-specific state
builders, one sealed transfer plan and separate attempt delivery/readiness receipts. Actual backend
access and aggregate budgets gate readiness. The old shapes below illustrate a proposal; they do
not establish a second selection authority or a currently qualified API.

`application/context/materialization_service.py` (lane-neutral) takes a `TransferPlan` and a
`MaterializationBackend` port and produces the files, the instruction segment and the
`transfer_planned` frame. Lane adapters implement the port: Deep Agents writes state files or
uploads to the sandbox (today's `seed_backend_files`), Session Lanes write the workspace.
Standard layout under the unit's mount root:

| Path | Content | Layer |
| --- | --- | --- |
| `/.mission/context.md` | rendered index, inline blocks, omitted list (as today) plus a **State** section and an **Obligations** section ("you must submit ...", with `collect` paths and `submit_output` usage) | all |
| `/.mission/state.json` | `mc.mission_state.v1`: the typed state facts of §4.1 | State |
| `/.mission/obligations.json` | `mc.unit_obligations.v1`: this unit's obligations, kinds, cardinality, collect paths | State |
| `/.mission/inputs.json` | manifest of materialized inputs (as today) | Deliverables |
| `/inputs/<binding>/...` | materialized deliverables; `/inputs/iterations/<n>/...` on the Goal Loop | Deliverables |
| `/outputs/<obligation>/...` | the writable collect roots, created empty | submission |
| `/goal/HANDOFF.md`, `/goal/checkpoint.json` | as today, paths taken from the workspace policy, not hard-coded (`AUDIT §B3`) | State |

The instruction segment is generated from the plan: one line per item with name, layer, tier,
path or fetch handle, digest; `{{inputs.<binding>.path}}` placeholders in authored instructions
are resolved. Deep Agents provider-specific detail (state backend text-only, sandbox upload,
skills files) stays under its discriminated container in the `environment_materialized` frame,
which also records the **middleware stack** (today absent, `AUDIT §C`).

### 4.7 Point links and observability

**Current revision, OC-D125/126/176.** Focused configuration/input/output/fulfillment/transfer inspection
and actionable durable coordinator wakes are selected. Optional configured content delivery stays
bounded by receiving authority and budget. Host wake, model-visible delivery, acknowledgment and
content read need separate proof. The global CLI redesign and literal command spellings below are
not approved by this scope selection.

- The consumer's input point carries `parent_coordinate` as today and a new
  `transferred_from: tuple[CognitionCoordinate, ...]` naming every producer result point whose
  deliverables or state were transferred, plus `transfer_plan_digest`.
- Frames: `transfer_planned` (the plan digest, item count per layer and tier, omissions),
  `output_submitted`, `rejected_submission`, `obligation_fulfilled` (one per obligation at
  settlement, projected into the stage group of the transcript beside `released_by` and the
  completion row).
- Stream: the same three as public events with `unit_key`, `point_ref` and location on the
  envelope (the coordinator-surface proposal's CS-D5), so a dashboard can render "S2 submitted
  2 of 3 reports; S3 released by S2 with report_1 materialized".
- Reads: `missionctl run outputs RUN --at <coordinate>` (fulfillment rows), `missionctl run
  inputs RUN --at <coordinate>` (the plan as materialized), both reserved by the
  coordinator-surface proposal (CS-D10) and implemented here.

## 5. Deep Agents context-engineering adoption

**Historical provider proposal.** Recheck current source/provider qualification; these versions,
adoption steps and inferred defaults do not control the IQ-07 implementation sequence.

Grounded in `AUDIT §C` and, since revision 2, in
[DEEP-AGENTS-SURFACE-2026-10-22.md](../../../provider-consolidation-2026-10/providers/deep_agents/DEEP-AGENTS-SURFACE-2026-10-22.md): installed
`deepagents==0.7.5`, `langchain==1.3.14`, `langgraph==1.2.10`, `langchain-openai==1.3.4`; latest
0.7.30, 1.4.7, 1.2.16, 1.7.2 (the older fast-track sheet's "0.7.23 and 1.4.3" were never
installed). Facts that change this section:

- **Every middleware below is selectable only once the agent-configuration language exists**
  (interview R3: `lane_features.deep_agents.*`); today the stack is fixed
  (`adapters/deep_agents/materializer.py:340-366`).
- **The todo list is not in the default stack** of either version; it is an explicit selection.
- **OpenAI built-in tools** (`web_search`, `file_search`, `code_interpreter`, `image_generation`,
  `mcp`, `tool_search`) are dict tools routed to the Responses API that never enter the ToolNode:
  no `wrap_tool_call`, hook, HITL or call limit sees them. They are model tools (interview R3,
  layer 3) recorded from the model's `server_tool_call`/`server_tool_result` content blocks, a
  frame kind the recorder does not have yet.
- **0.7.30's stock `AsyncSubAgentMiddleware`** gains hooks that append the child's result to the
  parent's messages before Mission Control admits it: the governed wrapper must keep reusing only
  the stock tools, and `notify_parent=False` where Mission Control owns delivery.
- **Dynamic subagents** (`langchain_quickjs.CodeInterpreterMiddleware`, pinned 0.3.5, unused)
  dispatch children that bypass the parent's HITL: gate `eval` itself, and only after §3.7 exists.
- **State and context**: both schemas are already passed to `create_deep_agent`, built from the
  operator scaffold, and no middleware reads `runtime.context`. Revision 2 proposes the context
  schema as the only identity source and three Mission Control channels with reducers
  (`mc_obligations`, `mc_children`, `mc_transfer`), evidence never authority (OC-D24).
- **The upgrade first**: LangGraph 1.2.13-1.2.16 fix DeltaChannel forks and resume (the precise
  fork depends on them; Stage 3 found the seed head reading a delta channel's pending writes),
  and 0.7.25 fixes a symlink bypass of filesystem permissions.

Adopt in this order, each behind the lane profile, each observed (a frame and a point) and
receipted under the `deep_agents` container:

1. `FilesystemMiddleware` eviction limits set from the lane profile; evicted
   `/large_tool_results/*` files registered as `evicted_tool_result` artifacts linked to the
   step's point, so a fork from that point still sees them.
2. `ContextEditingMiddleware(ClearToolUsesEdit)` after the observed summarizer; each clearing
   emits `mc.context_edited` (which tool uses, token counts) and the cleared bodies remain
   reachable through the promoted `frame-body://` refs of Stage 1 (nothing is lost, only
   removed from the model's context).
3. `ToolCallLimitMiddleware` and `ModelCallLimitMiddleware` bound to the unit's budget
   contract; a limit hit is a typed `budget_limit_reached` outcome, not a provider error.
4. `SummarizationToolMiddleware` (`compact_conversation`) exposed only when the lane profile
   enables it; observed as a compaction frame like the automatic summarizer.
5. The version bump to the latest `deepagents` release, executed by the owner per PROCESS §1.3.
   The dated surface block is now refreshed (revision 2); the interview's strawman runs the bump
   first (sprint A), before any adoption above.
6. (revision 2) The todo list, call limits, filesystem permissions and the OpenAI model tools join
   the first batch, through the agent-configuration language (interview R3.4).

## 6. Build order and proofs

**Historical sequence.** The current [work/dependency/proof matrix](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/WORK-ITEMS.md)
replaces the sequence below. Use owner-supplied fixtures after the interview, real independent review
and necessary repair/rerun. Old release numbers and toy examples are not current qualification.

**Revision 2:** the interview's strawman sequence
([OWNER-INTERVIEW-2026-10-22.md §3](../interview-instructions/OWNER-INTERVIEW-2026-10-22.md#3-the-strawman-sequence))
runs two sprints before OC-1: **A**, the Deep Agents upgrade, and **B**, the agent-configuration
language and the first lane features and model tools (the nouns obligations and `submit_output`
attach to). OC-1 then also carries the sync-subagent obligations of §3.7; OC-2 the subagent
transfer points T6/T7; the async admission and communication obligations go to the lifecycle
sprint after OC-3. The table below is the first version's and stays valid inside that order.

Four sessions after tracing Stage 3, each committing per package on a sprint branch, T0 first:

| Session | Builds | Proves (T0 unless noted) |
| --- | --- | --- |
| **OC-1 Contracts and submission** | `Obligation` and kinds; manifest superset and lowering; `submit_output` tool and `output_submitted` frames; declared-path collection; `check_fulfillment` and `fulfillment_service`; `obligation_fulfillment` table and artifact promotion with `producer_point_ref` and the trigger (release 1.4.5, owner executes); the §3.6 fixes; `run outputs`, `run artifact get` | FX-OC-OUTPUT: declared `document` with nothing submitted is `not_accepted(outputs_missing)`; a submitted markdown file is accepted, promoted and downloadable; a model `output_refs` claim naming an unregistered ref is a finding and not an output; `code_change` with `form: patch` accepted only with a non-empty diff; a `structured_record` with an unsupported schema fails compile. FX-OC-CUMULATIVE: `cardinality {min: 2}` across two submissions in one unit. |
| **OC-2 Transfer policy, materialization, dependency kinds** | `transfer_policy.py` with `HEURISTICS`; `materialization_service.py` and the backend port; `state.json`, `obligations.json`, `/outputs/<obligation>/`; `mission_fetch` tool and the fetch commands; released-by correction and `release_kind`; lowering of `any`/quorum, classes, named outputs, Provisional Binding, `conditional`; `transferred_from` and `transfer_planned` | FX-OC-TRANSFER: the dependent stage's first model call sees the upstream deliverable at the planned tier, its `context.md` names the path, its input point lists the producer's result point, the activation records the release kind. FX-OC-ANY: an `any` join transfers both satisfied producers. FX-OC-PROVISIONAL: a provisional input is referenced and the consumer's result is marked provisional until acceptance. |
| **OC-3 Cycles and Goal Loop** | authorable `cycle:` block; K05 deliveries; progress observation; governed cap with `on_cap`; K04 typed findings delivery; `handoff` as a required obligation with `invariants`; iteration deliverables under `/inputs/iterations/<n>/`; K02 seed-from-point rollover | FX-OC-CYCLE: a manifest-authored cycling stage re-runs with its prior fulfillment, unmet obligations and decision record inline, and settles `cycle_cap_exhausted` at the cap. FX-OC-ITERATION: iteration 2 sees iteration 1's verdict, findings and deliverables. FX-OC-ROLLOVER: generation 2 seeded from the result point with `rollover_start` and the handoff. |
| **OC-4 Deep Agents surface** | §5 items 1–4, the refreshed surface block, the bump if confirmed | FX-OC-CTXEDIT: a scripted run long enough to evict and clear; the evicted and cleared material is observed, receipted and reachable from the point; a fork from the point sees it. |

One T2 proof after OC-3, under 15 USD, models named by the owner: the §1 tracing mission with
real obligations (two `document` reports in S1 and S2, a `file_artifact` PDF in S3 derived from
them, a `verdict` review in S4), read end to end in the transcript files the way Stage 2 writes
them.

## 7. Manifest examples

**Historical illustrative syntax.** These examples do not establish supported current parser fields
or override IQ-07's general forms, single submission protocol, current sets or exact transfer rules.

Knowledge mission, the owner's "n reports and a PDF":

```yaml
stages:
  - key: research
    outputs:
      - name: report
        kind: document
        cardinality: { min: 3, max: 5 }
        accumulation: across_cycles
        validators: [{ evidence_backed: { min_citations: 3, resolve: registered_evidence } }]
    cycle: { region: [research], max_cycles: 3, progress: required, on_cap: human_review, carry: deliverables }
  - key: publish
    depends_on: [research]
    inputs:
      - name: reports
        from: research.report
        expand: materialize
    outputs:
      - name: brochure
        kind: file_artifact
        content_types: [application/pdf]
        derives_from: [research.report]
      - name: figures
        kind: file_artifact
        content_types: [image/png]
        cardinality: { min: 1, max: n }
        level: expected
  - key: review
    depends_on: [publish]
    outputs:
      - name: disposition
        kind: verdict
```

Codebase mission, a Deep Agents node allowed but not assumed to have git:

```yaml
stages:
  - key: implement
    lane: deep_agents
    outputs:
      - name: change
        kind: code_change
        form: patch                      # branch_head on a lane with git
        validators: [{ checks_receipt: { check: unit_tests } }]
  - key: verify
    depends_on: [implement]
    inputs: [{ name: change, from: implement.change, expand: workspace }]
    outputs: [{ name: disposition, kind: verdict }]
```

## 8. Decisions for the owner (recommendation marked)

| Id | Decision | Recommendation |
| --- | --- | --- |
| OC-D1 | Every agent-bearing node must declare at least one obligation for manifest v2 to validate; legacy nodes compile as `expected` `document`. | **Adopt.** An undeclared output is the root of silent admission. |
| OC-D2 | The closed v1 kind set of §3.2 (`document`, `file_artifact`, `structured_record`, `code_change` with `branch_head | patch`, `verdict`, `handoff`, `decision_record`). | **Adopt.** Provider-specific kinds go under the discriminated container later. |
| OC-D3 | Enforcement level per obligation (`required` rejects, `expected` records a shortfall, `optional` is silent), rather than one global level. | **Adopt.** |
| OC-D4 | Registered candidates are the only outputs; the model's `output_refs` is a reconciled claim. | **Adopt**, with the `stagegraph.py:770` fix in OC-1. |
| OC-D5 | Two submission channels (declared-path collection and `submit_output`), both harness-completed; no final-message channel. | **Adopt.** |
| OC-D6 | An `obligation_fulfillment` table in release 1.4.5 (versus JSON inside `completion_decision`). | **Table.** Cycles, iterations and the coordinator query it by obligation. |
| OC-D7 | Accepted deliverables are promoted to `artifact` rows in the settlement, with `producer_point_ref` and an immutability trigger. | **Adopt.** |
| OC-D8 | The three depth layers with the default tiers of §4.1; history is referenced never materialized unless authored or asked at fork time. | **Adopt.** |
| OC-D9 | Dependency kinds in v1: `any`, quorum, the four classes, named producer outputs, Provisional Binding with propagation, `conditional` over a closed fulfillment-fact grammar. | **Adopt all**; if one must slip, `conditional`. |
| OC-D10 | Cycle default: knowledge nodes start a fresh workspace and carry deliveries; codebase nodes carry the workspace snapshot. The cap is a governed outcome with `on_cap`. | **Adopt.** |
| OC-D11 | Verifier findings are a mandatory typed inline item to the next executor (K04) and to a cycling stage. | **Adopt.** |
| OC-D12 | Rollover seeds the fresh session from the result point (`seed_fork`, `rollover_start`) and delivers the handoff packet. | **Seed from point.** Deeper history stays reachable. |
| OC-D13 | The unwired Deep Agents hydrator and conversation-history archive: wire for rollover or delete. | **Wire the archive** (it is the History-layer handle for compactions); delete the hydrator if OC-D12 makes it redundant. |
| OC-D14 | `handoff` is a `required` executor obligation with a new `invariants` field. | **Adopt.** |
| OC-D15 | Heuristic order H1–H9 as data in one module. | **Adopt**, revisit after the first T2 proof. |
| OC-D16 | The `mission_fetch` tool and the real fetch commands replace the non-existent ones in packet retrieval instructions. | **Adopt.** |
| OC-D17 | Deep Agents middleware adoption order §5 and the version bump (owner executes). | **Adopt 1–4 now**; bump after the surface block is refreshed. |
| OC-D18 | Transfer policy for lanes other than `deep_agents` is built by the general module now and proven per lane in each provider's sprint. | **Adopt.** The module is kernel; only the backend port is per lane. |
| OC-D19 | (rev. 2) Closed kernel kinds plus catalog **obligation templates** (new catalog kind), versus open kinds with checker plugins or no templates. | **Closed kinds plus templates.** Interview R1.2. |
| OC-D20 | (rev. 2) A soft limit on obligations per node (default 8, warning) and a ceiling on `cardinality.max` (64, refusal), both installation settings. | **Adopt.** Interview R1.3. |
| OC-D21 | (rev. 2) In-turn enforcement: one reminder from a stop-condition middleware when the model tries to finish with a `required` obligation unsubmitted, then judgement at settlement. | **Adopt.** Interview R1.6. |
| OC-D22 | (rev. 2) Subagent output obligations on the profile (§3.7), checked at `task` return, at async admission, and at a dynamic dispatch's resolution, recorded on the parent's unit. | **Adopt** for sync in OC-1, async in the lifecycle sprint, dynamic after OC-2. Interview R2.1, R2.3. |
| OC-D23 | (rev. 2) Communication obligations: child `report`, parent `join` and `must_review`. | **Adopt**; `join` first if one must slip. Interview R2.2. |
| OC-D24 | (rev. 2) The context schema as the only run-identity source for Mission Control middleware; three Mission Control state channels with reducers (`mc_obligations`, `mc_children`, `mc_transfer`), private to child I/O unless declared, evidence never authority. | **Adopt** in sprint B or OC-1. Interview R3.6. |
| OC-D25 | (rev. 2) Verification layers: mechanical fulfillment always; an optional `verify:` per obligation naming a verifier node or a human review, which either gates acceptance or annotates it (author's choice, default annotate). | **Adopt.** Interview R1.4. |
| OC-D26 | (rev. 2) `code_change` on Deep Agents in v1 (patch form), so the kernel is codebase-ready before the code-lane sprints. | **Adopt.** Interview R1.7. |

**2026-10-24, OC-D83 (prerequisite application-knowledge-boundary interview):** the owner revised the
two-channel wording of OC-D4/D5. `submit_output` is the agent's one Mission Control act, progressive
and final; declared-path collection plus a `SUBMISSION.json` convention is the degraded channel for
lanes without a tool surface; the final message is not read at all (no reconciled `output_refs` claim).
Registered candidates remain the only outputs. Record and rationale:
[answers](../answer-sets/application-knowledge-boundary/claude-fable-5-1-2026-10-24/ANSWERS.md).

**2026-10-25, OC-D114/115 (final interview):** OC-D6's durable fulfillment intent is retained,
with submissions, fulfillment and invocation finalization separate; the old release number is
historical. OC-D115 revises OC-D2/19: general kernel forms plus pinned templates or explicit inline
contracts replace closed domain kinds. Control-record authority and substantive validators remain.
See [IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md).

**2026-10-25, OC-D118/119 (final interview):** OC-D3's three obligation levels are confirmed,
separate from acceptance/validity checks. OC-D14 is clarified: boundary-required authoritative state
is host-assembled; agent-authored semantic handoffs are required only where explicitly contracted.
Ordinary helpers retain the optional-obligation rule of OC-D71. See
[IA-09](../answer-sets/output-contracts-final/codex-gpt-6-2026-10-25/ANSWERS.md).

## 9. ADR and knowledge candidates

ADR candidates: output kinds and obligation fulfillment as the acceptance checkpoint; two
submission channels, harness-completed, with the final message as claim only; Mission State
Transfer as three depth layers behind one policy module with heuristics as data; the cycle cap
as a governed outcome; Deep Agents context-engineering adoption conditioned on observation and
receipt. Knowledge concepts touched: `completion` (stale lines 91–92 corrected),
`context-and-continuation`, `environments`, `recovery`, `execution`, `deep-agents-lane`,
`provider-frames-and-transcript`. GLOSSARY: the §2 terms.

## 10. Honest list and open questions

- `evidence_backed` resolution against Knowledge Services depends on an admitted capability
  that this repository does not define; v1 resolves against registered evidence refs and
  `artifact://` refs only.
- `code_change` with `form: branch_head` on Deep Agents needs a sandbox with git; untested.
- The audit could not trace what the Stage Graph workflow does when a stage owns obligations
  and the model omits `obligation_refs` (`AUDIT` honest list); OC-1 must find out before the
  obligation model replaces `obligation_refs`.
- The exact production `exclusive_write_paths` shape is unverified; `collect` globs assume
  `**` globbing on both backends.
- Quorum release on `pack_for_stage` has never run from a manifest; FX-OC-ANY is the first.
- Cost: `submit_output` adds one tool round-trip per submission on T2; acceptable, but the
  T2 proof must record it.
- (rev. 2) F-T3-1 was closed in tracing Stage 2 in the §3.6 shape; Stage 3 folded the
  wrong-contract-ref case into the same typed outcome. The other §3.6 items remain.
- (rev. 2) OC-D4 (registered refs win) is confirmed live twice and is the first fix of OC-1.
- (rev. 2) Model tools (OpenAI built-ins) produce no ToolNode call: an obligation can never be
  "submitted" by a server-side tool directly; the agent must write the result through a channel.
- (rev. 2) Dynamic subagents are pinned and unused; nothing about them is proven on this stack.
- (rev. 2) The lane describe is seeded by the common SQL release: the cells Stage 2 proved
  (cancel at the model call, `usage.cost: unknown`, structured output through the tool strategy)
  ship with release 1.4.5.

---

## Session instruction (revised 2026-10-22; copy into the session's first message)

**Retired launch instruction, 2026-10-26.** Do not execute the branch/stack/build commands below.
The final IQ-07 interview and its current work/proof matrix control. Linked workflows and selected
hooks are now included; their old non-goal entries below are superseded. This text is retained only
as dated process provenance.

**Revision 2:** this instruction runs **after** the owner interview
([OWNER-INTERVIEW-2026-10-22.md](../interview-instructions/OWNER-INTERVIEW-2026-10-22.md)) and after sprints A and B
if the interview keeps them first. Step 3 below then presents only the decisions the interview
left open; the branch starts from `main`, where the tracing sprint is merged.

We are in the provider consolidation program, sprint P1 (`deep_agents`), the output contracts
and Mission State Transfer work, session OC-1 (then OC-2, OC-3, OC-4 per §6). Work in
`platform/mission-control` on a new branch `sprint/output-contracts-1` from the merged tracing
work (commit and push when I say). Follow `docs/specs/provider-consolidation-2026-10/PROCESS.md`
exactly, including §1.3 (standing owner rules) and the owner confirmation step before building.

**Read first, in this order:** PROCESS.md; this document whole; the audit
`AUDIT-OUTPUT-TRANSFER-2026-10-22.md` (every `file:line` you will touch is there); the ledger
`CHANGES.md` entries for turn 4, Stage 1, Stage 2 and Stage 3 (what tracing built and what
Stage 2 found in the transcripts); `docs/specs/coordinator-surface-2026-10/PROPOSAL-COORDINATOR-SURFACE-2026-10-22.md`
§3 and CS-D10 (the `run outputs` and `run inputs` verbs this work implements); the accepted
text `01-STAGE_GRAPH.md`, `02-GOAL_LOOP.md`, `08-CONTINUATION_COMPACTION_AND_TRANSFER.md`;
`docs/knowledge/completion.md` and `context-and-continuation.md`.

**Then:**

1. Restate the goal in one paragraph in my words (§0 owner goals) and confirm it.
2. Re-verify the audit rows this session touches on the live T0 stack (the acceptance tests of
   turn 4 are the harness); record any drift in the ledger. Do not redo the audit.
3. Present the decisions of §8 for this session's scope with the recommendations and wait for
   my answers in one round. Mark anything the re-verification changed.
4. Build what I confirm, as deep modules behind the existing routers, per the §6 row for this
   session; rejections and omissions are typed outcomes, never prose; every new frame and
   point role is in the describe matrix; every lane-specific remainder stays under its
   discriminated container with a signed receipt.
5. Prove on T0 per §6; FX-DA-POINTS, FX-DA-POINTS-SG, FX-DA-FORK, FX-DA-INJECT and the FX-TR
   fixtures stay green. Write each fixture's transcript and mission files under
   `.scratch/output-contracts-1/<fixture>/<run id>/` the way Stage 2 did, so I can read what the
   consumer saw and what it submitted.
6. Document: the ledger entry (one row per change, finished part, proof, checks run, the honest
   list), the knowledge concepts and ADR candidates of §9 touched by this session,
   `python docs/tools/validate_okf.py`, `python docs/tools/agents_docs_index.py`, the next
   session's instruction appended to this document.
7. End with one finished part to read (in reading order), the sequence it sits in, and how I use
   it (one command and what I will see: `missionctl run outputs RUN --at stage:S2,cycle:1`
   showing the fulfillment rows, then `run inputs DERIVED --at stage:S3` showing what S3
   received and from which point).

**Deferred, not dropped** (keep them in the ledger's honest list): from turn 4, F-T4-1, F-T4-2,
F-T4-3, K03, P1-A8..A13; from turn 3, WP-S3, WP-S4, WP-S5, F-T3-2 and the seeded child observed
using its tool and Skill; F-T3-1 if Stage 2 did not close it. Output kinds beyond §3.2 and
per-lane backend ports other than `deep_agents` are carry-forward for the next provider's sprint.

**Non-goals:** human control binding (WP-5), hooks and plugins for the parent from manifests
(WP-3), `linked_run` children, cross-provider links, the Deep Agents v2 describe (WP-8), a
general artifact download UI.

**Host facts:** Windows 11, about 15 GB RAM; one heavy job at a time; kill stale
`langgraph_cli dev` and `temporal-sdk-python … server start-dev` processes before starting
another stack. The disposable Postgres 17 container is `mc-ft-disposable-pg17` (`docker start`
it; its admin DSN is built from the container's `POSTGRES_PASSWORD`, never printed). Release
1.4.5 is a migration in the §1.3 sense and the owner executes it. Postgres-backed test modules
must be listed in `tests/conftest.py::_PSYCOPG_SELECTOR_MODULES`. The offline stack is
`scripts/offline_operator_stack.py` (`--family GoalDirected|StageGraph`). Credentials are cited
by name only. A `deepagents` version bump is run from `platform/mission-control` with `uv` and
the owner executes it.
