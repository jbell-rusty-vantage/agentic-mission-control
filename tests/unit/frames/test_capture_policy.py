"""1.4.4 (TR-D2a): capture profiles are a system lever chosen in composition."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from mission_control.application.frames.body_refs import (
    FrameBodyRef,
    MalformedFrameBodyRef,
    frame_body_ref,
    is_frame_body_ref,
    parse_frame_body_ref,
)
from mission_control.application.frames.capture_policy import (
    CAPTURE_PROFILES,
    DEFAULT_CAPTURE_PROFILE,
    FULL_REQUESTS_PROFILE,
    STANDARD_PROFILE,
    FrameCapture,
    FrameCapturePolicy,
    capture_profile,
)
from mission_control.bootstrap.frame_capture import compose_frame_capture
from mission_control.bootstrap.settings import IntegrationConfigurationError, Settings
from mission_control.domain.frames.contracts import FULL_BODY_KINDS, FrameKind

K = FrameKind
DIGEST = "sha256:" + "ab" * 32


def test_the_two_shipped_profiles() -> None:
    assert set(CAPTURE_PROFILES) == {"standard", "full_requests"}
    assert DEFAULT_CAPTURE_PROFILE == "standard"
    assert capture_profile("standard") is STANDARD_PROFILE
    assert capture_profile("full_requests") is FULL_REQUESTS_PROFILE
    assert STANDARD_PROFILE.promote_kinds == frozenset(
        {
            K.MODEL_REQUEST,
            K.TOOL_CALL_COMPLETED,
            K.TOOL_CALL_FAILED,
            K.MESSAGE,
            K.RUN_RESULT,
            K.ENVIRONMENT_MATERIALIZED,
            K.SUBAGENT_ENDED,
        }
    )
    assert STANDARD_PROFILE.promote_kinds <= FULL_BODY_KINDS
    assert STANDARD_PROFILE.excerpt_cap_bytes == 8192
    assert STANDARD_PROFILE.max_body_bytes == 2 * 1024 * 1024
    assert STANDARD_PROFILE.message_objects and not STANDARD_PROFILE.full_requests
    # `full_requests` is `standard` plus the whole batch of every model request.
    assert FULL_REQUESTS_PROFILE.full_requests and FULL_REQUESTS_PROFILE.message_objects
    assert FULL_REQUESTS_PROFILE.promote_kinds == STANDARD_PROFILE.promote_kinds
    assert FULL_REQUESTS_PROFILE.excerpt_cap_bytes == STANDARD_PROFILE.excerpt_cap_bytes
    with pytest.raises(FrozenInstanceError):
        STANDARD_PROFILE.full_requests = True  # type: ignore[misc]
    with pytest.raises(TypeError):
        CAPTURE_PROFILES["mine"] = STANDARD_PROFILE  # type: ignore[index]


def test_an_unknown_profile_is_refused_by_name_and_at_composition() -> None:
    with pytest.raises(ValueError, match="unknown frame capture profile 'verbose'"):
        capture_profile("verbose")
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, mission_control_frame_capture_profile="verbose"
    )
    with pytest.raises(IntegrationConfigurationError, match="FRAME_CAPTURE_PROFILE"):
        compose_frame_capture(settings, None)


def test_composition_hands_the_policy_and_the_promoter_to_writer_sites() -> None:
    default = compose_frame_capture(Settings(_env_file=None), None)  # type: ignore[call-arg]
    assert default == FrameCapture(policy=STANDARD_PROFILE, promoter=None)

    class Payloads:
        async def stage(self, **kwargs: object) -> object:
            raise NotImplementedError

        async def retrieve(self, address: object) -> bytes:
            raise NotImplementedError

    full = compose_frame_capture(
        Settings(_env_file=None, mission_control_frame_capture_profile="full_requests"),  # type: ignore[call-arg]
        Payloads(),
    )
    assert full.policy is FULL_REQUESTS_PROFILE and full.promoter is not None


def test_eligibility_is_the_oversized_promotion_rule() -> None:
    policy = STANDARD_PROFILE
    assert policy.eligible(K.TOOL_CALL_COMPLETED, 9_000, 8192)
    assert policy.eligible(K.SUBAGENT_ENDED, 9_000, 8192)
    assert not policy.eligible(K.TOOL_CALL_COMPLETED, 8192, 8192), "at the cap stays inline"
    assert not policy.eligible(K.TOOL_CALL_COMPLETED, policy.max_body_bytes + 1, 8192)
    assert not policy.eligible(K.MESSAGE_DELTA, 9_000, 8192), "deltas never promote"
    assert not policy.eligible(K.SUBAGENT_STARTED, 9_000, 8192), "not a full-body kind"
    everything = FrameCapturePolicy(
        name="everything",
        excerpt_cap_bytes=1,
        promote_kinds=frozenset(FrameKind),
        max_body_bytes=10,
        full_requests=True,
        message_objects=True,
    )
    assert not everything.eligible(K.TOOL_CALL_DELTA, 5, 1), "FULL_BODY_KINDS still bounds it"
    assert everything.eligible(K.RUN_RESULT, 5, 1)
    with pytest.raises(ValueError):
        FrameCapturePolicy(
            name="",
            excerpt_cap_bytes=1,
            promote_kinds=frozenset(),
            max_body_bytes=1,
            full_requests=False,
            message_objects=False,
        )


def test_frame_body_references_render_and_parse() -> None:
    ref = frame_body_ref(
        digest=DIGEST,
        size_bytes=1234,
        media_type="application/json; charset=utf-8",
    )
    head = "frame-body://sha256:" + "ab" * 32 + "?bytes=1234&type=application%2Fjson"
    assert ref.startswith(head) and "ref=" not in ref
    assert is_frame_body_ref(ref) and not is_frame_body_ref("artifact:abc")
    parsed = parse_frame_body_ref(ref)
    assert parsed == FrameBodyRef(
        digest=DIGEST,
        bytes=1234,
        media_type="application/json; charset=utf-8",
    )
    assert parsed.render() == ref and parsed.hex_digest == "ab" * 32
    # Tracing Stage 3 (R4-F6): a legacy `ref=` locator is ignored on parse.
    legacy = parse_frame_body_ref(
        f"frame-body://{DIGEST}?bytes=3&type=text%2Fplain&ref=s3%3A%2F%2Fb"
    )
    assert legacy == FrameBodyRef(digest=DIGEST, bytes=3, media_type="text/plain")
    for bad in (
        "artifact://scope/run/id",
        "frame-body://sha256:zz?bytes=1&type=text/plain",
        f"frame-body://{DIGEST}",
        f"frame-body://{DIGEST}?type=text/plain",
        f"frame-body://{DIGEST}?bytes=x&type=text/plain",
        f"frame-body://{DIGEST}?bytes=1",
    ):
        with pytest.raises(MalformedFrameBodyRef):
            parse_frame_body_ref(bad)
    with pytest.raises(MalformedFrameBodyRef):
        frame_body_ref(digest="sha256:short", size_bytes=1, media_type="text/plain")
