"""A mission's watchers: ``controls.watchers``, ``controls.notifications`` and ``event_wait``
compiled into watcher descriptors (SPEC-04 §5, ADR-0046).

Three sources become one ordered tuple of :class:`WatcherDescriptor` on the mission definition:

1. ``controls.watchers`` (``mission/v2``): inline bodies compile here; a ``pin`` names a
   published ``mc.watcher.v1`` template, which the compile service resolves through the
   catalog and passes back in as ``resolved``.
2. ``controls.notifications`` (``mission/v2``): sugar for notify-only watchers. Each ``on``
   entry is a public event type (``run.completed``) or a significance kind (``blocked``,
   expanded to its event set); the only channel is the coordinator ``inbox``. In
   ``mission/v1`` the field stays unconsumed and compile warns.
3. Every ``event_wait`` stage: an implied watcher whose ``match`` becomes its condition and
   whose one action satisfies the stage's declared wait, so an event, not an operator,
   releases it.

Pure: no catalog access and no persistence. Issues carry manifest pointers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal

from pydantic import Field, field_validator

from mission_control.domain.authoring.manifest import (
    EVENT_TYPE_PATTERN,
    Behavior,
    Controls,
    EventWaitNode,
    ManifestErrorCode,
    ManifestIssue,
    ManifestModel,
    MissionBlock,
    StageGraphNode,
    SubscriptionDeclaration,
    WebhookChannel,
)
from mission_control.domain.programs.watcher_conditions import ConditionValue, WatcherCondition
from mission_control.domain.programs.watchers import (
    MAX_DEPTH,
    MAX_WATCHERS,
    USAGE_DIMENSIONS,
    SatisfyWaitAction,
    WatcherActionSpec,
    WatcherBoundaries,
    WatcherDeclaration,
    WatcherDescriptor,
    WatcherSpec,
    WatcherTrigger,
    compile_watcher,
)
from mission_control.domain.subscriptions.significance import KIND_EVENTS, kind_of_event

NOTIFICATIONS_PREFIX: Final = "notifications"
EVENT_WAIT_PREFIX: Final = "event_wait"
_FIELD_NAME: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EVENT_TYPE: Final = re.compile(EVENT_TYPE_PATTERN)
# Sugar mirrors the inbox: it notifies every matching event; the inbox applies its own caps.
_SUGAR_LIMITS: Final = {"max_fires": 1000, "rate": "1000/h"}


class NotificationsDeclaration(ManifestModel):
    """``mission/v2`` ``controls.notifications``: notify-only watchers on public event types
    or significance kinds, delivered to the coordinator inbox."""

    on: tuple[str, ...] = Field(min_length=1, max_length=32)
    channel: Literal["inbox"] = "inbox"

    @field_validator("on")
    @classmethod
    def _event_or_kind(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for entry in value:
            if "." not in entry and entry not in KIND_EVENTS:
                raise ValueError(
                    f"notifications.on entry {entry!r} is neither an event type "
                    f"(such as run.completed) nor a kind ({', '.join(sorted(KIND_EVENTS))})"
                )
            if "." in entry and not _EVENT_TYPE.fullmatch(entry):
                raise ValueError(f"notifications.on entry {entry!r} is not an event type")
        if len(set(value)) != len(value):
            raise ValueError("notifications.on must not repeat an entry")
        return value


class SubscriptionDeclarationV2(SubscriptionDeclaration):
    """A ``mission/v2`` subscription: ``stream`` or a signed webhook. ``mcp`` was never
    delivered (no MCP session registers a manifest subscription), so v2 rejects it; agents
    wait on their coordinator inbox instead (ADR-0049)."""

    channel: Literal["stream"] | WebhookChannel


class ControlsV2(Controls):
    """``mission/v2`` controls: v1 controls plus watchers and consumed notifications."""

    subscriptions: tuple[SubscriptionDeclarationV2, ...] = ()
    notifications: NotificationsDeclaration | None = None  # type: ignore[assignment]
    # Left out of dumps while empty, so a v1 document read as v2 dumps identically.
    watchers: tuple[WatcherDeclaration, ...] = Field(
        default=(), max_length=MAX_WATCHERS, exclude_if=lambda value: not value
    )


@dataclass(frozen=True)
class PinnedWatcher:
    """A ``controls.watchers`` entry whose body is a published template."""

    index: int
    declaration: WatcherDeclaration
    pointer: str


@dataclass(frozen=True)
class MissionWatchers:
    descriptors: tuple[WatcherDescriptor, ...]
    pinned: tuple[PinnedWatcher, ...]
    blockers: tuple[ManifestIssue, ...]
    warnings: tuple[ManifestIssue, ...]


@dataclass(frozen=True)
class WatcherContext:
    """What a descriptor is checked against: the mission's waits, grants and budget."""

    pointer: str
    wait_nodes: frozenset[str]
    commands_allowed: frozenset[str] | None
    budget: Mapping[str, int]


def _issue(
    pointer: str,
    message: str,
    reason: str,
    code: ManifestErrorCode = ManifestErrorCode.INVALID_DEFINITION,
) -> ManifestIssue:
    return ManifestIssue(code=code, pointer=pointer, message=message, reason=reason)


def _stage_nodes(block: MissionBlock, pointer: str) -> Iterable[tuple[Any, str]]:
    """The nodes the lowering makes Stage Graph stages, with their pointers."""

    root = block.program
    if isinstance(root, StageGraphNode):
        for index, child in enumerate(root.nodes):
            yield child, f"{pointer}/program/nodes/{index}"
    elif root.behavior_name() != Behavior.GOAL_LOOP.value:
        yield root, f"{pointer}/program"


def _all_nodes(node: Any, node_pointer: str) -> Iterable[tuple[Any, str]]:
    yield node, node_pointer
    for index, child in enumerate(getattr(node, "nodes", ()) or ()):
        yield from _all_nodes(child, f"{node_pointer}/nodes/{index}")


def mission_budget(block: MissionBlock) -> dict[str, int]:
    """The mission's declared token and dollar budget as run-control usage dimensions."""

    budget = block.environment.budget
    dimensions: dict[str, int] = {}
    if budget is not None and budget.tokens is not None:
        dimensions[USAGE_DIMENSIONS["tokens"]] = budget.tokens
    if budget is not None and budget.usd is not None:
        dimensions[USAGE_DIMENSIONS["usd_micros"]] = int(
            (Decimal(budget.usd) * Decimal(1_000_000)).to_integral_value()
        )
    return dimensions


def watcher_context(block: MissionBlock, pointer: str) -> WatcherContext:
    controls = block.controls
    allowed = controls.commands_allowed if controls is not None else None
    return WatcherContext(
        pointer=pointer,
        wait_nodes=frozenset(
            node.key for node, _ in _stage_nodes(block, pointer) if isinstance(node, EventWaitNode)
        ),
        commands_allowed=frozenset(item.value for item in allowed) if allowed is not None else None,
        budget=mission_budget(block),
    )


def descriptor_issues(
    descriptor: WatcherDescriptor, context: WatcherContext
) -> list[ManifestIssue]:
    """Grant, wait and budget rules a descriptor must meet in its mission (SPEC-04 §5.2)."""

    issues: list[ManifestIssue] = []
    pointer = descriptor.pointer
    for index, action in enumerate(descriptor.actions):
        if action.satisfy_wait is not None and action.satisfy_wait.node not in context.wait_nodes:
            issues.append(
                _issue(
                    f"{pointer}/then/{index}/satisfy_wait/node",
                    f"satisfy_wait names {action.satisfy_wait.node}, which is not an event_wait "
                    "stage of this mission",
                    "unknown_wait",
                )
            )
        kind = action.command_kind
        # An event_wait node releasing its own declared wait needs no further grant.
        if (
            kind is not None
            and descriptor.origin != "event_wait"
            and context.commands_allowed is not None
            and kind not in context.commands_allowed
        ):
            issues.append(
                _issue(
                    f"{pointer}/then/{index}",
                    f"watcher {descriptor.watcher_id} issues {kind}, which controls."
                    "commands_allowed does not grant",
                    "action_not_granted",
                    ManifestErrorCode.AUTHORITY_DENIED,
                )
            )
    bounds = descriptor.boundaries
    for name, value in (
        (USAGE_DIMENSIONS["tokens"], bounds.budget_tokens),
        (USAGE_DIMENSIONS["usd_micros"], bounds.budget_usd_micros),
    ):
        ceiling = context.budget.get(name)
        if value is not None and ceiling is not None and value > ceiling:
            issues.append(
                _issue(
                    f"{pointer}/limits/budget",
                    f"watcher {descriptor.watcher_id} budget {name}={value} exceeds the "
                    f"mission budget {ceiling}",
                    "widens_authority",
                    ManifestErrorCode.BUDGET_EXHAUSTED,
                )
            )
    return issues


def _notification_descriptors(
    declaration: NotificationsDeclaration, pointer: str
) -> list[WatcherDescriptor]:
    descriptors: list[WatcherDescriptor] = []
    for index, entry in enumerate(declaration.on):
        pairs: list[tuple[str | None, str]] = (
            [(entry, event) for event in sorted(KIND_EVENTS[entry])]
            if entry in KIND_EVENTS
            else [(None, entry)]
        )
        for offset, (kind, event_type) in enumerate(pairs):
            notify_kind = kind or kind_of_event(event_type) or "progress"
            descriptors.append(
                compile_watcher(
                    WatcherSpec.model_validate(
                        {
                            "on": {"event": event_type},
                            "then": [{"notify": {"kind": notify_kind}}],
                            "limits": _SUGAR_LIMITS,
                        }
                    ),
                    watcher_id=f"{NOTIFICATIONS_PREFIX}:{index}:{offset}",
                    origin="notifications",
                    pointer=f"{pointer}/on/{index}",
                )
            )
    return descriptors


def _event_wait_descriptor(node: EventWaitNode, pointer: str) -> WatcherDescriptor:
    conditions = tuple(
        WatcherCondition(
            op="eq",
            values=(ConditionValue(kind="path", text=f"event.{key}"), _literal(value)),
        )
        for key, value in sorted(node.match.items())
    )
    where = (
        None
        if not conditions
        else conditions[0]
        if len(conditions) == 1
        else WatcherCondition(op="all", operands=conditions)
    )
    action = WatcherActionSpec(satisfy_wait=SatisfyWaitAction(node=node.key))
    return WatcherDescriptor(
        watcher_id=f"{EVENT_WAIT_PREFIX}:{node.key}",
        origin="event_wait",
        pointer=pointer,
        trigger=WatcherTrigger(kind="event", name=node.event_type),
        where=where,
        actions=(action,),
        boundaries=WatcherBoundaries(
            max_fires=1,
            rate_count=1,
            rate_window_seconds=1,
            max_depth=MAX_DEPTH,
            min_trust="environment_key",
        ),
    )


def _literal(value: Any) -> ConditionValue:
    if value is None:
        return ConditionValue(kind="null")
    if isinstance(value, bool):
        return ConditionValue(kind="boolean", flag=value)
    if isinstance(value, int | Decimal):
        return ConditionValue(kind="number", text=str(value))
    if isinstance(value, str):
        return ConditionValue(kind="string", text=value)
    raise ValueError("an event_wait match value is a string, number, boolean or null")


def _event_wait_watchers(
    block: MissionBlock, pointer: str, blockers: list[ManifestIssue], warnings: list[ManifestIssue]
) -> list[WatcherDescriptor]:
    stages = {id(node) for node, _ in _stage_nodes(block, pointer)}
    descriptors: list[WatcherDescriptor] = []
    for node, node_pointer in _all_nodes(block.program, f"{pointer}/program"):
        if not isinstance(node, EventWaitNode):
            continue
        if id(node) not in stages:
            warnings.append(
                _issue(
                    node_pointer,
                    f"event_wait {node.key} is not a Stage Graph stage; no watcher releases it",
                    "event_wait_not_a_stage",
                    ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                )
            )
            continue
        if node.mode != "once":
            blockers.append(
                _issue(
                    f"{node_pointer}/mode",
                    "event_wait rearm is not supported; declare a watcher instead",
                    "event_wait_rearm",
                    ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                )
            )
            continue
        if node.timeout is not None or node.on_timeout is not None:
            warnings.append(
                _issue(
                    f"{node_pointer}/timeout",
                    f"event_wait {node.key} timeout is not enforced; the wait holds until "
                    "its event arrives or an operator satisfies it",
                    "event_wait_timeout_unenforced",
                    ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                )
            )
        bad = [
            key for key, value in node.match.items() if not _is_field(key) or not _is_scalar(value)
        ]
        if bad:
            blockers.append(
                _issue(
                    f"{node_pointer}/match",
                    f"event_wait match keys are field names with scalar values: {sorted(bad)}",
                    "event_wait_match",
                )
            )
            continue
        descriptors.append(_event_wait_descriptor(node, node_pointer))
    return descriptors


def _is_field(key: str) -> bool:
    return _FIELD_NAME.fullmatch(key) is not None


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, bool | int | Decimal | str)


def compile_mission_watchers(
    block: MissionBlock,
    pointer: str,
    *,
    resolved: Mapping[int, WatcherDescriptor] | None = None,
) -> MissionWatchers:
    """Every watcher of one mission block, in order: declared (pinned ones only once
    ``resolved`` supplies them by entry index), then notifications, then ``event_wait``."""

    blockers: list[ManifestIssue] = []
    warnings: list[ManifestIssue] = []
    descriptors: list[WatcherDescriptor] = []
    pinned: list[PinnedWatcher] = []
    controls = block.controls
    controls_pointer = f"{pointer}/controls"
    context = watcher_context(block, pointer)
    if isinstance(controls, ControlsV2):
        for index, declaration in enumerate(controls.watchers):
            entry_pointer = f"{controls_pointer}/watchers/{index}"
            if declaration.pin is not None:
                pinned.append(PinnedWatcher(index, declaration, entry_pointer))
                if resolved is not None and index in resolved:
                    descriptors.append(resolved[index])
                continue
            descriptors.append(
                compile_watcher(
                    declaration.spec(),
                    watcher_id=declaration.id,
                    origin="manifest",
                    pointer=entry_pointer,
                )
            )
        if controls.notifications is not None:
            descriptors.extend(
                _notification_descriptors(
                    controls.notifications, f"{controls_pointer}/notifications"
                )
            )
    elif controls is not None:
        if controls.notifications is not None:
            warnings.append(
                _issue(
                    f"{controls_pointer}/notifications",
                    "controls.notifications is consumed only by mission/v2 (as notify "
                    "watchers); mission/v1 ignores it",
                    "notifications_unconsumed",
                    ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                )
            )
        for index, item in enumerate(controls.subscriptions):
            if item.channel == "mcp":
                warnings.append(
                    _issue(
                        f"{controls_pointer}/subscriptions/{index}/channel",
                        "channel: mcp is never delivered; wait on the coordinator inbox "
                        "(missionctl wait, coordinator_inbox_wait)",
                        "mcp_channel_undelivered",
                        ManifestErrorCode.UNSUPPORTED_BEHAVIOR,
                    )
                )
    descriptors.extend(_event_wait_watchers(block, pointer, blockers, warnings))
    seen: set[str] = set()
    for descriptor in descriptors:
        if descriptor.watcher_id in seen:
            blockers.append(
                _issue(
                    descriptor.pointer,
                    f"watcher id {descriptor.watcher_id} is declared twice",
                    "duplicate_watcher",
                )
            )
        seen.add(descriptor.watcher_id)
        blockers.extend(descriptor_issues(descriptor, context))
    return MissionWatchers(
        descriptors=tuple(descriptors),
        pinned=tuple(pinned),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


__all__ = [
    "EVENT_WAIT_PREFIX",
    "NOTIFICATIONS_PREFIX",
    "ControlsV2",
    "MissionWatchers",
    "NotificationsDeclaration",
    "PinnedWatcher",
    "SubscriptionDeclarationV2",
    "WatcherContext",
    "compile_mission_watchers",
    "descriptor_issues",
    "mission_budget",
    "watcher_context",
]
