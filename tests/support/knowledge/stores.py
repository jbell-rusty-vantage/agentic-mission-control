"""The one staging fake: an in-memory ``MissionFileStagingPort`` and durable reader.

The knowledge stores it sat beside are src ``mission_control.adapters.knowledge.memory``.
"""

from __future__ import annotations

import hashlib


class InMemoryStaging:
    """The one staging fake: ``MissionFileStagingPort`` + durable reader over a dict.

    It replaces the content-addressed ``FakeStaging`` copies of ``tests/fixtures/continuation``
    and the stage-handoff support module. ``objects`` holds the staged bytes by locator.
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.corrupt_next: int = 0
        self.unreadable_next: int = 0
        # Item name suffix -> how many of its next reads fail (per item, not global).
        self.unreadable_items: dict[str, int] = {}
        self.staged: list[str] = []

    async def stage(self, *, request_scope: str, name: str, content: bytes, media_type: str) -> str:
        digest = "sha256:" + hashlib.sha256(content).hexdigest()
        stored = content
        if self.corrupt_next:
            self.corrupt_next -= 1
            stored = content + b"\x00corrupted"
        locator = f"mem://{request_scope}/{name}#{digest}:{len(content)}"
        self.objects[locator] = stored
        self.staged.append(locator)
        return locator

    async def retrieve(self, durable_ref: str) -> bytes:
        name = durable_ref.split("#", 1)[0].rsplit("/", 1)[-1]
        if self.unreadable_items.get(name):
            self.unreadable_items[name] -= 1
            raise OSError("object store unavailable")
        if self.unreadable_next:
            self.unreadable_next -= 1
            raise OSError("object store unavailable")
        # A durable reader resolves the object part of the locator; a test that replaces or
        # drops the bytes under that object ref is what the reader then sees.
        base = durable_ref.partition("#")[0]
        if base in self.objects:
            return self.objects[base]
        return self.objects[durable_ref]


__all__ = ["InMemoryStaging"]
