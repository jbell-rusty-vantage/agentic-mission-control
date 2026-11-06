"""OVE-204 slice 7: `S3ArtifactPayloadStore` against a real S3-compatible endpoint.

Env-gated (skips without every `MC_TEST_S3_*` variable): the local Supabase stack serves
Storage's S3 protocol at `http://127.0.0.1:<api port>/storage/v1/s3` (path-style, region
`local`, the keys `supabase status` prints); the bucket is the `mc.storage.mission-payloads`
seed's `mission-payloads`. One stage + retrieve round trip through the production adapter (the
one `s3_client` choke point: endpoint, region, path style, SigV4, checksums only when required),
a digest refusal, and the presigned GET read back over plain HTTP. With
`MC_TEST_S3_EVIDENCE` set, the observed facts (no credentials) are written there as JSON.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import httpx
import pytest

from mission_control.adapters.storage.artifact_payloads import S3ArtifactPayloadStore
from mission_control.adapters.storage.s3 import s3_client
from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.bootstrap.settings import Settings
from mission_control.domain.execution.errors import WorkspaceDigestMismatch

REQUIRED = (
    "MC_TEST_S3_ENDPOINT_URL",
    "MC_TEST_S3_BUCKET",
    "MC_TEST_S3_ACCESS_KEY_ID",
    "MC_TEST_S3_SECRET_ACCESS_KEY",
)
pytestmark = pytest.mark.skipif(
    any(not os.environ.get(name) for name in REQUIRED),
    reason="S3-compatible endpoint not configured (MC_TEST_S3_* unset)",
)


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        aws_profile=None,
        s3_bucket=os.environ["MC_TEST_S3_BUCKET"],
        s3_endpoint_url=os.environ["MC_TEST_S3_ENDPOINT_URL"],
        s3_force_path_style=True,
        s3_region=os.environ.get("MC_TEST_S3_REGION", "local"),
        s3_access_key_id=os.environ["MC_TEST_S3_ACCESS_KEY_ID"],
        s3_secret_access_key=os.environ["MC_TEST_S3_SECRET_ACCESS_KEY"],
    )


@pytest.mark.asyncio
async def test_stage_retrieve_and_presigned_get_round_trip() -> None:
    settings = _settings()
    bucket = os.environ["MC_TEST_S3_BUCKET"]
    store = S3ArtifactPayloadStore(settings, bucket)
    content = f"OVE-204 slice 7 round trip {uuid.uuid4()}\n".encode() * 64
    digest = f"sha256:{sha256(content).hexdigest()}"

    address = await store.stage(
        artifact_id="ove-204-slice-7",
        content=content,
        content_digest=digest,
        media_type="text/plain",
    )
    assert address.object_ref == f"s3://{bucket}/artifacts/sha256/{digest.removeprefix('sha256:')}"
    assert address == store.address_for(content_digest=digest, size_bytes=len(content))
    assert await store.retrieve(address) == content

    async with s3_client(settings) as client:
        assert client.meta.endpoint_url == settings.s3_endpoint_url
        assert client.meta.config.s3 == {"addressing_style": "path"}
        head = await client.head_object(
            Bucket=bucket, Key=address.object_ref.removeprefix(f"s3://{bucket}/")
        )
    assert head["ContentLength"] == len(content)
    assert head["Metadata"]["sha256"] == digest.removeprefix("sha256:")

    wrong = ArtifactPayloadAddress(
        object_ref=address.object_ref,
        content_digest="sha256:" + "0" * 64,
        size_bytes=len(content),
    )
    with pytest.raises(WorkspaceDigestMismatch):
        await store.retrieve(wrong)

    url = await store.runtime_url(address, ttl_seconds=120)
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.get(url)
    presigned = {"status": response.status_code, "bytes_match": response.content == content}
    assert presigned == {"status": 200, "bytes_match": True}

    _record_evidence(
        {
            "observed_at": datetime.now(UTC).isoformat(),
            "endpoint": settings.s3_endpoint_url,
            "region": settings.s3_region,
            "bucket": bucket,
            "object_ref": address.object_ref,
            "content_digest": digest,
            "size_bytes": len(content),
            "head_content_length": head["ContentLength"],
            "retrieve_bytes_match": True,
            "wrong_digest_refused": "WorkspaceDigestMismatch",
            "presigned_get": presigned,
        }
    )


def _record_evidence(facts: dict[str, object]) -> None:
    evidence = os.environ.get("MC_TEST_S3_EVIDENCE")
    if evidence:
        Path(evidence).parent.mkdir(parents=True, exist_ok=True)
        Path(evidence).write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
