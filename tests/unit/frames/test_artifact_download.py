"""1.4.4 (tracing Stage 1, TR-D3): `GET runs/{id}/artifacts/{ref}` and `read_bytes`.

The route streams the verified bytes of a `frame-body://` or `artifact://` reference under
`workflow.result.read`: the media type comes from the reference, the length and digest
travel as headers, `403` without the grant, `404` for a reference that does not resolve,
`413` over the full-body cap, `501` without a composed payload store. The CLI encodes the
reference into the path (`quote(ref, safe="")`), so the tests send it that way.

Tracing Stage 3 (R4-F6): the route binds the reference to the path's run. A frame body is
served only when a frame of that run (in the caller's scope) references its digest, with the
size and media type of that frame row; an unknown run, a digest the run does not reference
and an artifact of another run are `404`; the response is an attachment with `nosniff`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mission_control.adapters.storage.artifact_payloads import InMemoryArtifactPayloadStore
from mission_control.application.artifacts.artifact_promotion import artifact_durable_reference
from mission_control.application.frames.artifact_bodies import (
    ArtifactBodyDenied,
    ArtifactBodyMissing,
    ArtifactBodyTooLarge,
    FrameBodyRecord,
    GrantedArtifactBodyReader,
)
from mission_control.application.frames.body_refs import frame_body_ref
from mission_control.application.installations.registry import (
    ApplicationBinding,
    ApplicationRegistry,
    InstallationObservation,
)
from mission_control.domain.execution.contracts import (
    ArtifactMetadataRevision,
    ArtifactPromotionState,
    WorkspaceOwner,
    WorkspaceOwnerKind,
)
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.http.artifacts import DIGEST_HEADER, router
from mission_control.interfaces.http.mission_control import MissionPrincipal, get_mission_principal
from tests.fixtures.provider_frames import FIXTURE_RUN, INSTALLATION, SCOPE, TENANT

RUN = str(FIXTURE_RUN)
READ = frozenset({"workflow_run.read"})
FULL = READ | {"workflow.result.read"}
ACTOR = ActorContext(actor_id="operator", permissions=FULL)
BODY = b'{"content":"a promoted tool result","type":"tool"}'
DIGEST = "sha256:" + sha256(BODY).hexdigest()
REPORT = b"# report\n\nthe durable artifact body\n"
REPORT_DIGEST = "sha256:" + sha256(REPORT).hexdigest()
ARTIFACT_ID = "artifact-report-1"
BASE = f"/v1/applications/biotech/runs/{RUN}/artifacts/"


def revision(**overrides: Any) -> ArtifactMetadataRevision:
    values: dict[str, Any] = {
        "promotion_id": "promotion-1",
        "artifact_id": ARTIFACT_ID,
        "intent_key": "intent-1",
        "promotion_identity": "sha256:" + "a" * 64,
        "revision": 1,
        "state": ArtifactPromotionState.ADMITTED,
        "request_scope": SCOPE,
        "run_id": RUN,
        "semantic_attempt_key": "attempt-1",
        "producer_binding_id": "binding-1",
        "namespace_id": "ns-1",
        "workspace_id": "ws-1",
        "output_slot": "report",
        "logical_path": "report.md",
        "owner": WorkspaceOwner(kind=WorkspaceOwnerKind.RUN, owner_id=RUN),
        "candidate_id": "candidate-1",
        "content_digest": REPORT_DIGEST,
        "media_type": "text/markdown",
        "size_bytes": len(REPORT),
        "permission_ref": "permission-1",
        "permission_outcome": "allowed",
        "output_contract_ref": "contract-1",
        "object_ref": "memory://artifacts/" + REPORT_DIGEST.removeprefix("sha256:"),
        "recorded_at": datetime(2026, 10, 21, tzinfo=UTC),
    }
    values.update(overrides)
    return ArtifactMetadataRevision.model_validate(values)


class Metadata:
    def __init__(self, item: ArtifactMetadataRevision | None) -> None:
        self.item = item

    async def get_by_artifact(self, artifact_id: str) -> ArtifactMetadataRevision | None:
        return self.item if self.item is not None and self.item.artifact_id == artifact_id else None


class FrameIndex:
    """`FrameBodyIndex`: the digests each (scope, run) references, with the row's facts."""

    def __init__(self, bodies: dict[tuple[str, str, str], FrameBodyRecord] | None = None) -> None:
        self.bodies = (
            bodies
            if bodies is not None
            else {(SCOPE, RUN, DIGEST): FrameBodyRecord(len(BODY), "application/json")}
        )
        self.seen: list[tuple[str, str, str]] = []

    async def run_frame_body(
        self, request_scope: str, run_key: str, digest: str
    ) -> FrameBodyRecord | None:
        self.seen.append((request_scope, run_key, digest))
        return self.bodies.get((request_scope, run_key, digest))


def granted(
    payloads: InMemoryArtifactPayloadStore,
    *,
    frames: FrameIndex | None = None,
    max_bytes: int | None = None,
) -> GrantedArtifactBodyReader:
    extra: dict[str, Any] = {"max_bytes": max_bytes} if max_bytes is not None else {}
    return GrantedArtifactBodyReader(
        Metadata(revision()),
        payloads,
        request_scope=SCOPE,
        frames=frames if frames is not None else FrameIndex(),
        **extra,
    )


async def payload_store() -> InMemoryArtifactPayloadStore:
    payloads = InMemoryArtifactPayloadStore()
    await payloads.stage(
        artifact_id="frame-body", content=BODY, content_digest=DIGEST, media_type="application/json"
    )
    await payloads.stage(
        artifact_id=ARTIFACT_ID,
        content=REPORT,
        content_digest=REPORT_DIGEST,
        media_type="text/markdown",
    )
    return payloads


FRAME_REF = frame_body_ref(digest=DIGEST, size_bytes=len(BODY), media_type="application/json")
DURABLE_REF = artifact_durable_reference(SCOPE, RUN, ARTIFACT_ID)


def http_app(
    reader: GrantedArtifactBodyReader | None, permissions: frozenset[str] = FULL
) -> FastAPI:
    registry = ApplicationRegistry(
        (
            ApplicationBinding.seal(
                application_id="biotech",
                installation_id=INSTALLATION,
                binding_version="1",
                supabase_project_ref="project",
                database_secret_ref="TEST_DATABASE_URL",
                accepted_issuers={"https://issuer.invalid"},
                accepted_audiences={"authenticated"},
                required_component_version="1",
            ),
        )
    )
    registry.observe(
        "biotech", InstallationObservation(INSTALLATION, "biotech", "project", frozenset({"1"}))
    )
    app = FastAPI()
    app.include_router(router)
    app.state.mission_control_registry = registry
    app.state.mission_control_artifact_body_readers = (
        {(INSTALLATION, "biotech", TENANT): reader} if reader is not None else {}
    )
    app.dependency_overrides[get_mission_principal] = lambda: MissionPrincipal(
        installation_id=INSTALLATION,
        application_id="biotech",
        tenant_id=TENANT,
        issuer="https://issuer.invalid",
        audiences=frozenset({"authenticated"}),
        actor=ActorContext(actor_id="reader", permissions=permissions),
    )
    return app


@pytest.mark.asyncio
async def test_read_bytes_serves_both_families_with_their_media_types() -> None:
    reader = GrantedArtifactBodyReader(
        Metadata(revision()), await payload_store(), request_scope=SCOPE
    )
    assert await reader.read_bytes(SCOPE, ACTOR, FRAME_REF) == (BODY, "application/json")
    assert await reader.read_bytes(SCOPE, ACTOR, DURABLE_REF) == (REPORT, "text/markdown")
    assert await reader.read(SCOPE, ACTOR, DURABLE_REF) == REPORT.decode()
    with pytest.raises(ArtifactBodyDenied):
        await reader.read_bytes(SCOPE, ActorContext(actor_id="viewer", permissions=READ), FRAME_REF)
    with pytest.raises(ArtifactBodyMissing):
        await reader.read_bytes(
            SCOPE,
            ACTOR,
            frame_body_ref(digest="sha256:" + "0" * 64, size_bytes=3, media_type="text/plain"),
        )
    capped = GrantedArtifactBodyReader(
        Metadata(revision()), await payload_store(), request_scope=SCOPE, max_bytes=8
    )
    with pytest.raises(ArtifactBodyTooLarge):
        await capped.read_bytes(SCOPE, ACTOR, FRAME_REF)
    with pytest.raises(ArtifactBodyTooLarge):
        await capped.read_bytes(SCOPE, ACTOR, DURABLE_REF)


@pytest.mark.asyncio
async def test_http_download_streams_verified_bytes_with_the_media_type() -> None:
    reader = granted(await payload_store())
    client = TestClient(http_app(reader))
    response = client.get(BASE + quote(FRAME_REF, safe=""))
    assert response.status_code == 200, response.text
    assert response.content == BODY
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-length"] == str(len(BODY))
    assert response.headers[DIGEST_HEADER] == DIGEST
    assert response.headers["content-disposition"] == "attachment"
    assert response.headers["x-content-type-options"] == "nosniff"
    durable = client.get(BASE + quote(DURABLE_REF, safe=""))
    assert durable.status_code == 200, durable.text
    assert durable.content == REPORT
    assert durable.headers["content-type"].startswith("text/markdown")
    assert durable.headers[DIGEST_HEADER] == REPORT_DIGEST


@pytest.mark.asyncio
async def test_http_download_refuses_denies_and_caps() -> None:
    payloads = await payload_store()
    reader = granted(payloads)
    client = TestClient(http_app(reader))
    unknown = frame_body_ref(digest="sha256:" + "0" * 64, size_bytes=3, media_type="text/plain")
    assert client.get(BASE + quote(unknown, safe="")).status_code == 404
    assert client.get(BASE + quote("artifact:absent", safe="")).status_code == 404
    assert client.get(BASE + quote("not-a-reference", safe="")).status_code == 404
    other_run = artifact_durable_reference(SCOPE, "another-run", ARTIFACT_ID)
    assert client.get(BASE + quote(other_run, safe="")).status_code == 404

    viewer = TestClient(http_app(reader, READ))
    denied = viewer.get(BASE + quote(FRAME_REF, safe=""))
    assert denied.status_code == 403
    assert denied.json()["detail"]["permission"] == "workflow.result.read"

    capped = granted(payloads, max_bytes=8)
    over = TestClient(http_app(capped)).get(BASE + quote(FRAME_REF, safe=""))
    assert over.status_code == 413 and over.json()["detail"]["code"] == "payload_too_large"

    absent = TestClient(http_app(None)).get(BASE + quote(FRAME_REF, safe=""))
    assert absent.status_code == 501
    assert absent.json()["detail"]["code"] == "artifact_download_unavailable"


@pytest.mark.asyncio
async def test_a_frame_body_is_served_only_to_a_run_whose_frames_reference_it() -> None:
    """R4-F6: content addressing is no authority. The body is in the (global) store, but
    another run, an unknown run or another tenant's run that references nothing gets 404."""

    payloads = await payload_store()
    index = FrameIndex()
    client = TestClient(http_app(granted(payloads, frames=index)))
    assert client.get(BASE + quote(FRAME_REF, safe="")).status_code == 200
    assert index.seen[-1] == (SCOPE, RUN, DIGEST)
    for other in ("another-run", "00000000-0000-0000-0000-000000000000"):
        path = f"/v1/applications/biotech/runs/{other}/artifacts/" + quote(FRAME_REF, safe="")
        missing = client.get(path)
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "artifact_unavailable"
    # The same digest referenced by a run of another tenant scope proves nothing here.
    foreign = FrameIndex({("other-scope", RUN, DIGEST): FrameBodyRecord(len(BODY), "text/plain")})
    other_tenant = TestClient(http_app(granted(payloads, frames=foreign)))
    assert other_tenant.get(BASE + quote(FRAME_REF, safe="")).status_code == 404


@pytest.mark.asyncio
async def test_the_frame_row_not_the_caller_sizes_and_labels_the_body() -> None:
    """R4-F6: `type=` and `bytes=` of the caller's reference are ignored; a legacy `ref=`
    locator is never used (the body is located by digest)."""

    client = TestClient(http_app(granted(await payload_store())))
    forged = f"frame-body://{DIGEST}?bytes=3&type=text%2Fhtml&ref=" + quote(
        "memory://artifacts/" + "0" * 64, safe=""
    )
    response = client.get(BASE + quote(forged, safe=""))
    assert response.status_code == 200, response.text
    assert response.content == BODY
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_run_bound_reads_need_the_index_and_bind_durable_artifacts() -> None:
    payloads = await payload_store()
    bare = GrantedArtifactBodyReader(Metadata(revision()), payloads, request_scope=SCOPE)
    # In-process callers (transcript `--full`, replay) still read their own rows' references.
    assert await bare.read_bytes(SCOPE, ACTOR, FRAME_REF) == (BODY, "application/json")
    with pytest.raises(ArtifactBodyMissing):
        await bare.read_bytes(SCOPE, ACTOR, FRAME_REF, run_id=RUN)
    reader = granted(payloads)
    assert await reader.read_bytes(SCOPE, ACTOR, DURABLE_REF, run_id=RUN) == (
        REPORT,
        "text/markdown",
    )
    # The short form names no run: the path's run decides, inside the reader.
    short = f"artifact:{ARTIFACT_ID}"
    assert (await reader.read_bytes(SCOPE, ACTOR, short, run_id=RUN))[0] == REPORT
    with pytest.raises(ArtifactBodyMissing):
        await reader.read_bytes(SCOPE, ACTOR, short, run_id="another-run")
    client = TestClient(http_app(reader))
    other = f"/v1/applications/biotech/runs/another-run/artifacts/{quote(short, safe='')}"
    assert client.get(other).status_code == 404


def test_cli_run_artifact_writes_the_bytes_and_prints_a_receipt(tmp_path: Any, capsys: Any) -> None:
    import argparse
    import json

    import httpx

    from mission_control.interfaces.cli import main as cli

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path.decode())
        if request.url.raw_path.decode().endswith(quote(FRAME_REF, safe="")):
            return httpx.Response(200, content=BODY, headers={"content-type": "application/json"})
        return httpx.Response(404, json={"detail": {"code": "artifact_unavailable"}})

    transport = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://mc.test")
    client = cli.MissionClient(transport, "biotech")
    out = tmp_path / "body.json"
    status = cli.run_artifact(client, argparse.Namespace(run_id=RUN, ref=FRAME_REF, out=str(out)))
    assert status == 0 and out.read_bytes() == BODY
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["bytes"] == len(BODY) and receipt["digest"] == DIGEST
    assert receipt["media_type"] == "application/json" and receipt["ref"] == FRAME_REF
    # The reference travelled percent-encoded as one path segment.
    assert seen[0].endswith("/artifacts/" + quote(FRAME_REF, safe=""))
    missing = tmp_path / "missing.json"
    status = cli.run_artifact(
        client, argparse.Namespace(run_id=RUN, ref="artifact:absent", out=str(missing))
    )
    assert status == 2 and not missing.exists()
