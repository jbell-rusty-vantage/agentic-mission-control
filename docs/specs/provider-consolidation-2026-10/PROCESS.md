---
type: Specification
title: "How a provider-consolidation session works: the known sequence, the owner's questions, and the discriminator-and-router rule for contracts that become provider-specific materialization"
description: "The process every agent session on this program follows (orient, audit, cross-reference the end goals, plan, confirm with the owner, build in deep modules, prove, document, hand off), with the owner's confirmation step made explicit and the owner's understanding treated as a deliverable; and the architectural guidance that lane-neutral contracts are discriminated and routed to per-lane adapters through dedicated discriminators and routers, never through scattered lane checks. Written 2026-10-20 after the P1 deep_agents turn 2."
tags: [mission-control, providers, consolidation, process, guidance, architecture]
---

# Process and guidance for provider-consolidation sessions

This page is for the agent that runs a session and for the owner who works with it. It fixes
two things the first P1 turns did implicitly: the **sequence** a session follows, and the
**shape** of the code it produces when a mission contract has to become provider-specific
materialization.

Two ledgers exist and the word is used for both below. The **program ledger** is
[LEDGER.md](LEDGER.md): where every proposal, document, spec, issue, interview and session stands, with its
Linear id and next step. The **change ledger** is `providers/<lane>/CHANGES.md`: what each turn built. The
convention behind the first is [program-workspace.md](../../agents/program-workspace.md).

The general method these steps instantiate (the documentation surfaces, canonical versus working
documents, the skill that runs each phase, the session loop and its close check
`python docs/tools/check_docs.py`) is the `belllabs-method` skill
(`.agents/skills/belllabs-method/SKILL.md`, added 2026-10-23). This page keeps what is specific to
this program: the capability catalog, the owner's standing rules and the discriminator-and-router
rule. Interviews on this program run through `grill-with-answers`; code shape is projected with
`architecture-projection`; provider facts through `provider-research`.

## 1. The session sequence

Every session on this program runs the same loop. The owner's confirmation step (4) is not
optional and does not come after the build.

| Step | What happens | Output |
| --- | --- | --- |
| 0. Orient | Read [LEDGER](LEDGER.md) first (what stands where, what is next), then [README](README.md), the lane's `providers/<lane>/CHANGES.md` (the ledger of what previous turns built and left open), `DESIGN.md`, and the owner's brief for this turn. Read live branch state; do not trust a previous turn's description of the tree | a one-paragraph restatement of the turn's goal, in the owner's words |
| 1. Audit | Establish what the code does today for the goal: read the modules, run the cheapest honest probe (unit tests, the offline stack, never paid runs without authorization), and cite `file:line`. Separate *tested*, *implemented-unproven*, *documented-only* | `AUDIT.md` rows or a ledger "starting state" entry |
| 2. Cross-reference | Map the audit onto the end goals: the capability catalog C01–C16, the design positions, and the owner's considerations for this turn. Name each gap as general (every lane) or provider-specific | a gap list with that label on every row |
| 3. Plan | Decide the smallest set of changes that closes the gaps as **deep modules** (§2), each with its test and its "finished part" pointer. List every point where the plan chose for the owner | a plan with an explicit **Decisions needed** list |
| 4. **Confirm with the owner** | Ask the questions the plan raised, as choices with a recommendation and what each answer changes. Restate how the system will behave afterwards in the owner's terms (a manifest snippet, a command, what they will see). Wait for the answers that change the design; proceed under a stated assumption only for the rest | recorded answers in the sprint packet (`DECISIONS` section of `DESIGN.md` or the ledger) |
| 5. Build | File the Linear issue for each item first (§1.3, `OVE`, with its `## Provenance`). Implement in the module layout of §2. General changes and provider changes are separate commits or at least separate ledger rows. Every lane adapter signs a receipt | code, tests |
| 6. Prove | Run the tiers the change can honestly reach (T0 offline first). Report passed, failed, blocked and unrun separately; name pre-existing failures as such | ledger "Checks run" entry |
| 7. Document | Append the ledger entry (general vs provider-specific, finished part, proof); update the knowledge concept and the docs index; update the program ledger rows and archive what is finished (`python docs/tools/program_ledger.py archive`); keep the list of what is *not* materialized honest | `CHANGES.md`, `docs/knowledge/*` |
| 8. Hand off | Write the next session's instruction: goal, inputs to read, the open questions, the non-goals | `NEXT-SESSION.md` in the sprint folder, or a task-named `SESSION-<TASK>.md` when the owner has not fixed the sequence (2026-10-21); its row goes in the program ledger and its Linear issue is filed |

### 1.1 The owner's understanding is a deliverable

The owner uses this system through manifests, `missionctl`, the HTTP and MCP surfaces and
these documents. So each turn ends with, in the final message and in the ledger:

- **one finished part to read**, named by module, in reading order (inputs, the module, its
  output), with the test that proves it;
- **the sequence it sits in** (the HTTP verb → service → resolver → adapter → binding →
  activity → materializer chain), so the owner can see where the new part runs;
- **how to use it**: a manifest fragment or command, and what the owner will observe.

### 1.2 How to ask

- Ask when the answer changes what gets built: a contract shape, a default, a refusal rule, a
  tier or spend. Do not ask what the code already answers; read it and cite it.
- Ask as options with a recommendation first, and say what each option costs later. Batch
  the questions of one plan into one round. Use the question tool so the answer is recorded.
- Confirm the mental model, not only the decision: "after this, a `kind: async` profile on a
  Deep Agents node spawns on the Agent Server and the parent sees its result in
  `child_result_index`" is a sentence the owner can accept or correct.
- Record every answer with its date in the sprint packet. An unanswered question is a stated
  assumption in the ledger, never a silent default.

### 1.3 Standing owner rules (recorded 2026-10-20, after turn 3)

- **Migrations are part of the work.** Mission Control is early; a session architects the
  common SQL change in `packages/mission-control-db-contract` (a new migration file and a
  component version, never an edit of an applied one), executes it on the disposable database,
  and proves through it. Deferring a needed migration to "a later decision" is not the default.
- **One session spends at most 15 USD**, with the intent to stay well under it. The owner
  names the models for paid tiers (turn 3: GPT-6 Sol as the parent, GPT-6 Luna as subagents).
  Spend is recorded per run in the ledger.
- **Deep Agents stays the focus** of P1; general kernel items that come up are handled
  carefully in the same session and recorded as general ledger rows.
- Commit and push happen when the owner says so (turn 3: everything merged to `main` and pushed
  at the session's end).

### 1.5 Standing owner rules (recorded 2026-10-27, Sprint OC start)

- **Commit when the work is complete and verified**, not when told (OC-D183). Push the integration
  branch at gate release and session end. This replaces the 2026-10-20 commit rule above.
- **Sprint OC spends at most USD 40 in total** for W0–W5 (OC-D189); the 15 USD session cap still
  applies inside it. Runtime model pins are in `sprint-oc/PROOFS.md` §6.
- **The two remote Supabase Pro projects are disposable until quality ingestion exists** (OC-D184);
  wipe schemas and reinstall inside the delivering issue, never recreate projects.
- **When the owner is away, apply `sprint-oc/ESCALATION.md` and move on** (OC-D190).

### 1.4 Standing owner rules (recorded 2026-10-23)

- **Linear is used again, forward only.** An item that will be built or fixed gets its `OVE` issue before
  work starts; nothing finished earlier is back-filled. The id goes in the program ledger row. Claim and
  handoff records, labels and `## Provenance` follow [issue-tracker.md](../../agents/issue-tracker.md).
- **Documents have a lifecycle.** A new document gets a ledger row; a finished one moves to the one
  archive, `docs/specs/archive/`, by the tool, which rewrites the links. The kinds are proposals, general
  documentation, specs, issues, interview instructions, interview answers and session instructions.
- **Interview answers have their own structure.** Each sitting writes an `answers/` file created with
  `program_ledger.py new-answers`: the owner's words, date, decision id, what it changes, where it becomes
  (ADR, spec section, glossary, Linear issue) and where it was folded. Each decision is also summarised
  as a comment on the Linear issue it decides.

### 1.5 Standing owner rules (recorded 2026-10-25)

- **Schemas conform to the evolving system.** The owner directs: "WE DO NOT FORCE functionality
  around a current schema. We make the schema conform to our system." At the start and acceptance
  of every implementation wave, and whenever output/context/lifecycle semantics change, review the
  common MC SQL, shared KS verification SQL, AI Engineer PostgreSQL domain schemas and Biotech Neo4j
  model against the required behavior. Inspect source contracts and actual disposable installations;
  use a resolved live target when a claim requires live-state evidence. Configuration alone is not
  database evidence.
- Record a compact **schema-fit row** in the active conformance/proof record: required behavior,
  store/object and authority, current representation or missing invariant, change or justified
  no-change decision, release/migration/type/projection impact, and native proof/reviewer. Review
  tenant/origin identity, exact output/effect/report bindings, review/revocation, concurrency,
  receipt/delivery and recovery wherever the change touches them. A necessary migration belongs in
  the same work; the later domain-optimization pass is not a reason to defer it.
- Keep one schema owner per object. Common MC records belong to the MC component, shared verification
  records to the KS component, AI Engineer domain records to AIDB, and Biotech graph SDL to BKS
  `schema/source/`. Physical placement remains separate from logical schema evolution.
- **Finish the working chain before a broad deep-module refactor.** The immediate end goal is the
  coordinator skill → activatable, lifecycle-controllable workflows → Deep Agents, with output
  obligations and context transfer, for both applications. Continue required scoped refactors and
  the accepted Sprint V schema/service work. Defer a general module reorganization until that chain
  works; other provider qualification follows Deep Agents.
- Accepted Sprint V decisions and authorization remain in force. Do not repeat packet approval or
  ask the owner questions that source inspection/engineering conformance can settle. Ask only for
  genuinely unresolved behavior or policy choices. Sprint V's reviewed two-application cutover leads
  to IQ-07; the later all-workflow/output/context/Deep Agents gate still controls real research use.

## 2. Discriminators and routers: how a contract becomes provider-specific

Mission Control is one system with lane-neutral contracts and nine lanes that materialize them
differently. The temptation is to add `if lane == "deep_agents"` where it is convenient. The
rule is instead:

```text
Contract (lane-neutral)
  └─ Discriminator: classifies every item of the configuration
       shared(item)                       → every lane must materialize it (native, emulated, degraded, unsupported)
       provider_specific(lane, item)      → carried in a discriminated container; only that lane reads it
  └─ Router: lane profile → the lane's adapter (one deep module per lane)
       └─ Lane adapter: contract → native form + a signed materialization receipt
            └─ Materializer (runtime): applies the sealed native form, verifies digests
```

### 2.1 What exists today, by that vocabulary

| Role | Today | Status |
| --- | --- | --- |
| Discriminator, provider-specific items | `ProviderOptions` union discriminated by `provider` (`domain/execution/bindings.py`); `environment.provider_options` keyed by lane and validated by `domain/authoring/provider_options.py`; `SubagentProfile.provider_overrides` keyed by lane; `lane_environments` keyed by lane | explicit, dedicated |
| Discriminator, shared items | the catalog kinds (`domain/capabilities/host_support.py` `AgentCapabilityKind`, `OVERLAY_KEYS`), `LANE_LAYOUTS` | explicit for file-based kinds; not yet one `mc.agent_configuration.v1` (DESIGN §1, P1-S1) |
| Discriminator, subagents (turn 3) | `application/authoring/subagent_discriminator.py` over the per-lane table `application/authoring/lanes/support.py` (each adapter declares its row, Deep Agents: `lanes/deep_agents.py::SUBAGENT_FIELDS`); profile fields in one vocabulary (`SUBAGENT_FIELDS`), typed `provider_overrides` (`subagent_overrides.py`), seeds routed to the child at launch | explicit, dedicated; file-lane rows derived until WP-S5 |
| Router | `render_host_files` switches on lane for the file lanes (`application/agentic_components/projections.py`); `ManifestLaunchResolver.node` / `provider_node` / `cursor_node` switch on lane; `V2_LANE_BEHAVIORS` and `admit_node` | implicit, spread over three modules |
| Lane adapter | `application/authoring/lanes/deep_agents.py` (turn 2) | the first dedicated one |
| Receipt | `mc.materialization_receipt.v1` (turn 2), sealed into the Deep Agents binding | general contract, one producer |

### 2.2 The rule for new work

1. **Every provider-specific field lives under a discriminated container** keyed by lane
   profile: `provider_options`, `provider_overrides`, `lane_environments`, `providers` (launch
   bindings). Validation of the container is the registry's job
   (`PROVIDER_OPTIONS_MODELS` and its peers); a key for a lane the node does not run on is a
   compile blocker.
2. **Routing happens in one place per phase.** At compile and launch, the resolver routes a
   node role to `application/authoring/lanes/<lane>.py`; at runtime, the harness registry
   routes a binding to its lane. Nothing else checks the lane. When a lane branch exists today
   outside a router (`render_host_files`, `_lane_issues`, `admit_node`), new behaviour is added
   to the lane adapter, not to the branch, and the branch is retired as the adapters cover it.
3. **One deep module per lane adapter**, pure over its inputs, with a module docstring that
   states its three translations and what it refuses. It reads shared items and its own
   discriminated container; it never reads another lane's.
4. **Every adapter signs a receipt** (`mc.materialization_receipt.v1`). `unsupported` is a
   refusal when the mission required the item (`requires`, an explicit `kind`, a named tool),
   and a `degraded` row with a reason otherwise. Silent drops are defects.
5. **Shared items get one neutral contract** (`mc.agent_configuration.v1`, P1-S1) emitted by
   the compiler; adapters consume it. Until it exists, adapters consume the resolved
   `MissionDefinition` capabilities, as the Deep Agents adapter does.
6. **When generality is too clunky, say so in the contract.** If a shared field cannot be
   expressed neutrally (Cursor subagents are files with their own frontmatter; Deep Agents
   children are in-process objects with slices), the neutral contract keeps the common core
   and the lane-specific remainder goes under the discriminated container, documented for the
   coordinator agent. The owner decides which fields are core; the question is asked, not
   assumed.

### 2.3 The subagent case (the next turn's decision)

Subagents are the hardest shared item because every lane has a different native form: an
in-process `SubAgent` dict (Deep Agents), an Agent Server graph (Deep Agents async), a markdown
file with frontmatter (Cursor, Claude), a TOML file (Codex), a flag (hosted APIs). The neutral
`mc.subagent_profile.v1` carries the common core; `kind`, `placement`, `sandbox`, `budget` and
`provider_overrides` were added in turn 2; `capabilities: inherit | seeded` and `seeds` in
turn 3, with the decisions recorded in
[docs/specs/archive/provider-consolidation-2026-10/specs/SUBAGENTS.md](../archive/provider-consolidation-2026-10/specs/SUBAGENTS.md) §4 (Q1, Q2, Q7).

## 3. Per-turn checklist

- [ ] Goal restated in the owner's words; inputs read, including the ledger.
- [ ] Audit cites `file:line`; probe run where it costs nothing.
- [ ] Gaps labelled general or provider-specific.
- [ ] Decisions listed and **asked**; answers recorded with dates.
- [ ] Code lands as deep modules behind the router; receipts signed; no new lane branches
      outside routers.
- [ ] Checks reported as passed / failed / blocked / unrun; pre-existing failures named.
- [ ] Change-ledger entry, knowledge concept, docs index, `NEXT-SESSION.md`.
- [ ] Program ledger rows updated, finished documents archived, Linear issue filed per item built (id in the row); `python docs/tools/program_ledger.py check` passes.
- [ ] Final message: one finished part, the sequence it sits in, how to use it.
