---
type: Research
title: Daytona sandbox tiers, egress control and lifecycle
description: What Daytona's account tiers decide for Mission Control - per-sandbox egress allowlists only from Tier 3, cold container snapshots, lifecycle timers, limits and price - plus what the code already encodes. The note the network projector cites as research/daytona.md section 4.
tags: [mission-control, research, daytona, sandbox, egress, tiers, network]
subject: Daytona managed sandboxes as a Sandbox Host and as a Deep Agents sandbox backend
versions: [daytona SDK 0.224.0 (2026-10-12), langchain-daytona 0.0.8, daytonaio/daytona repo archived at v0.190.0]
sources:
  - docs/specs/archive/materialization-observation-2026-10/research/daytona.md (the full 393-line fact sheet read 2026-10-12; section numbers below refer to it)
  - docs/DEPLOYMENT_OPTIONS_2026-10-12.md (account tier statement)
  - src/mission_control/application/environments/network.py:31,440-483
observed: 2026-10-12 (vendor docs and SDK), 2026-11-01 (code)
confidence: medium; vendor facts are as read on 2026-10-12 and change daily (the SDK shipped almost daily); the account tier is unverified
used_by: [deep-agents-lane, environments, workspace-closure]
date: 2026-11-01
---

# Daytona sandbox tiers

`network.py:31` cites "research/daytona.md section 4" for Sandbox Host egress control. That fact sheet exists, archived
at the path in `sources`; its section 4 is "Networking". This note is the maintained extract. It does not replace the
sheet's SDK method tables or the SandboxHost adapter design (sections 2, 3, 9), which are archived with the
materialization-observation program.

## What decides egress: the account tier

| Tier | How reached | Egress control |
| --- | --- | --- |
| 1 | Email verification | Organisation policy only. Per-sandbox lists are ignored; `update_network_settings` errors. Reachable: the fixed "essential services" list (package registries, GitHub/GitLab, `*.anthropic.com`, `*.openai.com`, `*.chatgpt.com`, `*.vercel.app`, `*.workers.dev`, `*.supabase.co`, Docker registries and others) |
| 2 | Card plus 25 USD top-up | Same as Tier 1 |
| 3 | 500 USD top-up | Full internet by default; per-sandbox `domain_allow_list` (up to 100 domains, `*.` wildcards), `network_allow_list` (up to 10 IPv4 CIDRs) or `network_block_all`, strictly enforced; essential services are **not** auto-added; mutable at runtime |
| 4 | 2000 USD every 30 days | As Tier 3 |

The three per-sandbox settings are mutually exclusive (a mixed request is a 400). `outbound_proxy_url` sets
`HTTP(S)_PROXY` only and is not a security boundary [sheet section 1.1, section 4].

**Unverified: which tier the owner's account has.** `DEPLOYMENT_OPTIONS_2026-10-12.md` records "Tier 1/2, 200 USD free
credit". A probe on 2026-10-12 returned `X-RateLimit-Limit-authenticated: 50000`, which matches the documented Tier 4
general rate, so the sheet marks the tier unverified and says to read `app.daytona.io/dashboard/limits` before relying
on allowlists.

## How the code uses this

`project_sandbox_egress(profile, policy, egress_control=, essential_services=)` (`network.py:437`) takes one of three
control kinds, named exactly as the research does:

- `domain_allowlist` (Tier 3+): the policy is enforced per sandbox (`egress: allow_all | block_all | allowlist`).
- `org_essential_services_only` (Tier 1/2): a policy whose hosts the essential list covers runs, **advisory**
  (`egress: organisation`); any other host raises `NetworkProjectionRefused(SANDBOX_EGRESS_UNAVAILABLE)` rather than
  run unreachable.
- `none`: nothing narrower than `allow_all` holds.

Status: **implemented and unit-tested** (`tests/unit/agentic_components/test_network_policy.py:386`), **not called in
production**: no `SandboxHost` port, Daytona adapter or lane exists in `src/` (the archived issues HL-01/HL-02 specify
them). For Deep Agents the projector in use is `_deep_agents` (`network.py:389`), which seals exact worker-tool hosts
into the operation grant and explicitly leaves executable sandbox networking unchanged. Deep Agents' `daytona` backend
literal is admitted by the contract but has no factory ([sandbox providers](../deep-agents/sandbox-providers.md)).

## Lifecycle and limits worth knowing (vendor, 2026-10-12)

- Containers snapshot **cold only**: filesystem, sandbox must be stopped; restore creates a new sandbox; `fork` and
  pause are VM-sandbox-only. Snapshots go inactive after 2 weeks unused and bill storage after sandbox deletion
  [section 5].
- Auto-stop default 15 min; outbound sockets and background processes do not reset it, so long self-hosted executors set
  `auto_stop_interval=0` and `ttl_minutes` as the backstop [sections 1.1, 4].
- Per-sandbox maximum 4 vCPU / 8 GiB / 10 GiB; default 1 / 1 / 3 [section 1.1]. Tier pools: Tier 1 10 vCPU, Tier 2
  100, Tier 3 250, Tier 4 500 (the sheet notes an inconsistency in the Tier 1 memory figure) [section 6].
- Price: 0.0504 USD per vCPU-hour, 0.0162 per GiB-hour RAM, per second; a 2 vCPU / 4 GiB / 10 GiB sandbox is about
  0.166 USD/h running [section 6].
- Sessions give streaming stdin as text lines only, with no close-stdin [section 2]. Preview URLs carry WebSockets;
  the standard token is sandbox-wide and unrevokable, so only signed URLs are acceptable [section 4].
- Secret substitution does not apply to upgraded WebSocket connections [section 4].
- The open-source repository is frozen (archived June 2026); self-hosting is not a fallback [section 0].
- Compliance: SOC 2, ISO 27001, GDPR, HIPAA are listed; whether a BAA exists is unverified, so the design caps the
  sandbox data class at `internal` [sections 6, 9.3].

## Citations

- Archived sheet: [daytona.md](../../specs/archive/materialization-observation-2026-10/research/daytona.md); deployment report [DEPLOYMENT_OPTIONS_2026-10-12](../../DEPLOYMENT_OPTIONS_2026-10-12.md).
- Code: `src/mission_control/application/environments/network.py` (lines 31, 437-483), `src/mission_control/domain/execution/contracts.py:686`.
- Related: [Deep Agents sandbox providers](../deep-agents/sandbox-providers.md).
