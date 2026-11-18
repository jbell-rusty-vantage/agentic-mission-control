"""Builders, constants and fakes that other test files import.

Moved from tests/integration/temporal/test_ft_g7_visibility.py.
"""

from __future__ import annotations

from temporalio.client import WorkflowHistory


def _mc_upserts(history: WorkflowHistory) -> list[dict[str, str]]:
    """The fast-track upserts of a history, decoded as `{name: raw json}`."""

    upserts: list[dict[str, str]] = []
    for event in history.events:
        if not event.HasField("upsert_workflow_search_attributes_event_attributes"):
            continue
        fields = event.upsert_workflow_search_attributes_event_attributes.search_attributes
        mc = {
            name: payload.data.decode("utf-8")
            for name, payload in fields.indexed_fields.items()
            if name.startswith("mc_")
        }
        if mc:
            upserts.append(mc)
    return upserts
