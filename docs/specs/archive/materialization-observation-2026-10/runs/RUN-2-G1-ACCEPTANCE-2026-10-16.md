---
type: Acceptance Mapping
title: "Run 2 G1 component proof and remaining host assembly"
description: "Default-off transport, fixed deadline/encoding defects and full G1 gaps."
---

# G1 remains unqualified

Source preparation lives in ignored `.scratch/run2-completion-20261016/g1-assembly/`.
It is operational preparation, not an enabled serving route. The retired controller
still refuses live use; the existing lifecycle refuses the non-fixture transport.
[Current boundaries](RUN-2-OPERATIONS-BOUNDARIES-2026-10-16.md) and original S0
acceptance remain in force.

| Criterion | Checked component | Remaining evidence |
| --- | --- | --- |
| Admission/aliases/protected denial | Fixtures deny public and internal protected IDs, pins/origin/identity/default-off | Actual global registry/alias admission and exact future identity registration |
| Normal API/authority | Actual MissionClient against mock transport and newly owned loopback403 fixture | Authenticated serving route/current principal;403 never authorizes elevation |
| Absolute deadline | Monotonic reserve includes spawn, request, read and exact-child termination | Actual native/wrapper supervisor lifecycle on current host |
| Spawn/cancel race | Retained spawn task; bounded join; late exact-handle kill callback; unresolved handoff poisons transport | No claim that OS-hung process creation is synchronously proven stopped |
| Response bounds | HTTP1MiB, IPC64KiB/stderr4KiB; identity encoding requested and nonidentity refused before buffering | Actual serving/native capture boundaries |
| Secret isolation | Pinned direct Python per operation; bounded private stdin, bootstrap-only env, no ambient keys/proxies, redirects/retries | Actual independent custody integration and secret-sentinel host proof |
| Finalization |39 existing lifecycle fixtures and18 transport cases, combined57 pass35.62s | Independent NativeSupervisor, private terminal bytes, direct/wrapper descendants, listener absence and exact cleanup |

Independent review exposed spawn awaiting outside cleanup and unbounded compressed
response handling. Both were fixed, regressions passed, and root reviewed the
final component. Ruff/format3 files and mypy2 source modules passed. Receipt
`g1-assembly/spawn-fix-receipt.json`; transportSHA256
`33b52fca6cbbb37961ff7c57c7c2b813db4f13c478e63a6551159937bc3fe4cb`,
workerSHA256`967060ae1a6bb0a0719c30ea1f9d06620eb323c5937ff1fadc073847d986f373`.

## Next bounded assembly package

Owner: G1 host integrator; one editor for lifecycle/transport/supervisor assembly,
no concurrent native/heavy lease. Build the actual registry and independent
supervisor/private capture join; use new synthetic IDs and owned child/listener
fixtures first. Retain protected deny-list and default-off until all original
admission/finalization/cleanup criteria are demonstrated together. Acceptance
must name the principal, exact child/job/listener handles, registry entries,
durable intent and terminal/custody digest, and prove cleanup after timeout,
caller cancellation, frozen/flooding child and partial capture. Never kill by
process name or touch an existing run/service.

The separate standalone CLI Windows Job fixture proved held-child exit for its
exact owned parent/child only; it does not qualify sandbox users, wrappers or
full G1. No serving normal-API or native G1 admission was invoked. Additional
fixture counts alone cannot close the actual host-assembly requirement.
