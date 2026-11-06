---
type: Concept
title: Pinned Claude nonquery bootstrap boundary
description: Exact SDK and CLI source contracts, strict startup validation and offline native proof outcomes; no provider or live worker qualification.
---

# Pinned Claude nonquery bootstrap boundary

This note separates static source evidence, fixture tests and the actual offline native
bootstrap proof below. None establishes provider or live worker qualification.
The local session previously waited for `system/init` immediately
after `ClaudeSDKClient.connect(None)`. SDK 0.2.165 initializes control transport without
sending user input. Its local headless CLI 2.1.294 emits native init while processing its
first input, so waiting before submitting any input can time out.

The inspected bundled CLI SHA-256 is
`27122ca7b624f537546fbef35b80c66370d974ff258f3d9b10ac50bb8771f262`.
Offsets below refer only to these exact bytes, including embedded JavaScript modules:

| Offset | Source contract |
| --- | --- |
| 238989600–238993500 | Streaming user input forwards `shouldQuery`; `isSynthetic` becomes `isMeta`; `client_composed` disables slash expansion. |
| 238434456 | `cy` derives `skipAttachments` from `client_composed`. Arbitrary raw skip flags are not assumed to pass through. |
| 221092567 | `Ict` excludes synthetic nonquery input from prompt-source selection, forces `shouldQuery=false`, and returns before submission hooks; `Js` skips workflow autoload for nonquery input. |
| 238682000–238690600 | The headless path emits genuine init, then nonquery success with zero turns and API duration, without entering the model engine. It can replay the metadata user input. |
| 210613402 | `Bp` zero usage includes nested thinking/cache/server-tool counters, categorical `service_tier="standard"`, `speed="standard"`, `inference_geo=""`, empty iterations and null fallback credit. The adapter requires the complete exact shape, types and values; unknown/missing keys are refused. |
| 238434112; 227803878; 238992000 onward | `ly` maps synthetic input without inbound/client provenance to exactly `{kind:"unclassified"}`; `eC`/`RJe` supplies no alternate origin for this envelope. The headless input forwards this origin and the zero-result branch copies it. Result and optional echo require exactly that origin, never arbitrary sender fields or human provenance. |

SDK `client.py` SHA-256
`980f956d963338b39f4fd5224e69594eb513bfda37e5b215cf94bb0499ea047c`
and `_internal/query.py` SHA-256
`0562517de949f4431177f204fe84cda3265f495d0eb0a949b9ced96cc5bd8276`
were read from the attested Linux installation. `connect(None)` supplies an empty input
stream; `query(AsyncIterable)` forwards the input envelope. No bundled CLI was run during
this source investigation.

The adapter submits fixed metadata text with all three supported flags. One stream iterator
must observe native init and drain a matching successful zero-turn, zero-usage, zero-cost
result before returning create identity or allowing a business send. Unknown messages,
effects, identity drift, model output, nonzero or unrecognized usage, process death and
timeouts fail closed and disconnect. Bootstrap results are excluded from business usage
and turn frames. Resume identity must match the requested native session.
The SDK replay echo is optional; when present it must match the bootstrap UUID and fixed
text without tool-result fields and with exactly the synthetic unclassified origin.
Duplicate echoes are refused. The actual successful proof below emitted no replay echo;
echo validation remains supported by the pinned source and fixtures rather than that
native observation.

This prevents a model query; it does not remove ordinary CLI startup, session persistence,
configured session-start hooks, discovery or MCP initialization. A result cannot undo an
initialization effect. Those remain governed by the admitted environment and hook policy.
An unsafe bootstrap currently fails create before normal session/usage persistence; it is
not a settled zero-usage turn. If a real runtime reports unexpected usage, quarantine that
attempt and retain independent native evidence before workspace cleanup; do not retry or
claim no spend from the refused business admission. Durable anomalous-create usage custody
is a separate limitation, not supplied by these fixtures.

The operator executed three separately retained disposable proofs with the exact existing
local image (`--pull=never`), `--network=none`, nonroot user, read-only root/source mount,
empty environment/credentials, and tmpfs home/config. Installed SDK 0.2.165 and CLI 2.1.294
plus the exact CLI file hash were checked before native startup. The proof called only
`LiveSession.start()` and `close()`, never `send()`, with no hooks or MCP configured.

| Proof | Actual offline outcome | Sanitized receipt SHA-256 |
| --- | --- | --- |
| 1 | Genuine init and successful zero-turn result reached; numeric-only usage validation refused the categorical/default usage fields. | `4c31ddd3f0684fcebe171ca4d6bfcd4b06a8b8bbb29cd29b48dbd0066284492b` |
| 2 | Complete exact usage defaults matched; the guard requiring null origin refused the synthetic unclassified origin. | `0392432334fcf92d75ed5d393af4a93d086ef053362a96dc17143f3b53fc265a` |
| 3 | Passed: one genuine native init, one success result, one metadata input, no echo, zero business turns, zero API duration/cost and all strict usage defaults matched. | `f5c84d6f4d3d51674836a5235e420e859ba1c1a6aa8d64e08efc530719fbe988` |

Every proof verified the owned container absent after cleanup. Earlier refusal receipts
remain unchanged. Proof 3 used session source SHA-256
`73f35e55295a4c57dbae1260c4b07d69907c2b29ebbe96191a92175f02ee5438`,
source-tree SHA-256 `53d3b828c0e5ffe561e6456268b0531c7e22ec1b548279ce001d84598d75fc81`,
and local image `sha256:9fa67866a14866560e3a2f1215133a40af17d11c3dc5ab571f96e550c8d94e61`.
Subsequent shared recovery edits change that source-tree identity; the proof remains
evidence for these exact reviewed startup bytes, not blanket evidence for later changes.

The successful offline proof cannot establish credential validity, provider entitlement,
business inference, configured hook/MCP behavior or live worker compatibility. Independent
live qualification remains required under its own admitted scope.

## Citations

Implementation: [single stream owner](../../../../../src/mission_control/adapters/claude/session.py).
Offline regressions: [bootstrap boundary](../../../../../tests/unit/claude/test_claude_bootstrap.py)
and [existing harness contracts](../../../../../tests/unit/claude/test_claude_harness.py).
