---
type: Decision Record
title: "Signal Ingress: trust tiers, one SQL call per request, and signals are evidence, never authority"
description: "Accepted for the materialization-observation sprint (SPEC-04 section 3, SPEC-10, R11, R29; MO-40): a thin public ingress verifies callers at one of five trust tiers and records what they sent through SECURITY DEFINER functions of a NOLOGIN role with no table grants; the gate answer is computed in SQL with the Operation Intent written before allow; accepted messages land in an append-only inbox that only the worker drains into frames, reconciliations and admissions."
tags: [mission-control, adr, accepted, ingress, observation, security]
status: accepted
source: docs/specs/archive/materialization-observation-2026-10/SPEC-10-ingress-on-vercel.md (sections 1-4); docs/specs/archive/materialization-observation-2026-10/SPEC-04-watchers-and-callbacks.md (sections 3 and 4.3); docs/specs/archive/materialization-observation-2026-10/research/vercel-ingress.md (sections 2.1-2.5); docs/specs/archive/materialization-observation-2026-10/research/cursor.md (section 2.6); DECISIONS R11, R17, R29 and Proposed ADRs 0045; MO-40; ADR-0043; ADR-0008; ADR-0004
---

# Signal Ingress: trust tiers; signals are evidence, never authority

**Status: accepted 2026-11-01; implemented by the materialization-observation Run 2 finish (`b95ae4aa` completion summary; `152a3dcb` finish records, 2026-10-20) and the 1.4 database release (`b434e573`).** Previously proposed. 

Cloud lanes were blind beyond their provider APIs: nothing could reach Mission Control from a
provider VM, a hook or a provider webhook, and the only callback (the Kernel Hook loopback) is
bound to the worker's `127.0.0.1`. Remote launch had no route that keeps Temporal credentials off
the public edge (R29).

We add **Signal Ingress**: `application/signals/` (service, contracts, verification, ports),
`adapters/postgres/ingress.py`, `adapters/auth/provider_oidc.py`, the router
`interfaces/http/ingress.py` and common-component migration `0035_signal_ingress.sql`.

- **The edge verifies; SQL decides; the worker acts.** Each request is verified in the process,
  size-capped and parsed into a strict contract (`mc.signal.v1`, `mc.signal_gate.v1`,
  `mc.mission_request.v1`), redacted, then becomes exactly one call to a SECURITY DEFINER
  function. The function decides whether the credential is live, which run it binds, duplicates,
  the per-credential rate window and the gate answer. The edge holds no Temporal credentials,
  signals no workflow and writes no provider frame (frames have a single writer per execution).
- **Least privilege.** The edge's login is a member of the NOLOGIN role
  `mission_control_ingress`, which has no table grant: only EXECUTE on `ingress_accept`,
  `ingress_gate`, `ingress_webhook`, `ingress_artifact_prepare`, `ingress_artifact_commit`,
  `ingress_mission_request` and `ingress_mission_request_status`. Every ingress table keeps
  FORCE ROW LEVEL SECURITY; the functions bind the transaction scope from the credential they
  resolve, at entry and again once the credential names its tenant (a definer-only policy lets
  the schema owner resolve a credential before its tenant is known).
- **Trust tiers**, recorded on every inbox row:

  | Tier | Credential | May drive |
  | --- | --- | --- |
  | `run_token` | Minted `mint:signal_token` (ADR-0043) looked up by digest; bound to run, unit and generation | Signals, synchronous gates, artifact uploads |
  | `provider_oidc` | Cursor VM JWT (RS256, issuer `https://api.cursor.com`, our audience, at most 300 s), its `cloud_agent_id` bound to a run generation by the worker at launch | Same as `run_token` |
  | `environment_key` | `HMAC(derive(master, "<app>/<provider>/<environment>"), timestamp.body)`; the provider session is bound by the first `session.started` that presents the run nonce's preimage | Observation only: never gates, effects or artifacts |
  | `provider_signed` | Standard Webhooks (Anthropic, OpenAI), GitHub `X-Hub-Signature-256`, Cursor v0 with a per-run derived secret | Wake-ups only; the payload is never trusted |
  | `launch_token` | Minted `mint:mission_request`, bound to a tenant scope and optionally a manifest set | One remote launch request, admitted on the worker |

- **Signals are evidence, never authority.** A signal reaches a reducer only as a provider frame
  through the lane's existing closing-frame rules; a webhook only wakes a lane, which re-reads
  the provider. Payloads are stored redacted as untrusted data.
- **The gate is computed in SQL**, in one transaction: a revoked credential answers `stop` (and
  records it only within the credential's rate window, so a revoked token cannot write past its
  limit); under the same per-run advisory lock and admission ledger as the loopback Kernel Hook
  (`stop_fence_effect_admission`) a Stop Fence covering the generation answers `stop`; a tool the
  binding disallows answers `deny`; otherwise the Operation Intent (`hook_effect_intent`, keyed
  on the effect ref) is written **before** `allow`. A replayed gate call, including a concurrent
  retry, answers the recorded decision only when its body matches the recorded one; a reused
  `signal_id` with another body is refused as `dedupe_conflict` (409), so a client-chosen id
  never carries one effect's answer past a fence, a disallowed tool or revocation. Each inbox
  kind dedupes in its own space (`dedupe_space`: all signals share one, every other kind is its
  own), so a signal and a gate decision may share an id. Revocation is one UPDATE, so it takes
  effect at the edge on the next call.
- **The environment-key signature covers the timestamp and body, not the session header.**
  Whoever holds one environment's derived key can therefore post observations for any
  session already bound in that environment. We accept this because the tier is observation
  only (no gate, effect, upload or launch), its signals are evidence and never authority,
  and the key is scoped to one application, provider and environment.
- **The inbox is the only hand-off.** `ingress_inbox` is append-only; an AFTER INSERT trigger
  notifies `mc_ingress` with the scope and row id. The worker claims pending rows with
  `FOR UPDATE SKIP LOCKED` and settles each one once (`drained` with an optional `outcome`,
  `rejected` with a typed `outcome.reason`, or `dead`); a retried failure only increments
  `attempts`. A provider webhook row has no tenant until the drainer resolves its session.
- **Derived secrets.** Environment keys and Cursor webhook secrets are
  `HMAC-SHA256(master, "<purpose>:<identifier>")`, so the edge holds one master per purpose.
- **The loopback listener serves the same handlers.** `create_hook_callback_app` mounts the
  ingress routes beside the Kernel Hook callback when the worker composes ingress services.

We rejected letting the edge write frames (breaks the single-writer arrival ordinal), signalling
Temporal from the edge (Temporal credentials at a public edge, bypassing the outbox), a third
durable store such as Vercel Queues (gates need the database anyway), table grants for the edge
role (a compromised edge could read or rewrite history), and trusting webhook payloads (they are
unordered, duplicated and unauthenticated beyond the signature).

## Consequences

- Migration 0035 adds `mission_control_ingress` to the release's runtime roles; release 1.4.0
  (built by the integrator) carries it. Each installation adds one login, `mc_ingress_<app>`,
  a member of that role, connecting through the transaction-mode pooler with the statement
  cache off.
- The Secret Broker gains the `mission_request` purpose (`LaunchBinding`, 7 days, 30 requests
  per minute), a per-purpose rate limit and a secret-free credential `context` (a gate reads
  `harness_execution_id`, `lane_profile` and `disallowed_tools`; a launch credential reads
  `manifest_refs`). Its PostgreSQL store is `PostgresMintedCredentialStore` over
  `ingress_credential`.
- Not in this decision's implementation: the Vercel project and import closure (MO-74), the
  IngressDrainer (MO-75), artifact custody and the quarantine signer (MO-76), the launch
  admission and `missionctl remote launch` (MO-79), the Telemetry Hook Pack (MO-41), and
  composing the services into the worker and minting gate-capable tokens from lanes. A gate
  call with a credential that lacks its context, or names a lane profile that is not
  registered, answers `deny` (`gate_context_missing`).
- Webhook registration with providers and the live 1.4.0 apply are owner steps (SPEC-10
  section 9); nothing here registers or deploys anything.
