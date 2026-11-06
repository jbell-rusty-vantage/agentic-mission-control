"""MO-44: a published Capability Kind `watcher` (`mc.watcher.v1`) is resolved by exact pin at
manifest compile and may only be narrowed by the pinning entry (SPEC-04 §5.1)."""

from __future__ import annotations

from typing import Any

import pytest

from mission_control.application.authoring.control_plane_repository import (
    InMemoryDefinitionRepository,
)
from mission_control.domain.authoring.contracts import WatcherDefinition
from mission_control.domain.capabilities.catalog_entry import capability_pin
from tests.unit.authoring.test_manifest_compile import AT, minimal, scope, service, text

STALL_DETECTOR = WatcherDefinition.model_validate(
    {
        "logical_id": "watcher.fixture-stall-detector",
        "title": "Stall detector",
        "description": "Notify the coordinator when no frames arrive for 20 minutes",
        "spec": {
            "on": {"absence": {"of": ["frame"], "for": "20m"}},
            "then": [{"notify": {"kind": "blocked"}}],
            "limits": {"max_fires": 5, "min_interval": "5m"},
        },
    }
)
POINTER = "/mission/controls/watchers/0"


async def publish(definitions: InMemoryDefinitionRepository) -> None:
    await definitions.publish(STALL_DETECTOR, "fixture", AT, 0)


async def compile_pinned(entry: dict[str, Any]) -> Any:
    compile_service, definitions, _ = await service(publish)
    published = {
        item.ref.logical_id: capability_pin(item).render()
        for item in await definitions.list_published_definitions()
    }
    document = minimal()
    document["manifest"] = "mission/v2"
    pin = entry.pop("pin", None) or published[entry.pop("logical_id")]
    document["mission"]["controls"]["watchers"] = [{"id": "stall", "pin": pin, **entry}]
    compilation = await compile_service.compile(text(document), scope())
    blockers = {(item.pointer, item.reason) for item in compilation.report.blockers}
    watchers = compilation.definitions[0].policies.watchers if compilation.definitions else ()
    return blockers, watchers, published


@pytest.mark.asyncio
async def test_a_pinned_watcher_takes_its_body_from_the_catalog_and_narrows_its_limits() -> None:
    blockers, watchers, published = await compile_pinned(
        {"logical_id": "watcher.fixture-stall-detector", "limits": {"max_fires": 2}}
    )
    assert blockers == set()
    (descriptor,) = watchers
    assert (descriptor.watcher_id, descriptor.origin, descriptor.pointer) == (
        "stall",
        "catalog",
        POINTER,
    )
    assert descriptor.template == published["watcher.fixture-stall-detector"]
    assert descriptor.trigger.kind == "absence" and descriptor.trigger.seconds == 20 * 60
    assert (descriptor.boundaries.max_fires, descriptor.boundaries.min_interval_seconds) == (
        2,
        300,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("entry", "blocker"),
    [
        (
            {"logical_id": "watcher.fixture-stall-detector", "limits": {"max_fires": 9}},
            "widens_authority",
        ),
        # A pin resolves within the role's kind: another kind's row is not found.
        ({"logical_id": "mcp.biomcp"}, "pin_not_found"),
        ({"pin": "watcher.absent@1.0.0#sha256:" + "a" * 64}, "pin_not_found"),
    ],
)
async def test_a_pin_that_widens_names_another_kind_or_is_missing_is_a_blocker(
    entry: dict[str, Any], blocker: str
) -> None:
    blockers, watchers, _ = await compile_pinned(entry)
    assert any(pointer.startswith(POINTER) and reason == blocker for pointer, reason in blockers)
    assert watchers == ()
