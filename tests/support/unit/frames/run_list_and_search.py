"""Builders, constants and fakes that other test files import.

Moved from tests/unit/frames/test_run_list_and_search.py.
"""

from __future__ import annotations

from collections.abc import Sequence

from mission_control.application.frames.search import ProjectionReceipt, TranscriptDocument


class MemoryDocuments:
    def __init__(self) -> None:
        self.rows: dict[str, TranscriptDocument] = {}

    async def replace(
        self, request_scope: str, run_key: str, documents: Sequence[TranscriptDocument]
    ) -> ProjectionReceipt:
        fresh = {document.cursor: document for document in documents}
        changed = sum(1 for key, value in fresh.items() if self.rows.get(key) != value)
        deleted = len(set(self.rows) - set(fresh))
        self.rows = fresh
        return ProjectionReceipt(
            run_id=run_key, upserted=changed, deleted=deleted, documents=len(fresh)
        )

    async def search(
        self, request_scope: str, run_key: str, text: str, *, limit: int
    ) -> tuple[tuple[str, float], ...]:
        words = text.lower().split()
        scored = [
            (
                cursor,
                float(sum(word in f"{doc.title} {doc.body_excerpt}".lower() for word in words)),
            )
            for cursor, doc in self.rows.items()
        ]
        return tuple(sorted((item for item in scored if item[1]), key=lambda item: -item[1]))[
            :limit
        ]
