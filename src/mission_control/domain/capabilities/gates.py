"""Declared synchronous tool gates; unsupported native enforcement fails at projection."""

from pydantic import BaseModel, ConfigDict, model_validator

from mission_control.domain.capabilities.hooks import HookEvent


class SignalGatePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    events: tuple[HookEvent, ...] = (HookEvent.BEFORE_TOOL,)
    fail_closed: bool = True

    @model_validator(mode="after")
    def permission_events_only(self) -> "SignalGatePolicy":
        allowed = {HookEvent.BEFORE_TOOL, HookEvent.BEFORE_SHELL, HookEvent.BEFORE_MCP}
        if (
            not self.events
            or len(set(self.events)) != len(self.events)
            or set(self.events) - allowed
        ):
            raise ValueError(
                "signal gates require distinct before_tool, before_shell or before_mcp events"
            )
        return self
