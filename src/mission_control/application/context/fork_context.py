"""Resolve fork conversation only through a sealed, scoped source RunSnapshot."""

from __future__ import annotations

from typing import Protocol

from mission_control.domain.context.refs import parse_durable_input_locator
from mission_control.domain.context.snapshot_evidence import (
    MAX_CONVERSATION_BYTES,
    ConversationEnvelope,
    digest_bytes,
)
from mission_control.domain.policies.forks import RunSnapshotManifest


class SnapshotReader(Protocol):
    async def get(self, request_scope: str, snapshot_id: str) -> RunSnapshotManifest | None: ...


class CustodyReader(Protocol):
    async def retrieve(self, durable_ref: str) -> bytes: ...


class ForkContextReader:
    def __init__(self, snapshots: SnapshotReader, custody: CustodyReader) -> None:
        self._snapshots = snapshots
        self._custody = custody

    async def read(
        self,
        *,
        request_scope: str,
        snapshot_ref: str,
        snapshot_digest: str,
        content_bytes: int,
        restore_refs: tuple[str, ...],
    ) -> bytes:
        prefix = "run-snapshot://"
        if not snapshot_ref.startswith(prefix):
            raise ValueError("fork conversation requires a registered run snapshot")
        snapshot = await self._snapshots.get(request_scope, snapshot_ref.removeprefix(prefix))
        if snapshot is None:
            raise ValueError("fork conversation source snapshot is missing")
        # Validate even in-memory ports; a model_copy must not bypass the sealed contract.
        snapshot = RunSnapshotManifest.model_validate(snapshot.model_dump(mode="json"))
        evidence = snapshot.conversation
        if (
            snapshot.request_scope != request_scope
            or snapshot.snapshot_digest != snapshot_digest
            or evidence is None
        ):
            raise ValueError("fork conversation snapshot custody differs")
        if evidence.origin.restore_ref not in restore_refs:
            raise ValueError("fork conversation does not match the commanded workspace restore")
        if content_bytes != evidence.content_bytes:
            raise ValueError("fork conversation declared size differs")
        _, locator_digest, locator_size = parse_durable_input_locator(evidence.durable_ref)
        if (locator_digest, locator_size) != (evidence.content_digest, evidence.content_bytes):
            raise ValueError("fork conversation locator metadata differs")
        raw = await self._custody.retrieve(evidence.durable_ref)
        if (
            len(raw) > MAX_CONVERSATION_BYTES
            or len(raw) != evidence.content_bytes
            or digest_bytes(raw) != evidence.content_digest
        ):
            raise ValueError("fork conversation artifact size or digest differs")
        envelope = ConversationEnvelope.model_validate_json(raw)
        if (
            envelope.origin != evidence.origin
            or envelope.conversation.disposition != evidence.disposition
        ):
            raise ValueError("fork conversation artifact origin differs")
        # Explicit absence is useful evidence, but never acceptance of required conversation.
        if envelope.conversation.disposition != "exported":
            raise ValueError("fork conversation was unavailable at the source")
        return raw
