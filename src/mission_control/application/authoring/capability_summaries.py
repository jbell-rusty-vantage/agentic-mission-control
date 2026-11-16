"""One line of catalog description per exact Capability Pin, for the Purpose Card.

The launch author tells every node what it was given (``purpose_card.py``): the name of each
bound capability and one line of its catalog description. A description belongs to an exact
published revision, so reading it by pin is reading a sealed fact. Only the definition row is
read: no bundle bytes, no custody, nothing a launch could be refused for. A pin the catalog
does not hold is left out, and its capability is listed by name alone.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence

from mission_control.application.capabilities.catalog import find_published_by_pin
from mission_control.domain.capabilities.pins import CapabilityPin

CapabilitySummariesPort = Callable[[Sequence[str]], Awaitable[Mapping[str, str]]]
"""Exact pin texts (``id@version#sha256:...``) to each published row's description."""


class CatalogCapabilitySummaries:
    """:data:`CapabilitySummariesPort` over the catalog's published definitions."""

    def __init__(self, definitions: object) -> None:
        self._definitions = definitions

    async def __call__(self, pins: Sequence[str]) -> Mapping[str, str]:
        summaries: dict[str, str] = {}
        for text in dict.fromkeys(pins):
            try:
                pin = CapabilityPin.parse(text)
            except ValueError:  # not an exact pin: nothing to look up
                continue
            published = await find_published_by_pin(self._definitions, pin)
            description = getattr(published.definition, "description", None) if published else None
            if isinstance(description, str) and description.strip():
                summaries[text] = description
        return summaries


__all__ = ["CapabilitySummariesPort", "CatalogCapabilitySummaries"]
