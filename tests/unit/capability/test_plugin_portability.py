"""Catalog plugins expand identically to their constituents on every lane (MO-32)."""

from datetime import UTC, datetime

import pytest

from mission_control.application.capabilities import catalog
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.authoring.contracts import (
    ExactDefinitionRef,
    PluginDefinition,
    PublishedDefinition,
)
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.capabilities.pins import CapabilityPin
from tests.support.projection_rows import INSTRUCTION, fixture_rows, plugin_row


@pytest.mark.parametrize("lane", list(LaneProfile))
def test_plugin_and_explicit_constituents_render_the_same_cognition(lane: LaneProfile) -> None:
    plugin, *loose = fixture_rows()
    # Optional unsupported members are deliberately omitted by the plugin policy.
    members = tuple(
        row
        for row in plugin.members
        if row.definition.host_support.status(lane).value == "supported"
        or row.pin not in {m.pin for m in plugin.definition.manifest.members if m.optional}
    )
    expanded = HOST_PROJECTORS.render((plugin, *loose), lane, INSTRUCTION)
    direct = HOST_PROJECTORS.render((*members, *loose), lane, INSTRUCTION)
    assert expanded.files == direct.files
    assert expanded.in_process == direct.in_process
    assert expanded.send_options == direct.send_options
    assert expanded.report.plugin_expansions
    assert not any("plugin" in path.path for path in expanded.files)


class SelfReferencingCatalog:
    """A catalog whose row for the plugin's pin names that same pin as a member.

    Content-addressed pins cannot form such a cycle; a corrupted or hand-edited catalog can,
    and the resolver must refuse it rather than recurse without bound.
    """

    def __init__(self, definition: PluginDefinition, pin: CapabilityPin) -> None:
        self._row = PublishedDefinition(
            ref=ExactDefinitionRef(
                kind=definition.kind,
                logical_id=pin.capability_id,
                revision=1,
                digest=pin.digest,
            ),
            definition=definition,
            published_at=datetime(2026, 11, 1, tzinfo=UTC),
            published_by="fixture",
        )
        self._pin = pin

    async def find_by_pin(self, capability_id: str, digest: str) -> PublishedDefinition | None:
        if (capability_id, digest) == (self._pin.capability_id, self._pin.digest):
            return self._row
        return None


async def test_catalog_rejects_a_cycle_before_recursing_forever() -> None:
    row = plugin_row()
    definition = PluginDefinition.model_validate(
        {
            **row.definition.model_dump(mode="json"),
            "manifest": {"members": [{"pin": row.pin.render(), "role": "skill"}]},
        }
    )
    pin = row.pin.render()
    with pytest.raises(catalog.CapabilityNotFound) as refused:
        await catalog.resolved_capability(
            SelfReferencingCatalog(definition, row.pin), row.pin, bundles=None
        )
    # Refused at the first revisit: the plugin, then itself as its own member.
    assert str(refused.value) == f"plugin dependency cycle: {pin} > {pin}"
