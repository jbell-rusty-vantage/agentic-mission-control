---
type: Specification
title: "Run 2 OpenAI product resolution: hosted Agents API, SDK and direct model transport"
description: "Source-backed resolution of the existing OpenAI lane, runtime dependency versus wire pin, implemented/planned/qualified boundaries and official documentation checked 2026-10-14."
tags: [mission-control, providers, openai, evidence]
---

# OpenAI architecture resolution for Run 2

**Mission Control implements the OpenAI hosted Agents API using its own HTTP client. It does not run the OpenAI Agents SDK.** The conclusion follows imports, endpoints and production wiring, not the codex_agents name. Inspection: 2026-10-14, repository base a2527f6f3c385a7f55272c41d90e6860b44781d0. This is planning evidence, not a new provider qualification.

## Source trace

| Evidence | Exact source and implication |
| --- | --- |
| Concrete HTTP client | src/mission_control/adapters/openai_agents/client.py:35-36 sets https://api.openai.com/v1 and OpenAI-Beta: agents=v1. Lines 102-128 construct httpx.AsyncClient with API-key auth and create /agents/sessions. Session retrieve, input, items, turns and SSE are product-specific resource calls. |
| Production composition | adapters/temporal/hosted_lane_composition.py:29-33 imports the local client/harness; line 407 constructs AgentsApiClient, line 486 constructs CodexAgentsHarness, line 494 registers deletion. deployment_composition.py:551-552,652,1214 includes the enabled lane in worker composition. It is an optional configured path, not universally enabled readiness. |
| Exact authoring/binding | application/authoring/provider_launch.py:77-80 requires hosted wire evidence sdk.openai: 3.29.0 and beta.agents: agents=v1. domain/execution/bindings.py defines CodexAgentsOptions with openai_hosted/funding-gated self_hosted. No Agents SDK runner is admitted by that contract. |
| Installed dependency | pyproject.toml declares standard openai>=2.36,<3; uv.lock locks openai 2.44.0. No openai-agents package or application agents runner imports were found in the inspected tree. This is absence in this repository, not a claim about provider availability. |
| Historical SDK pin | scripts/provider_smoke/openai_agents_api.py uses isolated standard OpenAI SDK 3.29.0 beta.agents for smoke/schema evidence. Production lane calls are custom HTTP. The sdk.openai binding key is retained compatibility provenance, **not proof that production installs 3.29.0**. Record runtime dependency and wire/schema evidence separately; do not rename sealed keys silently. |
| Offline coverage | tests/unit/openai_agents/, tests/conformance/lanes/, tests/fixtures/agents_lane.py and tests/unit/authoring/test_hosted_launch_bindings.py exercise resources, harness, recovery, effects and authoring. Run 1 records executed selections; no tests were rerun for this document. |
| Roadmap | SPEC-06 §5, HL-11/12/13/21 and HL-25 cover the hosted API. HL-14 self-hosted executor is S4 funding-gated. MANAGED-AGENTS-REMOTE-PATH marks Agents SDK “Not a lane (C2)”. SC-01/SC-03 subscription Codex cloud is deferred. No SDK lane implementation issue is in this packet. |
| Qualification | RUN-1-REPORT §Budgets and provider evidence: five bounded S3 attempts did not prove accepted approval/recovery; usage/cost remained unknown. Corrected source passed offline checks but was not rerun with inference. HL-25 remote qualification and full owner-selected projection evidence remain outstanding. |

All source paths above are relative to src/mission_control unless they start scripts/, tests/, docs/ or name a root file.

## Product distinctions in active planning

| Surface | Current Mission Control status |
| --- | --- |
| OpenAI hosted Agents API (codex_agents) | Implemented optional HTTP lane, offline covered; full S3 acceptance/remote qualification blocked or unrun. Requires exact account/configuration readiness. |
| OpenAI Agents SDK | Application-run SDK loop; no dependency, runner, registered lane or in-sprint implementation plan found. Documentation support is not local implementation. |
| Direct Responses execution adapter | No standalone lane configured by this packet. Model helpers/ChatOpenAI inside Deep Agents may use model APIs; they are transport within another runtime, not this execution surface. |
| Codex local (codex) | Separate app-server JSON-RPC harness. S0, auth-home refusal, version/schema repin and exact WSL qualification are SPEC-09 work. |
| Codex subscription cloud (codex_cloud) | Separate product/profile with deferred SC experimental qualification. It cannot inherit hosted API qualification. |
| Hosted Agents API self-hosted executor | Planned S4 HL-14, currently funding-gated and refused by admitted binding placement rules. |

The owner's “OpenAI agents we currently or plan to support” therefore maps first to the **existing hosted Agents API**. No additional SDK or Responses implementation is inferred. Keep codex_agents as the wire ID and label it “OpenAI hosted Agents API” in guidance. Direct OpenAI API and direct Anthropic Messages execution surfaces remain future designs, along with typed Anthropic model transport for Deep Agents.

## Official verification and limits

Checked 2026-10-14: the [OpenAI agents runtime comparison](https://developers.openai.com/api/docs/guides/agents) distinguishes provider-managed Agents API, application-run Agents SDK and Responses API; the [Agents API overview](https://developers.openai.com/api/docs/guides/agents-api/overview) describes the managed Codex-harness session product. These corroborate taxonomy, not account entitlement, adapter correctness or acceptance.

Current source corrects a historical smoke note: vaults are /v1/vaults, not /v1/agents/vaults. Preserve the original smoke record and cite client.py for current behavior; do not silently alter receipts. A newer documentation/schema delta needs a separately pinned adapter change and qualification, never a running-binding upgrade.

## Managed Agents pause: separate blocker

Anthropic harness.py:631 implements hold_budget(harness_execution_id, held: bool), with True holding and False releasing the budget gate; only tests were found calling it. Static describe explicitly notes missing workflow wiring and declares pause unsupported. Domain lane control also marks Managed/OpenAI provider pause unsupported; operation workflow pause holds the next turn boundary. HL-24's budget-gate pause/resume requirement therefore remains blocked. Boundary proof is useful but cannot satisfy that requirement without an explicit owner amendment. A describe-only change is insufficient. See [approved amendments](RUN-2-PLANNING-AMENDMENTS.md).
