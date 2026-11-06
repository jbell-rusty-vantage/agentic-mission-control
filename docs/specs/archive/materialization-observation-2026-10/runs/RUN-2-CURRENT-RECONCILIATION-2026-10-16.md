---
type: Reconciliation Evidence Record
title: "Run 2 retained identity and recovery implementation evidence"
description: "Exact protected pins, fresh read limits and replay proof."
---

# Protected identity and recovery evidence

The [current boundary](RUN-2-OPERATIONS-BOUNDARIES-2026-10-16.md) controls action.
These are retained observations, not a fresh production eligibility statement.

| Field | Pinned observation |
| --- | --- |
| Public / internal | `60f44a50-c0e4-5edb-ac13-0fb0436aaedb` / `01a14386-3bb2-7dd0-ba2b-f33d0eaa2053` |
| Scope | `mc/01a103c0-9a9e-70f3-9398-eb1573a98324/ai-engineer/00000000-0000-7000-8000-000000000001` |
| Last installed read |15:53: cancelling v5/gen1; harness`4eb7354d-980a-52f1-93b3-83b6b8863a2b` rev140; owner epoch1 expired08:18:10.959536 |
| Binding / claim | `7669041e-bf40-58a2-9878-82a85b975b92` / `c0d3b676-9738-59c7-9b47-01566d1a9420`; slot1/attempt1, no currency |
| Binding digest | `sha256:fe8d72dbc4983c780dc31a4c0b432fa69528a21b0c2c24954a754400468e30be` |
| Family head | `sha256:fe2905b2abaace9136235108132ede15f887259a00d9c86013e9005764815785` |
| Native agent / turn | `agent-73162e55-750b-4f76-8762-ebee7c6dcead` / `run-2df4a451-c80c-4814-843c-3cc542048c2f` |
| Native terminal | FINISHED08:20:51.998; input456013/output14072/cache-read417705/cache-write38280/explicit total926070; selector default is not an observed serving model |
| Frame/dispatch frontier |249 frames ord1..249; create/send acknowledged once; effect unsettled; no accepted usage/output/settlement |
| Cancel | SQL UUID`01a143d0-e8cb-7d31-ac91-f9b772e6554e` differs from domain ID`6a5398e3-2a73-4351-a354-a24a9a4ddc4b`; ordinal2 delivered; issuer`mc.command.v1,service:run2-s0-launcher,cancel` |
| Protected once-fence SHA256 | `c30215e853a393b9e0f48a3b2e7ac1e97a98cb6b415766cdb9b28430b98dab37` |

## R1 custody, unchanged

Capture16:15:31: result2946 UTF-8 bytes SHA256
`2e4aac0d29aae546e783667baef26ec7850b3f34586d62908f1f66171e194a7c`;
private manifestSHA256`261f5982fefd5beb2ae64ce0098bf142c36e879835d6d402e8e71ab23a43ad52`.
Linux directory is `/home/overton/.local/state/mission-control/evidence/run2/`
followed by public key/result digest;0400 result/manifest,0700 directories,
fsynced. No raw result printed/copied to Windows. Private read-only files are
not owner-resistant WORM. Actual source DB/WAL/SHM pins respectively:

- `4de3897f2925110a9f36a7c5d82d1d6120c8db87771d94af76b3eec7c57ba849`
- `ee74417ab9aa383ee0cf43d2dd2f569f45c7b172df694620faba2a9847a33bab`
- `e6da94fba38b6b98ce615060c3bb108d2cc349a9fe5e661b9f7b2b696fe9eeb7`

The new R1 bridge checks this legacy manifest plus separately pinned native
counter/timestamp/source evidence, deriving the newer schema in memory only.
Legacy R1 did not contain every counter; never infer missing counters from its
total or overwrite its manifest. Actual private payload-reader integration remains
to be demonstrated under exact server-approved addresses.

## R2 implementation proof

`TerminalEvidenceAdoptionService` has no NativeHarness dependency. It claims a
later owner epoch only after expired-owner and invariant-frontier checks, writes
deterministic digest-bound terminal frames atomically, reuses the existing claim,
stages exact text custody, and calls normal settlement/family decision services.
No declared files are invented. During cancellation, normal family handling
quarantines the result and closes producer liability rather than accepting output.
Normal terminalization validates/applies a matching pending cancel; it does not
invent a provider acknowledgement or stale-target rejection.

Tests exercise capture/authority drift before writes, different claimant adoption,
stale owner/gen, duplicate/conflicting frames, pinned CAS after concurrent cancel,
crash after frames, after effect observation, after usage authority and before
family completion; replay once, known-currency discharge and unknown positive
currency pending. Closed recovery permits unknown cost only with complete
attributable terminal usage and no pending admitted currency. Real PG tests prove
restricted-role fencing/final usage snapshot and delivered-cancel terminal commit.
Exact context-reader joins currently use fake DB unit fixtures; Temporal input
tests use typed real validators with fake closed history, not production replay.

## Installed data and next read

Read-only installed contract1.4.2 verification passed37 exact receipts, all six
capability roles, reader/writer1 and full-owned-schema attestation SHA256
`1d6dcd1a96b44b7c3635ffd34cec7703703160b04bf52c24643157c72a472cc3`.
No schema migration/backfill is introduced or indicated. Do not reapply migrations.
Current seed/config/provider pins, reference checkpointer, Biotech SDL and actual
payload backend remain separate readiness facts.

Next production read must pin current versions/owner/dispatch/family/command and
exact closed Temporal execution IDs in scoped read-only repeatable-read transactions
with finite row/time bounds. Prior normal API health timed out; no service was
restarted. No new installed read or shared-data adoption occurred in this tranche.
A concrete live request still needs exact restricted principal permission,
trustworthy private custody reader and separately authorized shared-data scope.
