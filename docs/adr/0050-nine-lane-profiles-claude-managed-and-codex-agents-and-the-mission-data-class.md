---
type: Decision Record
title: "Nine Lane Profiles: claude_managed and codex_agents join the claude and codex lanes as describe-only stubs, and missions carry a Data Class the non-ZDR lanes admit"
description: "Accepted for the materialization-observation sprint (SPEC-06 sections 1, 8 and 9; HL-06), amending ADR-0035: the API-billed hosted agent APIs Anthropic Managed Agents (claude_managed) and the OpenAI Agents API with the Codex harness (codex_agents) become Lane Profiles on the existing claude and codex lanes, placed cloud because the provider runs the agent loop, with the tool placement (cloud or openai_hosted, funding-gated self_hosted) in their typed binding options; both ship as unqualified v2 stubs that claim nothing; their only auth route is an API key with explicit api billing consent; mission/v2 gains a Data Class that claude_managed and codex_agents admit only at public or internal by default (an Application may widen to confidential, never phi or secret); migration 0036 is the common SQL slot."
tags: [mission-control, adr, accepted, execution, lanes, authoring, providers]
status: accepted
source: docs/specs/archive/materialization-observation-2026-10/SPEC-06-hosted-api-lanes.md (sections 1, 8 and 9); docs/specs/archive/materialization-observation-2026-10/DECISIONS.md (R3, R4, R10, R27, R30, R31, C3, O3; Proposed ADRs 0050); docs/specs/archive/materialization-observation-2026-10/research/codebase-new-lanes.md (section 2); docs/specs/archive/materialization-observation-2026-10/research/provider-smoke-2026-10.md; HL-06; ADR-0035; ADR-0052
---

# Nine Lane Profiles: claude_managed and codex_agents, and the mission Data Class

**Status: accepted 2026-11-01; implemented by the materialization-observation Run 2 finish (`b95ae4aa` completion summary; `152a3dcb` finish records, 2026-10-20) and the 1.4 database release (`b434e573`).** Previously proposed.  Until then ADR-0035 remains
the accepted vocabulary text; nothing here claims either new profile is implemented, qualified
or account-enabled.

## Context

ADR-0035 fixed seven Lane Profiles and named `claude_cloud`/`codex_cloud` as the provider-hosted
products. The owner approved API billing for two hosted agent APIs (DECISIONS R3, R4, R10):
Anthropic **Managed Agents**, where Anthropic runs the loop and the tools run in its cloud
sandbox or on our worker, and the OpenAI **Agents API**, which runs the closed Codex harness in
OpenAI's sandbox or on our executor. Neither is the subscription product `claude_cloud` or
`codex_cloud`, and neither is ZDR-eligible: transcripts persist until deleted and tool inputs and
outputs pass through the provider (DECISIONS C3). The HL-23 smoke confirmed their request shapes,
mid-turn delivery and usage on 2026-10-12.

## Decision

1. **Two profiles on the existing lanes.** `claude_managed` joins the `claude` lane and
   `codex_agents` the `codex` lane, so `LaneName`, `RUNTIME_OF_LANE`, the runtime-to-binding
   pairing and the `lane_profile.lane` CHECK stay as they are. `host_support.LaneProfile` and
   `lanes.LANE_PROFILES` gain both names, and every vocabulary the import guards and the lane
   contract tests enumerate follows (hook mapping, frame kind and dedupe tables, auth surfaces,
   route evidence, search attributes, the manifest `lane` enum, command semantics). The set of
   nine is `deep_agents | cursor_local | cursor_cloud | claude_agent_sdk | codex | claude_cloud |
   codex_cloud | claude_managed | codex_agents`.

2. **Placement `cloud`; tool placement in the binding.** "Cloud" now means the provider runs the
   agent loop, which covers the hosted products and the hosted agent APIs; our own remote SDK
   worker stays `worker_hosted`. Where tools execute is the binding's `tool_placement`:
   `ClaudeManagedOptions` takes `cloud` or `self_hosted`, `CodexAgentsOptions` `openai_hosted` or
   `self_hosted`. `self_hosted` (our Sandbox Host) is funding-gated (R31) and has no declared
   matrix, so a binding that selects it is refused until it does. The options are typed: Managed
   Agents always sets `max_list_cost_minor_units` (the session budget, the only pause mechanism),
   and `multiagent`/`multi_agent` default off (R33, SPEC-06 section 5.3).

3. **Knowledge work needs no repository.** A hosted agent API binding may omit the repository;
   when it binds one, it pins both URL and commit. `mission/v2` drops the `workspace.repo`
   requirement for these two lanes only.

4. **Describe-only stubs that claim nothing.** Both declared matrices are `mc.lane_describe.v2`
   with every control `unqualified` and every feature `unqualified`; delivery semantics,
   identities, usage and approval modes record SPEC-06 section 9 and the HL-23 observations as
   design intent. `pause` stays `unsupported` (boundary-only) until HL-08 implements the budget
   gate and HL-12 the function-tool gate; no hook file runs on either API, so the hook mechanism
   is `none`. The lane conformance suite registers both as `DescribeOnlyConformance` until
   HL-08 and HL-12 add their fakes; `qualified` flips only with the HL-24 and HL-25 drills.

5. **Published where their key is bound.** The API's describe-only registry lists
   `claude_managed` when an Anthropic API key is bound and `codex_agents` when an OpenAI API key
   is; a lane credential such as `mission_control_claude_lane` does not publish them.

6. **API key only, with consent.** Each profile has one auth route, `api_key`, billing `api`
   and documented; sign-in routes are `unsupported`. A profile that does not consent to `api`
   billing is refused with `AUTH_BILLING_NOT_CONSENTED`; there is no subscription fallback.

7. **The mission Data Class.** A `mission/v2` mission declares `data_class: public | internal |
   confidential | phi | secret`. `domain/execution/data_class.py` holds the policy:
   `claude_managed` and `codex_agents` admit `public` and `internal` by default, an Application
   may widen a profile up to `confidential`, never to `phi` or `secret`, and a mission that
   declares no class is refused there. Compile admission refuses every node role whose lane does
   not admit the class (`DATA_CLASS_NOT_ADMITTED`, `DATA_CLASS_UNDECLARED`), pointed at the lane
   that chose it. Profiles without a policy row admit every class.

8. **Migration 0036 is the common slot.** It seeds the two `lane_profile` rows from the declared
   matrices (`qualified = false`), admits their `mc.execution_binding.v2` documents, and widens
   the lane-profile CHECKs on `harness_execution`, `provider_frame`, `continuation_transfer` and
   `search_document` and the capability host-support validator. The Data Class needs no column:
   it travels in the persisted manifest bytes under the manifest digest.

We rejected new lanes (`anthropic`, `openai`): they would touch about eight more vocabularies and
the `lane` CHECK for no behavioural gain (research/codebase-new-lanes.md section 2). We rejected a
profile per tool placement: the agent loop, API, identities and controls are the same; only
where tools run differs, which is binding data. We rejected letting the API-billed profiles ride
on the subscription lane credentials, which would advertise a lane whose billing route is absent.

## Consequences

- Neither profile is dispatchable: their launch is refused at compile (a `hosted_launch_refused`
  warning) and at launch (no launch author), and admission refuses them while unqualified.
- The Host Projection writes no files for them and reports every capability row as skipped;
  HL-07 and HL-11 prepare from pack files (R30) and HL-21 projects rows through the provider API.
- HL-18 builds on the Data Class policy: the Application Binding widening and session retention.
  Chain links that move outputs between missions of different classes are not judged here.
- The SQL change is additive; every widened CHECK still admits every row it admitted before.
