"""Slim Supabase quarantine REST adapter, matching installed storage3 wire methods.

Only httpx is imported. Dedicated bucket/credential are trusted application bindings.
Downloads are bounded while streaming; no provider runtime or storage SDK is needed.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from mission_control.application.capabilities.bundle_custody import SignedUpload
from mission_control.application.signals.contracts import IngressRejected


class SupabaseQuarantineStore:
    def __init__(
        self, client: httpx.AsyncClient, *, project_url: str, bucket: str, credential: str
    ) -> None:
        parsed = urlsplit(project_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("quarantine requires a trusted HTTPS project URL")
        if not bucket or "/" in bucket:
            raise ValueError("invalid quarantine bucket")
        self._client = client
        self._base = project_url.rstrip("/") + "/storage/v1"
        self._bucket = quote(bucket, safe="")
        self._headers = {"authorization": f"Bearer {credential}", "apikey": credential}

    def _path(self, key: str) -> str:
        if not key or any(p in {"", ".", ".."} for p in key.split("/")):
            raise ValueError("invalid quarantine object key")
        return self._bucket + "/" + quote(key, safe="/")

    async def signed_upload(self, storage_key: str) -> SignedUpload:
        response = await self._client.post(
            self._base + "/object/upload/sign/" + self._path(storage_key),
            headers=self._headers,
            follow_redirects=False,
        )
        response.raise_for_status()
        relative = response.json()["url"]
        if not isinstance(relative, str) or not relative.startswith("/object/upload/sign/"):
            raise RuntimeError("invalid storage signed upload response")
        url = self._base + relative
        tokens = parse_qs(urlsplit(url).query).get("token", [])
        if len(tokens) != 1:
            raise RuntimeError("missing storage signed upload token")
        return SignedUpload(path=storage_key, url=url, token=tokens[0])

    async def read(self, key: str, *, max_bytes: int) -> bytes:
        if max_bytes < 0:
            raise ValueError("invalid quarantine size bound")
        async with self._client.stream(
            "GET",
            self._base + "/object/" + self._path(key),
            headers=self._headers,
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared is not None and (not declared.isdigit() or int(declared) > max_bytes):
                raise IngressRejected(422, "artifact_size_mismatch")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                if len(content) + len(chunk) > max_bytes:
                    raise IngressRejected(422, "artifact_size_mismatch")
                content.extend(chunk)
            return bytes(content)

    async def delete(self, key: str) -> None:
        self._path(key)
        response = await self._client.request(
            "DELETE",
            self._base + "/object/" + self._bucket,
            headers=self._headers,
            json={"prefixes": [key]},
            follow_redirects=False,
        )
        response.raise_for_status()


class SupabaseArtifactPayloadStore:
    """Immutable digest-key byte custody; registering a version is a separate SQL action."""

    def __init__(self, store: SupabaseQuarantineStore, *, namespace: str) -> None:
        if not namespace or any(p in {"", ".", ".."} for p in namespace.split("/")):
            raise ValueError("invalid custody namespace")
        self._store, self._namespace = store, namespace

    async def stage(
        self, *, artifact_id: str, content: bytes, content_digest: str, media_type: str
    ) -> Any:
        from hashlib import sha256

        from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress

        if "sha256:" + sha256(content).hexdigest() != content_digest:
            raise ValueError("custody payload digest mismatch")
        key = self._namespace + "/sha256/" + content_digest.removeprefix("sha256:")
        response = await self._store._client.post(
            self._store._base + "/object/" + self._store._path(key),
            headers=self._store._headers | {"content-type": media_type, "x-upsert": "false"},
            content=content,
            follow_redirects=False,
        )
        if response.status_code in {400, 409}:
            body = response.json()
            if (
                str(body.get("error", "")) not in {"Duplicate", "ResourceAlreadyExists"}
                and str(body.get("statusCode", "")) != "409"
            ):
                response.raise_for_status()
            if await self._store.read(key, max_bytes=len(content)) != content:
                raise ValueError("custody digest path contains conflicting bytes")
        else:
            response.raise_for_status()
        return ArtifactPayloadAddress(
            object_ref=f"supabase://{self._store._bucket}/{key}",
            content_digest=content_digest,
            size_bytes=len(content),
        )

    async def retrieve(self, address: Any) -> bytes:
        from hashlib import sha256

        prefix = f"supabase://{self._store._bucket}/{self._namespace}/sha256/"
        if not address.object_ref.startswith(prefix):
            raise ValueError("artifact belongs to a different custody namespace")
        key = address.object_ref.removeprefix(f"supabase://{self._store._bucket}/")
        content = await self._store.read(key, max_bytes=address.size_bytes)
        if (
            len(content) != address.size_bytes
            or "sha256:" + sha256(content).hexdigest() != address.content_digest
        ):
            raise ValueError("custody bytes do not match registered version")
        return content
