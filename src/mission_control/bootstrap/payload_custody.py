"""Verify split-host payload identity before any worker or API dispatch."""

from __future__ import annotations

from pathlib import Path

from mission_control.bootstrap.settings import Settings

MARKER = ".mission-control-payload-root"


def verify_payload_custody(settings: Settings, root: Path) -> None:
    if not settings.mission_control_split_host or settings.s3_bucket:
        return
    expected = settings.mission_control_payload_shared_id
    if not expected or not expected.strip():
        raise ValueError("split-host filesystem custody requires an explicit shared marker or S3")
    try:
        marker = root / MARKER
        if marker.is_symlink() or marker.stat().st_size > 1024:
            raise ValueError("payload root marker is invalid")
        observed = marker.read_text(encoding="utf-8").strip()
    except OSError:
        raise ValueError("split-host payload root marker is unavailable; configure S3") from None
    if observed != expected:
        raise ValueError("split-host payload root marker differs; configure S3")
