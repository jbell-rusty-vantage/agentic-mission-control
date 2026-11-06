"""Capture-origin allowlist supplied by trusted composition, never request-body JSON."""

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime

from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadAddress
from mission_control.application.frames.artifact_bodies import ArtifactPayloadReader
from mission_control.application.recovery.terminal_evidence_capture import (
    MAX_CAPTURE_BYTES,
    MAX_RESULT_BYTES,
    RetainedTerminalCapture,
    capture_digest,
    validate_capture,
)
from mission_control.application.recovery.terminal_lane_adoption import (
    AdoptionIdentity,
    AdoptionInspectionRefused,
)


@dataclass(frozen=True)
class ApprovedTerminalCapture:
    identity: AdoptionIdentity
    manifest: ArtifactPayloadAddress
    result: ArtifactPayloadAddress


class ApprovedTerminalCaptureReader:
    def __init__(
        self, payloads: ArtifactPayloadReader, approved: Mapping[str, ApprovedTerminalCapture]
    ) -> None:
        self._payloads, self._approved = payloads, dict(approved)

    async def load_verified(
        self, identity: AdoptionIdentity, reference: str
    ) -> RetainedTerminalCapture:
        pin = self._approved.get(reference)
        if pin is None or pin.identity != identity:
            raise AdoptionInspectionRefused("capture origin is not approved for this identity")
        if not (
            0 < pin.manifest.size_bytes <= MAX_CAPTURE_BYTES
            and 0 < pin.result.size_bytes <= MAX_RESULT_BYTES
        ):
            raise AdoptionInspectionRefused("approved capture exceeds its read bound")
        manifest = await self._payloads.retrieve(pin.manifest)
        result = await self._payloads.retrieve(pin.result)
        if len(manifest) != pin.manifest.size_bytes or len(result) != pin.result.size_bytes:
            raise AdoptionInspectionRefused("approved capture size differs")
        if capture_digest(result) != pin.result.content_digest:
            raise AdoptionInspectionRefused("approved retained response digest differs")
        retained = RetainedTerminalCapture(manifest, result)
        validate_capture(retained, identity, pin.manifest.content_digest)
        return retained


@dataclass(frozen=True)
class ApprovedR1Capture:
    """Trusted operator pin, including separately verified native-source metadata.

    R1 deliberately retained only the total. Enrichment requires the independently
    pinned native receipt, never inferred counters or a current pricing estimate.
    """

    identity: AdoptionIdentity
    manifest: ArtifactPayloadAddress
    result: ArtifactPayloadAddress
    native_usage: Mapping[str, int]
    source_sha256: Mapping[str, str]
    source_evidence_digest: str
    observed_at: datetime
    native_finished_at: datetime


class ApprovedR1CaptureReader:
    def __init__(
        self, payloads: ArtifactPayloadReader, approved: Mapping[str, ApprovedR1Capture]
    ) -> None:
        self._payloads, self._approved = payloads, dict(approved)

    async def load_verified(
        self, identity: AdoptionIdentity, reference: str
    ) -> RetainedTerminalCapture:
        pin = self._approved.get(reference)
        if pin is None or pin.identity != identity:
            raise AdoptionInspectionRefused("R1 capture origin is not approved")
        if not (
            0 < pin.manifest.size_bytes <= MAX_CAPTURE_BYTES
            and 0 < pin.result.size_bytes <= MAX_RESULT_BYTES
        ):
            raise AdoptionInspectionRefused("R1 capture size bound")
        raw = await self._payloads.retrieve(pin.manifest)
        result = await self._payloads.retrieve(pin.result)
        if (
            capture_digest(raw) != pin.manifest.content_digest
            or len(raw) != pin.manifest.size_bytes
            or capture_digest(result) != pin.result.content_digest
            or len(result) != pin.result.size_bytes
        ):
            raise AdoptionInspectionRefused("R1 private custody bytes differ")
        old = json.loads(raw)
        expected = {
            "schema": "mc.r1.private-local-custody.v1",
            "public_run": identity.public_run_key,
            "internal_run": identity.internal_run_id,
            "native_agent": identity.native_session_ref,
            "native_run": identity.native_turn_ref,
            "native_status": "FINISHED",
            "total_tokens": pin.native_usage.get("totalTokens"),
            "result_bytes": len(result),
            "result_sha256": pin.result.content_digest.removeprefix("sha256:"),
            "source_sha256": dict(pin.source_sha256),
            "original_sqlite_opened": False,
            "private_local_only": True,
            "runtime_artifact_registered": False,
            "settlement_proven": False,
        }
        if (
            old != expected
            or type(old.get("total_tokens")) is not int
            or type(old.get("result_bytes")) is not int
            or set(pin.source_sha256) != {"index.db", "index.db-wal", "index.db-shm"}
            or any(
                re.fullmatch(r"[0-9a-f]{64}", value) is None for value in pin.source_sha256.values()
            )
        ):
            raise AdoptionInspectionRefused(
                "R1 identity or approved native-source attestation differs"
            )
        manifest = json.dumps(
            {
                "schema_version": "mc.terminal_lane_capture.v1",
                "identity": asdict(identity),
                "native_status": "FINISHED",
                "result_digest": pin.result.content_digest,
                "result_size": len(result),
                "usage": dict(pin.native_usage),
                "cost_micros_usd": None,
                "observed_at": pin.observed_at.isoformat(),
                "native_finished_at": pin.native_finished_at.isoformat(),
                "source_evidence_digest": pin.source_evidence_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        retained = RetainedTerminalCapture(manifest, result)
        validate_capture(retained, identity, capture_digest(manifest))
        return retained
