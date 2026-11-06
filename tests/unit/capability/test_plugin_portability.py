"""Catalog plugins expand identically to their constituents on every lane (MO-32)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mission_control.application.capabilities import catalog
from mission_control.bootstrap.host_projection import HOST_PROJECTORS
from mission_control.domain.authoring.contracts import PluginDefinition
from mission_control.domain.capabilities.host_support import LaneProfile
from tests.fixtures.projections.rows import INSTRUCTION, fixture_rows, plugin_row


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


async def test_catalog_rejects_a_cycle_before_recursing_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = plugin_row()
    definition = PluginDefinition.model_validate(
        {
            **row.definition.model_dump(mode="json"),
            "manifest": {"members": [{"pin": row.pin.render(), "role": "skill"}]},
        }
    )
    lookup = AsyncMock(return_value=SimpleNamespace(definition=definition))
    monkeypatch.setattr(catalog, "find_published_by_pin", lookup)
    with pytest.raises(catalog.CapabilityNotFound, match="plugin dependency cycle"):
        await catalog.resolved_capability(object(), row.pin, bundles=None)
    assert lookup.await_count == 2
