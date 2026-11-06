from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest

from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.application.signals.artifacts import ArtifactCustodyService, CommittedUpload
from mission_control.application.signals.drainer import DrainRejected


class Storage:
    def __init__(self, content):
        self.content, self.staged, self.deleted, self.prior = content, 0, 0, None

    async def read(self, key, *, max_bytes):
        return self.content

    async def delete(self, key):
        self.deleted += 1

    async def stage(self, *, artifact_id, content, content_digest, media_type):
        self.staged += 1
        return ArtifactPayloadAddress(
            object_ref=artifact_id, content_digest=content_digest, size_bytes=len(content)
        )

    async def require_current(self, upload):
        pass

    async def rejected(self, upload, reason):
        pass

    async def existing(self, upload):
        return self.prior

    async def verified(self, upload, address):
        self.prior = address


def upload(content):
    return CommittedUpload(
        uuid4(),
        "scope",
        "run",
        1,
        "output",
        "key",
        "sha256:" + sha256(content).hexdigest(),
        len(content),
        "text/plain",
        datetime.now(UTC) + timedelta(minutes=1),
    )


@pytest.mark.asyncio
async def test_large_verified_and_replay_after_quarantine_deleted():
    content = b"a" * 4_600_000
    store = Storage(content)
    service = ArtifactCustodyService(store, store, store)
    declaration = upload(content)
    first = await service.verify(declaration, request_scope="scope", generation=1)
    store.content = b""
    assert await service.verify(declaration, request_scope="scope", generation=1) == first
    assert store.staged == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"digest": "sha256:" + "0" * 64}, "artifact_digest_mismatch"),
        ({"size_bytes": 8}, "artifact_size_mismatch"),
        ({"request_scope": "other"}, "artifact_cross_scope_or_stale"),
        ({"generation": 2}, "artifact_cross_scope_or_stale"),
        ({"expires_at": datetime.now(UTC) - timedelta(seconds=1)}, "artifact_expired"),
    ],
)
async def test_negatives_before_custody(change, reason):
    store = Storage(b"test")
    with pytest.raises(DrainRejected, match=reason):
        await ArtifactCustodyService(store, store, store).verify(
            replace(upload(b"test"), **change), request_scope="scope", generation=1
        )
    assert store.staged == 0
    assert store.deleted == (0 if reason == "artifact_cross_scope_or_stale" else 1)


@pytest.mark.asyncio
async def test_quarantine_rest_signed_upload_and_bounded_download():
    import httpx

    from mission_control.adapters.supabase_storage.ingress import SupabaseQuarantineStore
    from mission_control.application.signals.contracts import IngressRejected

    def handler(request):
        if request.method == "POST":
            return httpx.Response(
                200, json={"url": "/object/upload/sign/quarantine/key?token=once"}
            )
        return httpx.Response(200, content=b"oversized")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        store = SupabaseQuarantineStore(
            client,
            project_url="https://project.supabase.co",
            bucket="quarantine",
            credential="fixture",
        )
        signed = await store.signed_upload("key")
        assert signed.token == "once"
        assert signed.url.startswith("https://project.supabase.co/storage/v1/object/upload/sign/")
        with pytest.raises(IngressRejected, match="artifact_size_mismatch"):
            await store.read("key", max_bytes=3)


@pytest.mark.asyncio
async def test_quarantine_signed_response_cannot_redirect_credentials():
    import httpx

    from mission_control.adapters.supabase_storage.ingress import SupabaseQuarantineStore

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"url": "https://attacker.invalid?token=x"})
        )
    ) as client:
        store = SupabaseQuarantineStore(
            client,
            project_url="https://project.supabase.co",
            bucket="quarantine",
            credential="fixture",
        )
        with pytest.raises(RuntimeError, match="invalid storage"):
            await store.signed_upload("key")
