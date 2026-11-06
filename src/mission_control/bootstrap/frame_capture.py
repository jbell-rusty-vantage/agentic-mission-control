"""Composition of frame capture: the profile the deployment names and the promoter (1.4.4).

`MISSION_CONTROL_FRAME_CAPTURE_PROFILE` selects a `FrameCapturePolicy`; the artifact payload
store, when the deployment has one, becomes the `PayloadStoreFrameBodyPromoter`. The
`FrameCapture` built here carries both to the writer sites composition wires (the Deep Agents
adapter passes them as `FrameWriter(..., capture=, promoter=)`); a manifest or
`provider_options` never chooses capture behaviour. An unknown profile name is a configuration
error at composition, not a silent fallback.
"""

from __future__ import annotations

from mission_control.adapters.storage.frame_body_promoter import PayloadStoreFrameBodyPromoter
from mission_control.application.artifacts.artifact_promotion import ArtifactPayloadPort
from mission_control.application.frames.capture_policy import (
    CAPTURE_PROFILES,
    FrameCapture,
    capture_profile,
)
from mission_control.bootstrap.settings import IntegrationConfigurationError, Settings


def compose_frame_capture(settings: Settings, payloads: ArtifactPayloadPort | None) -> FrameCapture:
    """The capture policy and promoter for this deployment's writer sites."""

    name = settings.mission_control_frame_capture_profile
    try:
        policy = capture_profile(name)
    except ValueError as error:
        known = ", ".join(sorted(CAPTURE_PROFILES))
        raise IntegrationConfigurationError(
            f"MISSION_CONTROL_FRAME_CAPTURE_PROFILE={name!r} is not a capture profile; "
            f"known profiles: {known}"
        ) from error
    promoter = PayloadStoreFrameBodyPromoter(payloads) if payloads is not None else None
    return FrameCapture(policy=policy, promoter=promoter)


__all__ = ["compose_frame_capture"]
