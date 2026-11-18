"""The one staging fake: an in-memory ``MissionFileStagingPort`` and durable reader.

The knowledge stores it sat beside are src ``mission_control.adapters.knowledge.memory``.
"""

from __future__ import annotations

import hashlib


class StagedObjects(dict[str, bytes]):
    """Staged bytes keyed by object ref: a full ``<object>#<digest>:<size>`` locator and its
    object part name the same entry, as a durable reader resolves them."""

    @staticmethod
    def _key(ref: object) -> object:
        return ref.partition("#")[0] if isinstance(ref, str) else ref

    def __getitem__(self, ref: str) -> bytes:
        return super().__getitem__(self._key(ref))  # type: ignore[arg-type]

    def __setitem__(self, ref: str, content: bytes) -> None:
        super().__setitem__(self._key(ref), content)  # type: ignore[arg-type]

    def __delitem__(self, ref: str) -> None:
        super().__delitem__(self._key(ref))  # type: ignore[arg-type]

    def __contains__(self, ref: object) -> bool:
        return super().__contains__(self._key(ref))

    def get(self, ref: str, default: bytes | None = None) -> bytes | None:  # type: ignore[override]
        return super().get(self._key(ref), default)  # type: ignore[arg-type]

    def pop(self, ref: str, *default: bytes) -> bytes:  # type: ignore[override]
        return super().pop(self._key(ref), *default)  # type: ignore[arg-type]


class InMemoryStaging:
    """The one staging fake: ``MissionFileStagingPort`` + durable reader over a dict.

    It replaces the content-addressed ``FakeStaging`` copies of ``tests/fixtures/continuation``
    and the stage-handoff support module. ``objects`` holds the staged bytes by object ref.
    """

    def __init__(self) -> None:
        self.objects: StagedObjects = StagedObjects()
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
        return self.objects[durable_ref]


__all__ = ["InMemoryStaging"]
