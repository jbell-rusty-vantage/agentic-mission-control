# Projection template

Copy the headings; replace the example bodies. The examples are shaped like this repository
(`src/mission_control/`, a lane adapter) so the level of detail is visible; they are not a design.

````markdown
---
type: Specification
title: "<TOPIC>: architecture projection"
description: "<one sentence: what is being built, for which decisions, as which modules>"
tags: [mission-control, projection, <area>]
---

# <TOPIC>: architecture projection

**Status:** draft <date> · accepted <date> · as built <date>. Decisions: `OC-D4`, `ADR-0057`.

## 1. Goal

<the owner's words, verbatim, then one sentence of restatement>

## 2. Module map

| Module | Layer | Interface (one line) | Hides | Refuses |
| --- | --- | --- | --- | --- |
| `application/authoring/lanes/<lane>.py` | application | `materialize(config, options) -> LaneBinding` | the native translation of the shared items | an item the mission requires that the lane cannot carry (`unsupported` + reason) |
| `domain/execution/materialization_receipt.py` | domain | `MaterializationReceipt` (existing) | nothing new | - |
| `adapters/<lane>/materializer.py` | adapter | `apply(binding) -> AppliedBinding` | the SDK calls | a binding whose digest does not match |

## 3. File tree

```text
src/mission_control/
├── application/authoring/lanes/
│   ├── support.py               changed: one row for <lane> in the per-lane table
│   └── <lane>.py                new: the lane adapter (deep module)
├── domain/execution/
│   └── materialization_receipt.py   unchanged, consumed
└── adapters/<lane>/
    └── materializer.py          changed: reads the sealed binding, verifies digests
tests/unit/application/authoring/lanes/
└── test_<lane>.py               new: the seam tests of §8
packages/mission-control-db-contract/migrations/
└── 1.4.5__<slug>.sql            new (only when §7 says so)
```

## 4. Interfaces

```python
@dataclass(frozen=True)
class LaneBinding:
    """The lane's native form of one node's configuration, sealed with its receipt."""
    native: Mapping[str, object]
    receipt: MaterializationReceipt


def materialize(config: AgentConfiguration, options: LaneOptions) -> LaneBinding:
    """Translate the shared configuration and this lane's discriminated options into the
    native form and sign the receipt. Pure: no I/O, no clock. Raises LaneRefusal when a
    required item is unsupported."""
```

## 5. Dependency chain

```text
interfaces/http/missions.py
  └─► application/authoring/manifest_launch_resolver.py      (interfaces call application)
        ├─► application/authoring/lanes/<lane>.py              (router → one adapter per lane)
        │     ├─► domain/capabilities/*                        (reads shared items)
        │     ├─► domain/authoring/provider_options.py         (reads its own discriminated container only)
        │     └─► domain/execution/materialization_receipt.py  (writes the receipt)
        └─► ports.LaneMaterializer                              (application depends on the port)
adapters/<lane>/materializer.py ──implements──► ports.LaneMaterializer   (adapters implement ports)
domain/*  imports: stdlib, pydantic, mission_control.domain only          (no database, Temporal, FastAPI, SDK)
```

## 6. Sequence

`POST /missions/{id}/launch` → `LaunchService.launch` → `ManifestLaunchResolver.node` →
`lanes/<lane>.materialize` → `LaneBinding` sealed into the launch binding →
`operation.execute` activity → `adapters/<lane>/materializer.apply` → receipt persisted.

## 7. Data and migrations

| Table / column | Change | Migration | Component version |
| --- | --- | --- | --- |
| `materialization_receipts.items` | none | - | - |

## 8. Seams and tests

| Seam | Test | Catches | Misses |
| --- | --- | --- | --- |
| `materialize()` | `tests/unit/.../test_<lane>.py::test_required_item_unsupported_refuses` | silent drops of required items | SDK behaviour |
| `apply()` with a fake SDK | `tests/unit/adapters/<lane>/test_materializer.py` | digest mismatch handling | live provider drift |

## 9. Receipts and observability

The receipt row per item (`native | emulated | degraded | unsupported`), the ledger `CHANGES.md`
entry, and the frame the materializer emits.

## 10. Non-goals and open questions

- Non-goal: <what this projection deliberately leaves out>
- Open: <question> → interview round <n>

## Conformance (as built <date>)

| Projected | As built | Why |
| --- | --- | --- |
| `materialize(config, options)` | `materialize(config, options, *, clock)` | the receipt needs a timestamp; injected to keep the module pure |
````
