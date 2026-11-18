"""The one in-memory lane artifact sink (the `stage`/`retrieve` port every lane harness writes to).

It replaces the three copies that lived in `tests/fixtures/cursor_local.py`,
`tests/unit/codex/support.py` and `tests/unit/workspaces/workspace_fixtures.py`. `staged` maps each
durable ref to its bytes, so a test can read, corrupt or drop a staged payload; `files()` also
gives the staged name and media type.
"""

from __future__ import annotations


class MemoryArtifacts:
    def __init__(self) -> None:
        self.staged: dict[str, bytes] = {}
        self.described: dict[str, tuple[str, str]] = {}
        self._next = 0

    async def stage(self, *, request_scope: str, name: str, content: bytes, media_type: str) -> str:
        del request_scope
        ref = f"payload://{self._next}/{name}"
        self._next += 1
        self.staged[ref] = content
        self.described[ref] = (name, media_type)
        return ref

    async def retrieve(self, durable_ref: str) -> bytes:
        try:
            return self.staged[durable_ref]
        except KeyError as error:
            raise LookupError(durable_ref) from error

    def files(self) -> dict[str, tuple[str, bytes, str]]:
        """Every staged payload still held, by ref, as `(name, content, media_type)`."""

        return {
            ref: (self.described[ref][0], content, self.described[ref][1])
            for ref, content in self.staged.items()
        }


__all__ = ["MemoryArtifacts"]
