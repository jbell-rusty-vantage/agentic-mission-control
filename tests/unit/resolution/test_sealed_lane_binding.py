"""OC-R2 review fixes: the sealed lane binding at request validation and at decode.

- Pairing at validation (`_verify_lane_pairing`): the profile's lane must serve the runtime and
  the sealed bytes must carry a schema that lane produces.
- The sealed payload is bounded by construction: the shared run-control scan (secret key
  names, structural limits) and an explicit byte ceiling.
- A lane's `carried_by` refuses a `lane_dispatch` its sealed binding does not state.
- OC-R7 S1: a run-control contract walks a binding's envelope in place of its payload only when
  the payload is the bytes its digest names, and scans those bytes decoded; a dict that merely
  mimics the envelope is scanned as data.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

import pytest
from pydantic import ValidationError

from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.contracts import OperationExecutionRequest
from mission_control.domain.execution.lanes import CursorExecutionBinding
from mission_control.domain.policies.contracts import Contract
from mission_control.domain.resolution.sealed import MAX_SEALED_PAYLOAD_BYTES, SealedLaneBinding
from tests.fixtures.lane_turns import cursor_binding, cursor_operation
from tests.unit.claude.fixtures import claude_operation
from tests.unit.operations.test_operation_execution import operation_request


def _payload(**changes: Any) -> dict[str, Any]:
    payload = operation_request().model_dump(mode="python")
    payload.update(changes)
    return payload


def _sealed(document: object, *, profile: str = "cursor_local") -> SealedLaneBinding:
    return SealedLaneBinding.seal(
        lane_profile=profile,
        schema_id="mc.cursor_binding.v2",
        payload=json.dumps(document).encode("utf-8"),
    )


# --- Item 1: pairing at request validation ------------------------------------------------


def test_a_claude_runtime_on_a_cursor_profile_is_refused_at_validation() -> None:
    cursor = cursor_operation()
    with pytest.raises(ValidationError, match="cursor_local does not serve a claude runtime"):
        OperationExecutionRequest.model_validate(
            {**cursor.model_dump(mode="python"), "execution_runtime": "claude"}
        )


def test_a_native_runtime_on_another_lane_profile_is_refused_at_validation() -> None:
    with pytest.raises(ValidationError, match="codex does not serve a native runtime"):
        OperationExecutionRequest.model_validate(_payload(lane_profile="codex"))


def test_a_sealed_binding_of_another_lanes_schema_is_refused_at_validation() -> None:
    cursor = cursor_operation()
    assert cursor.lane_binding is not None
    foreign = SealedLaneBinding.seal(
        lane_profile="cursor_local",
        schema_id="mc.execution_binding.v2",
        payload=cursor.lane_binding.payload,
    )
    with pytest.raises(ValidationError, match="cannot carry the mc.execution_binding.v2 schema"):
        OperationExecutionRequest.model_validate(
            {**cursor.model_dump(mode="python"), "lane_binding": foreign}
        )


def test_the_well_paired_requests_still_validate() -> None:
    assert cursor_operation().lane_binding is not None
    assert claude_operation().lane_binding is not None


# --- Item 3: the sealed payload is bounded by construction --------------------------------


@pytest.mark.parametrize("key", ["api_key", "authorization", "github_access_token", "Password"])
def test_a_secret_named_key_inside_a_sealed_payload_is_refused(key: str) -> None:
    with pytest.raises(ValidationError, match="raw secrets"):
        _sealed({"pins": {"sdk": "1"}, "nested": [{key: "x"}]})


def test_an_oversized_sealed_payload_is_refused() -> None:
    document = {"items": ["x" * 4_000] * (MAX_SEALED_PAYLOAD_BYTES // 4_000 + 1)}
    with pytest.raises(ValidationError, match=f"exceeds {MAX_SEALED_PAYLOAD_BYTES} bytes"):
        _sealed(document)


def test_a_sealed_payload_breaking_the_structural_limits_is_refused() -> None:
    with pytest.raises(ValidationError, match="8192 characters"):
        _sealed({"text": "x" * 8_193})
    with pytest.raises(ValidationError, match="signed 64-bit"):
        _sealed({"count": 2**64})


def test_a_real_lane_binding_passes_the_scan() -> None:
    binding = cursor_binding()
    assert SealedLaneBinding.model_validate(binding.seal().model_dump(mode="json")) == (
        binding.seal()
    )


# --- OC-R7 S1: a nested envelope is skipped only when its bytes are verified -------------


class _Carrier(Contract):
    """Any run-control contract with a free-form field a binding-shaped dict can sit in."""

    data: dict[str, Any]


def _envelope(document: object, *, digest: str | None = None) -> dict[str, str]:
    payload = json.dumps(document).encode("utf-8")
    return {
        "lane_profile": "cursor_local",
        "schema_id": "mc.cursor_binding.v2",
        "digest": digest or "sha256:" + hashlib.sha256(payload).hexdigest(),
        "payload": base64.b64encode(payload).decode("ascii"),
    }


def test_a_genuine_nested_envelope_is_walked_in_place_of_its_payload() -> None:
    # The base64 form is longer than a run-control string may be; the verified bytes are not.
    envelope = _envelope({"items": ["x" * 4_000, "y" * 4_000]})
    assert len(envelope["payload"]) > 8_192
    assert _Carrier(data={"nested": [envelope]}).data["nested"][0] == envelope
    assert _Carrier(data={"binding": cursor_binding().seal().model_dump(mode="json")})


def test_a_forged_envelope_whose_digest_does_not_bind_its_payload_is_scanned_as_data() -> None:
    forged = _envelope({"items": ["x" * 4_000, "y" * 4_000]}, digest="sha256:" + "0" * 64)
    with pytest.raises(ValidationError, match="8192 characters"):
        _Carrier(data={"nested": {"deeper": [forged]}})
    undecodable = {**_envelope({"a": 1}), "payload": "not base64!" * 1_000}
    with pytest.raises(ValidationError, match="8192 characters"):
        _Carrier(data={"nested": undecodable})


@pytest.mark.parametrize("key", ["api_key", "phi", "raw_output"])
def test_a_digest_matching_envelope_is_scanned_decoded(key: str) -> None:
    # Computing a matching digest does not hide a payload the shared scan would refuse.
    forged = _envelope({"pins": {"sdk": "1"}, "nested": [{key: "x"}]})
    with pytest.raises(ValidationError, match="raw secrets"):
        _Carrier(data={"nested": [forged]})
    with pytest.raises(ValidationError, match="8192 characters"):
        _Carrier(data={"nested": _envelope({"text": "x" * 8_193})})


# --- Item 5: carried_by refuses a dispatch the sealed binding does not state --------------


def test_cursor_carried_by_refuses_a_dispatch_the_binding_does_not_state() -> None:
    cursor = cursor_operation()
    assert CursorExecutionBinding.carried_by(cursor) is not None
    dispatch = cursor.lane_dispatch
    assert dispatch is not None
    for drift in ({"task_queue": "another-queue"}, {"wall_clock_s": 7}):
        drifted = cursor.model_copy(update={"lane_dispatch": dispatch.model_copy(update=drift)})
        with pytest.raises(ValueError, match="lane dispatch differs"):
            CursorExecutionBinding.carried_by(drifted)
    later = cursor.model_copy(
        update={"lane_dispatch": dispatch.model_copy(update={"execution_generation": 3})}
    )
    # The generation is the attempt's (the families advance it); the lane states the rest.
    assert CursorExecutionBinding.carried_by(later) is not None


def test_provider_carried_by_refuses_a_dispatch_the_binding_does_not_state() -> None:
    claude = claude_operation()
    assert ProviderExecutionBinding.carried_by(claude) is not None
    dispatch = claude.lane_dispatch
    assert dispatch is not None
    for drift in (
        {"task_queue": "another-queue"},
        {"wall_clock_s": 7},
        {"heartbeat_class": "deep_agent"},
    ):
        drifted = claude.model_copy(update={"lane_dispatch": dispatch.model_copy(update=drift)})
        with pytest.raises(ValueError, match="lane dispatch differs"):
            ProviderExecutionBinding.carried_by(drifted)
