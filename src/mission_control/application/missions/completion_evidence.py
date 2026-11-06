"""Read port for already committed, scope-bound completion validation receipts."""

from typing import Protocol

from mission_control.contracts.run_evidence import CompletionEvidencePage


class CompletionEvidenceReader(Protocol):
    async def list(
        self,
        request_scope: str,
        run_id: str,
        *,
        after_family_version: int = 0,
        limit: int = 100,
    ) -> CompletionEvidencePage: ...


class CompletionEvidenceCorrupt(ValueError):
    """A persisted receipt fails its identity or integrity contract."""
