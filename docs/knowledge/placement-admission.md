---
type: Concept
category: execution
title: Placement admission
description: Durable provider capacity reservations and freshly checked manifest lane alternatives before sealing.
tags: [mission-control, placement, capacity, lanes, manifest, implementation]
aliases: [placement, capacity reservation, lane alternatives, prefer_cloud]
questions:
  - How are provider capacity and lane alternatives admitted?
  - What happens when a provider has no free capacity?
  - How do I declare lane alternatives like prefer_cloud in a manifest?
  - Can a worker swap to another lane after the definition is sealed?
updated: 2026-11-01
---

# Placement admission

`MISSION_CONTROL_PLACEMENT_LIMITS` supplies JSON per-profile `max_active`, optional
`launches_per_minute`, and `retry_after_s`. Defaults admit eight Cursor Cloud sessions
and fifteen launches per minute, four sessions on each managed API profile, and three
sessions on each local CLI profile. Migration 0041 stores installation/application-wide
reservations across tenants. A reservation lasts until session settlement; retries reuse
the HEID reservation. Releasing a session does not erase its recent launch count.

Capacity refusal enters the existing durable Temporal provider-limit wait. It does not
prepare or start a provider session. Controls can interrupt that wait. The database clock
and installation/application/profile advisory lock enforce concurrent admissions; runtime
roles cannot enumerate reservations or free another tenant's session.

A v2 environment can declare alternatives:

```yaml
environment:
  lane: deep_agents
  placement: prefer_cloud
  lanes: [cursor_cloud, deep_agents]
  lane_environments:
    cursor_cloud:
      lane: cursor_cloud
      execution_environment:
        kind: provider_hosted
        provider: cursor
        environment_ref: env-reviewed
    deep_agents:
      lane: deep_agents
```

Alternatives overlay the containing environment. Each preferred lane must name its exact
environment; nested preferences within a candidate are refused. Up to four profiles are
allowed per preference list and up to 64 complete candidate documents per compile.
`prefer_cloud` orders hosted profiles first while preserving order within each group;
`cloud_only` and `local_only` filter the declared list.

Every candidate independently runs capability resolution, feature, environment and budget
admission, and lowering. Production selection then requires the authoritative lane registry's
`qualified` describe and freshly assessed scoped prerequisites. An unqualified-worker override
does not count as qualification. The selected definition is the one submitted and sealed;
workers never substitute another lane after sealing. The original author's manifest digest
remains the request idempotency identity. Runtime capacity can change after compile and is
reserved atomically before prepare; full placements wait durably rather than swapping lanes.

No provider was contacted for the tests. Qualification evidence must come from the existing
bounded provider drills. Missing qualification or trusted prerequisite evidence refuses
preference selection.

Placement is the only local-versus-cloud choice today: it picks one lane at compile and seals it, and a full placement waits instead of moving; one session that moves between local and cloud lanes is a
goal ([lanes and harness](lanes-and-harness.md)). The lane registry that supplies the `qualified` check is `application/resolution/registries.py::LaneRegistry`.

Built / specified / goal: capacity reservation, wait and preferences built and tested (unit, PostgreSQL, real Temporal); no provider contacted by these tests.

## Citations

- Code: [placement](../../src/mission_control/application/workspaces/placement.py), [preferences](../../src/mission_control/application/workspaces/preferences.py), [manifest service](../../src/mission_control/application/authoring/manifest_service.py), [lane registry](../../src/mission_control/application/resolution/registries.py), [migration 0041](../../packages/mission-control-db-contract/component/migrations/0041_placement_capacity.sql).
- Tests: [admission](../../tests/unit/workspaces/test_placement_admission.py), [preferences](../../tests/unit/workspaces/test_placement_preferences.py), [capacity in PostgreSQL](../../tests/integration/postgres/test_placement_capacity.py), [durable wait](../../tests/integration/temporal/test_placement_wait.py).
