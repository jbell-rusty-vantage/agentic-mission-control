"""Normalized external evidence; the worker supplies identity and verified provenance.

The future inbox drainer may use these envelopes after resolving a delivery to an
admitted execution. Payload fields never select a run, generation or trust tier.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from mission_control.application.frames.writer import FrameWriter
from mission_control.domain.frames.contracts import FrameKind, FrameObservation
from mission_control.domain.programs.watchers import Observation


class SourceSignal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Literal["github", "cursor", "worker"]
    signal_type: str = Field(pattern=r"^[a-z][a-z0-9_.]*$", max_length=240)
    delivery_id: str = Field(min_length=1, max_length=512)
    observed_at: AwareDatetime
    data: dict[str, Any]

    def frame(self) -> FrameObservation:
        # Deliberately non-closing: evidence cannot settle lifecycle or usage.
        return FrameObservation(
            provider_key=f"source:{self.source}:{self.delivery_id}",
            raw_kind=f"signal.{self.signal_type}",
            kind=FrameKind.STATUS,
            observed_at=self.observed_at,
            body={"data": self.data, "trust_tier": "provider_signed"},
        )

    def observation(self) -> Observation:
        return Observation(
            source="signal",
            ref=f"source:{self.source}:{self.delivery_id}",
            types=(self.signal_type,),
            at=self.observed_at,
            data=self.data,
            trust="provider_signed",
        )


class TrustedSourceSink:
    """A worker-owned writer already bound to an admitted execution and generation.

    Only verified webhook/drainer or trusted poll/watch composition may call this.
    No public payload deserializer is an authentication boundary.
    """

    def __init__(self, writer: FrameWriter) -> None:
        self._writer = writer

    async def emit(self, signal: SourceSignal) -> None:
        await self._writer.write([signal.frame()])


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _scalars(document: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    return {
        key: document[key][:2048] if isinstance(document[key], str) else document[key]
        for key in keys
        if key in document and isinstance(document[key], str | int | bool | type(None))
    }


def github_signal(
    event: str, payload: Mapping[str, Any], *, delivery_id: str, observed_at: datetime
) -> SourceSignal:
    """Reduce a *verified* GitHub delivery/read to bounded condition fields."""
    action = payload.get("action")
    if event == "check_suite":
        suite = _object(payload.get("check_suite"))
        data = _scalars(suite, "id", "head_sha", "head_branch", "status", "conclusion")
        signal_type = (
            "github.check_suite.completed" if action == "completed" else "github.check_suite"
        )
    elif event == "pull_request":
        pull = _object(payload.get("pull_request"))
        data = _scalars(pull, "number", "state", "merged", "merge_commit_sha")
        data["head_branch"] = _scalars(_object(pull.get("head")), "ref").get("ref")
        signal_type = (
            "github.pull_request.merged"
            if action == "closed" and pull.get("merged") is True
            else "github.pull_request"
        )
    elif event == "push":
        data = _scalars(payload, "ref", "before", "after", "created", "deleted", "forced")
        signal_type = "github.push"
    else:
        raise ValueError("unsupported GitHub source event")
    repository = _object(payload.get("repository"))
    data.update(_scalars(repository, "full_name"))
    return SourceSignal(
        source="github",
        signal_type=signal_type,
        delivery_id=delivery_id,
        observed_at=observed_at,
        data=data,
    )


def cursor_status_signal(
    payload: Mapping[str, Any], *, delivery_id: str, observed_at: datetime
) -> SourceSignal:
    """Cursor v0 statusChange is advisory evidence, including FINISHED."""
    if payload.get("event") != "statusChange" or payload.get("status") not in {"FINISHED", "ERROR"}:
        raise ValueError("unsupported Cursor status event")
    if not isinstance(payload.get("id"), str) or not payload["id"]:
        raise ValueError("Cursor status requires a provider session id")
    return SourceSignal(
        source="cursor",
        signal_type="cursor.status_change",
        delivery_id=delivery_id,
        observed_at=observed_at,
        data=_scalars(payload, "id", "status", "timestamp"),
    )
