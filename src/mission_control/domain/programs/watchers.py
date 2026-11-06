"""Watchers: declared, bounded, deterministic reactions to observed facts (SPEC-04 §5, ADR-0046).

A watcher is authored under ``controls.watchers`` (or published as the Capability Kind
``watcher``, ``mc.watcher.v1``) as a trigger, an optional closed condition, typed actions and
boundaries. Compilation turns every watcher into an immutable :class:`WatcherDescriptor`
carried by the mission definition (the Compiled Program); the Watcher Evaluator then reads
the run's journal, its signals and its clock and plans firings with :func:`plan_watchers`.

Pure rules only:

- **Triggers** are closed: a mission event (``event``, public aliases included), an agent or
  provider ``signal``, the ``absence`` of events, frames or signals for a duration, or an
  interval ``schedule``. Durations are measured from the arming time and the last firing, so
  the same silence or tick fires once.
- **Conditions** (``where`` over the trigger, ``while`` over the run) are the closed AST of
  :mod:`watcher_conditions` (ADR-0010); there is no free-form code.
- **Actions** map onto existing paths only: ``notify`` (an inbox notification of a
  significance kind), ``instruct`` (``queue_instruction`` or ``interrupt_and_inject``),
  ``satisfy_wait`` (releases an ``event_wait`` node's declared wait; a fact matched before
  the run declares that wait is held until it does), ``command`` (``pause``, ``cancel``,
  ``request_continuation``) and ``probe`` (a run inspection).
- **Boundaries** are mandatory and always resolved: ``max_fires``, ``min_interval``, a rate,
  the recursion depth, a usage budget for ``instruct``, the minimum signal trust tier and an
  optional lifetime (``until``). Defaults come from the coordinator profile's defaults.
- **Dedupe.** A firing is keyed by ``(watcher_id, trigger_key)``; its journal event id and
  every action's request id derive from that key, so a replayed pass never acts twice.

Signals and provider outcomes are evidence, never authority: a firing only issues admitted
commands, and every limit is checked before any action leaves.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Final, Literal
from uuid import UUID, uuid5

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from mission_control.domain.authoring.manifest import (
    PIN_PATTERN,
    Duration,
    EventType,
    ManifestModel,
    Slug,
)
from mission_control.domain.programs.watcher_conditions import (
    PATH_PATTERN,
    ConditionSyntaxError,
    WatcherCondition,
    evaluate_condition,
    parse_condition,
    read_path,
)
from mission_control.domain.subscriptions.event_types import event_type_matches
from mission_control.domain.subscriptions.significance import NotifyKind

WATCHER_SPEC_SCHEMA_VERSION: Final = "mc.watcher.v1"
WATCHER_DESCRIPTOR_SCHEMA_VERSION: Final = "mc.watcher_descriptor.v1"
WATCHER_FIRED: Final = "watcher.fired"
WATCHER_FAILED: Final = "watcher.failed"
WATCHER_EVENTS: Final = frozenset({WATCHER_FIRED, WATCHER_FAILED})
# The run-control wait a StageGraph declared wait (an `event_wait` node) is recorded under;
# the StageGraph workflow declares and releases its waits with this same prefix.
WAIT_CONDITION_PREFIX: Final = "stagegraph-wait:"
# Boundary defaults: the coordinator profile's defaults (`mc.coordinator_profile.v1`).
DEFAULT_MAX_FIRES: Final = 12
DEFAULT_RATE: Final = (12, 300)
DEFAULT_MAX_DEPTH: Final = 2
MAX_DEPTH: Final = 8
MAX_WATCHERS: Final = 32
MAX_ACTIONS: Final = 8
MAX_INCLUDES: Final = 8
MAX_FACT_CHARS: Final = 256
_NAMESPACE: Final = UUID("8f1c2a64-5b0e-4f7a-9d3c-6e2b1a0f4c57")
_RATE = re.compile(r"^(?P<count>[1-9][0-9]{0,3})/(?P<span>[1-9][0-9]*)?(?P<unit>[smhd])$")
_UNIT_SECONDS: Final = {"s": 1, "m": 60, "h": 3600, "d": 86_400}

TrustTier = Literal["environment_key", "provider_signed", "provider_oidc", "run_token"]
TriggerKind = Literal["event", "signal", "absence", "schedule"]
AbsenceSource = Literal["event", "frame", "signal"]
WatcherOrigin = Literal["manifest", "catalog", "notifications", "event_wait"]
SuppressionReason = Literal[
    "recursion_bound",
    "trust_tier",
    "max_fires",
    "min_interval",
    "rate_limited",
    "budget_exhausted",
]
# Ingress tiers (SPEC-04 §3); journal events and timers are internal and outrank them all.
TRUST_RANK: Final[dict[str, int]] = {
    "environment_key": 0,
    "provider_signed": 1,
    "provider_oidc": 2,
    "run_token": 2,
}
INTERNAL_TRUST: Final = 3
# `instruct` and `command` change what a run does; a signal must be at least provider-signed
# to drive them (SPEC-04 §3: an environment key never drives effects).
DRIVING_TRUST: Final = "provider_signed"
USAGE_DIMENSIONS: Final = {"tokens": "tokens.total", "usd_micros": "currency.estimated_micros"}
# `run` and `watcher` in a condition: the facts the evaluator provides, with the closed
# vocabulary of each enumerated one (the run's phase and outcome, the inspection lifecycle),
# so a condition naming another fact or value is refused instead of never matching.
RUN_PHASES: Final = frozenset({"pending", "active", "waiting", "paused", "cancelling", "terminal"})
RUN_LIFECYCLES: Final = frozenset({"pending", "running", "paused", "completed"})
RUN_OUTCOMES: Final = frozenset({"completed", "partially_completed", "failed", "cancelled"})
RUN_FACTS: Final[Mapping[str, frozenset[str] | None]] = {
    "id": None,
    "lifecycle": RUN_LIFECYCLES,
    "phase": RUN_PHASES,
    "outcome": RUN_OUTCOMES,
    "version": None,
    "branch_prefix": None,
}
WATCHER_FACTS: Final = frozenset({"id", "fires"})


def _check_facts(condition: WatcherCondition) -> None:
    for path in condition.paths():
        root, _, name = path.partition(".")
        known = RUN_FACTS if root == "run" else WATCHER_FACTS if root == "watcher" else None
        if known is not None and name not in known:
            raise ValueError(f"{path} is not a {root} fact ({root}.{'|'.join(sorted(known))})")
    _check_literals(condition)


def _check_literals(condition: WatcherCondition) -> None:
    for operand in condition.operands:
        _check_literals(operand)
    if condition.op not in {"eq", "ne", "in", "not_in"}:
        return
    for path, literal in (condition.values, condition.values[::-1]):
        if path.kind != "path" or not (path.text or "").startswith("run."):
            continue
        vocabulary = RUN_FACTS.get((path.text or "").removeprefix("run."))
        if vocabulary is None:
            continue
        words = literal.items if literal.kind == "list" else (literal,)
        for word in words:
            if word.kind == "string" and word.text not in vocabulary:
                known = ", ".join(sorted(vocabulary))
                raise ValueError(f"{path.text} is never {word.text!r} (it is one of {known})")


def _condition_text(value: str) -> str:
    try:
        condition = parse_condition(value)
    except ConditionSyntaxError as error:
        raise ValueError(f"condition {value!r}: {error}") from None
    try:
        _check_facts(condition)
    except ValueError as error:
        raise ValueError(f"condition {value!r}: {error}") from None
    return value


ConditionText = Annotated[
    str, StringConstraints(min_length=1, max_length=2048), AfterValidator(_condition_text)
]
SignalType = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")]
FactPath = Annotated[str, StringConstraints(pattern=PATH_PATTERN, max_length=256)]
RateText = Annotated[str, StringConstraints(pattern=_RATE.pattern)]


def parse_rate(text: str) -> tuple[int, int]:
    """``10/h`` or ``3/10m``: (count, window seconds)."""

    match = _RATE.fullmatch(text)
    if match is None:
        raise ValueError(f"rate {text!r} is <count>/<window>, such as 10/h or 3/10m")
    span = int(match["span"] or 1)
    return int(match["count"]), span * _UNIT_SECONDS[match["unit"]]


# --- Authoring shape (manifest `controls.watchers[]` and the `mc.watcher.v1` template) -------


class AbsenceTrigger(ManifestModel):
    of: tuple[AbsenceSource, ...] = Field(min_length=1, max_length=3)
    for_: Duration = Field(alias="for")

    @model_validator(mode="after")
    def _unique(self) -> AbsenceTrigger:
        if len(set(self.of)) != len(self.of):
            raise ValueError("absence.of must not repeat a source")
        return self


class ScheduleTrigger(ManifestModel):
    every: Duration


class WatcherTriggerSpec(ManifestModel):
    """``on``: exactly one trigger; ``where`` filters a fact trigger, ``while`` gates on the run."""

    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [{"required": [key]} for key in ("signal", "event", "absence", "schedule")]
        }
    )

    signal: SignalType | None = None
    event: EventType | None = None
    absence: AbsenceTrigger | None = None
    schedule: ScheduleTrigger | None = None
    where: ConditionText | None = None
    while_: ConditionText | None = Field(default=None, alias="while")

    @model_validator(mode="after")
    def _one_trigger(self) -> WatcherTriggerSpec:
        present = [
            name for name in ("signal", "event", "absence", "schedule") if getattr(self, name)
        ]
        if len(present) != 1:
            raise ValueError(
                "a watcher trigger needs exactly one of signal | event | absence | schedule"
            )
        if self.where is not None and present[0] in {"absence", "schedule"}:
            raise ValueError(f"an {present[0]} trigger has no event to filter; use while")
        return self

    @property
    def kind(self) -> TriggerKind:
        if self.signal is not None:
            return "signal"
        if self.event is not None:
            return "event"
        return "absence" if self.absence is not None else "schedule"


class NotifyAction(ManifestModel):
    kind: NotifyKind
    text: str | None = Field(default=None, min_length=1, max_length=MAX_FACT_CHARS)


class InstructAction(ManifestModel):
    target: Literal["self"] = "self"
    text: str = Field(min_length=1, max_length=4096)
    include: tuple[FactPath, ...] = Field(default=(), max_length=MAX_INCLUDES)
    delivery: Literal["queue_instruction", "interrupt_and_inject"] = "queue_instruction"
    boundary: Literal["next_turn", "next_iteration"] = "next_turn"


class SatisfyWaitAction(ManifestModel):
    node: Slug


class CommandAction(ManifestModel):
    kind: Literal["pause", "cancel", "request_continuation"]
    urgency: Literal["normal", "immediate"] | None = None

    @model_validator(mode="after")
    def _urgency_for_cancel(self) -> CommandAction:
        if self.urgency is not None and self.kind != "cancel":
            raise ValueError("urgency applies to cancel only")
        return self


class ProbeAction(ManifestModel):
    target: Literal["self"] = "self"


_ACTION_KEYS: Final = ("notify", "instruct", "satisfy_wait", "command", "probe")


class WatcherActionSpec(ManifestModel):
    """One ``then`` entry: exactly one typed action, each mapped to an existing path."""

    model_config = ConfigDict(
        json_schema_extra={"oneOf": [{"required": [key]} for key in _ACTION_KEYS]}
    )

    notify: NotifyAction | None = None
    instruct: InstructAction | None = None
    satisfy_wait: SatisfyWaitAction | None = None
    command: CommandAction | None = None
    probe: ProbeAction | None = None

    @model_validator(mode="after")
    def _one_action(self) -> WatcherActionSpec:
        present = [name for name in _ACTION_KEYS if getattr(self, name) is not None]
        if len(present) != 1:
            raise ValueError(f"a watcher action needs exactly one of {' | '.join(_ACTION_KEYS)}")
        return self

    @property
    def kind(self) -> str:
        return next(name for name in _ACTION_KEYS if getattr(self, name) is not None)

    @property
    def command_kind(self) -> str | None:
        """The run command this action is admitted as, or None (notify and probe)."""

        if self.instruct is not None:
            return self.instruct.delivery
        if self.satisfy_wait is not None:
            return "satisfy_wait"
        if self.command is not None:
            return self.command.kind
        return None

    @property
    def drives_run(self) -> bool:
        return self.instruct is not None or self.command is not None


class WatcherBudget(ManifestModel):
    tokens: int | None = Field(default=None, ge=1)
    usd: Decimal | None = Field(default=None, gt=0, decimal_places=6)

    @model_validator(mode="after")
    def _some_dimension(self) -> WatcherBudget:
        if self.tokens is None and self.usd is None:
            raise ValueError("a watcher budget names tokens or usd")
        return self


class WatcherLimits(ManifestModel):
    max_fires: int | None = Field(default=None, ge=1, le=1000)
    min_interval: Duration | None = None
    rate: RateText | None = None
    max_depth: int | None = Field(default=None, ge=0, le=MAX_DEPTH)
    budget: WatcherBudget | None = None
    min_trust: TrustTier | None = None


class WatcherUntil(ManifestModel):
    model_config = ConfigDict(
        json_schema_extra={"oneOf": [{"required": ["event"]}, {"required": ["deadline"]}]}
    )

    event: EventType | None = None
    deadline: AwareDatetime | None = None

    @model_validator(mode="after")
    def _one_end(self) -> WatcherUntil:
        if (self.event is None) == (self.deadline is None):
            raise ValueError("until needs exactly one of event | deadline")
        return self


def _check_driving_trust(then: Sequence[WatcherActionSpec], limits: WatcherLimits | None) -> None:
    trust = limits.min_trust if limits is not None else None
    driving = any(action.drives_run for action in then)
    if driving and trust is not None and TRUST_RANK[trust] < TRUST_RANK[DRIVING_TRUST]:
        raise ValueError(f"instruct and command actions need min_trust {DRIVING_TRUST} or higher")


class WatcherSpec(ManifestModel):
    """The body of a watcher: what ``mc.watcher.v1`` publishes and a manifest inlines."""

    on: WatcherTriggerSpec
    then: tuple[WatcherActionSpec, ...] = Field(min_length=1, max_length=MAX_ACTIONS)
    limits: WatcherLimits | None = None
    until: WatcherUntil | None = None

    @model_validator(mode="after")
    def _trust_for_driving_actions(self) -> WatcherSpec:
        _check_driving_trust(self.then, self.limits)
        return self


class WatcherDeclaration(ManifestModel):
    """One ``controls.watchers`` entry: an inline :class:`WatcherSpec` or a catalog ``pin``.

    A pinned watcher takes its body from the published ``mc.watcher.v1`` template; the entry
    may only narrow its ``limits`` and set ``until``.
    """

    model_config = ConfigDict(
        json_schema_extra={"oneOf": [{"required": ["pin"]}, {"required": ["on", "then"]}]}
    )

    id: Slug
    pin: str | None = Field(default=None, pattern=PIN_PATTERN)
    on: WatcherTriggerSpec | None = None
    then: tuple[WatcherActionSpec, ...] | None = Field(
        default=None, min_length=1, max_length=MAX_ACTIONS
    )
    limits: WatcherLimits | None = None
    until: WatcherUntil | None = None

    @model_validator(mode="after")
    def _inline_or_pinned(self) -> WatcherDeclaration:
        if self.pin is not None:
            if self.on is not None or self.then is not None:
                raise ValueError("a pinned watcher takes on and then from its template")
            if not self.pin.endswith("@latest") and "#sha256:" not in self.pin:
                raise ValueError(
                    "an exact watcher pin needs #sha256:<digest>; only @latest may omit it"
                )
        elif self.on is None or self.then is None:
            raise ValueError("an inline watcher declares on and then (or names a pin)")
        else:
            _check_driving_trust(self.then, self.limits)
        return self

    def spec(self) -> WatcherSpec:
        """The inline body (pinned watchers resolve theirs from the catalog)."""

        if self.on is None or self.then is None:
            raise ValueError(f"watcher {self.id} is pinned; its body is in the catalog")
        return WatcherSpec(on=self.on, then=self.then, limits=self.limits, until=self.until)


# --- Compiled descriptors ------------------------------------------------------------------


class WatcherContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WatcherTrigger(WatcherContract):
    kind: TriggerKind
    name: str | None = None  # the event type pattern or the signal type
    absence_of: tuple[AbsenceSource, ...] = ()
    seconds: int | None = Field(default=None, ge=1)  # absence duration or schedule interval

    @model_validator(mode="after")
    def _shape(self) -> WatcherTrigger:
        named = self.kind in {"event", "signal"}
        if named != (self.name is not None) or named == (self.seconds is not None):
            raise ValueError(f"a {self.kind} trigger is malformed")
        if (self.kind == "absence") != bool(self.absence_of):
            raise ValueError("only an absence trigger names its sources")
        return self


class WatcherBoundaries(WatcherContract):
    """Every limit resolved; nothing is left to a runtime default."""

    max_fires: int = Field(ge=1)
    min_interval_seconds: int | None = Field(default=None, ge=1)
    rate_count: int = Field(ge=1)
    rate_window_seconds: int = Field(ge=1)
    max_depth: int = Field(ge=0)
    budget_tokens: int | None = Field(default=None, ge=1)
    budget_usd_micros: int | None = Field(default=None, ge=1)
    min_trust: TrustTier
    until_event: str | None = None
    until_deadline: AwareDatetime | None = None


class WatcherDescriptor(WatcherContract):
    """``mc.watcher_descriptor.v1``: one compiled watcher in the Compiled Program."""

    schema_version: Literal["mc.watcher_descriptor.v1"] = WATCHER_DESCRIPTOR_SCHEMA_VERSION
    # Authored ids are slugs; implied watchers are `notifications:<n>` and `event_wait:<node>`.
    watcher_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_:-]{0,191}$")
    origin: WatcherOrigin
    pointer: str
    template: str | None = None
    trigger: WatcherTrigger
    where: WatcherCondition | None = None
    active_while: WatcherCondition | None = None
    actions: tuple[WatcherActionSpec, ...] = Field(min_length=1, max_length=MAX_ACTIONS)
    boundaries: WatcherBoundaries

    @property
    def command_kinds(self) -> frozenset[str]:
        return frozenset(
            kind for action in self.actions if (kind := action.command_kind) is not None
        )


def _narrow(name: str, ceiling: int | None, value: int | None) -> int | None:
    if value is None:
        return ceiling
    if ceiling is not None and value > ceiling:
        raise ValueError(f"limits.{name} {value} widens the template's {ceiling}")
    return value


def resolve_boundaries(
    spec: WatcherSpec, overrides: WatcherLimits | None = None, until: WatcherUntil | None = None
) -> WatcherBoundaries:
    """The spec's limits with defaults filled in, narrowed by a pinning entry's overrides."""

    limits = spec.limits or WatcherLimits()
    rate_count, rate_window = parse_rate(limits.rate) if limits.rate else DEFAULT_RATE
    budget = limits.budget
    tokens = budget.tokens if budget is not None else None
    usd = _usd_micros(budget.usd) if budget is not None and budget.usd is not None else None
    driving = any(action.drives_run for action in spec.then)
    trust: TrustTier = limits.min_trust or (DRIVING_TRUST if driving else "environment_key")
    max_fires = limits.max_fires or DEFAULT_MAX_FIRES
    min_interval = limits.min_interval
    max_depth = DEFAULT_MAX_DEPTH if limits.max_depth is None else limits.max_depth
    if overrides is not None:
        max_fires = _narrow("max_fires", max_fires, overrides.max_fires) or max_fires
        max_depth = _narrow("max_depth", max_depth, overrides.max_depth) or 0
        if overrides.min_interval is not None:
            if min_interval is not None and overrides.min_interval < min_interval:
                raise ValueError("limits.min_interval shortens the template's interval")
            min_interval = overrides.min_interval
        if overrides.rate is not None:
            count, window = parse_rate(overrides.rate)
            if count / window > rate_count / rate_window:
                raise ValueError(f"limits.rate {overrides.rate} widens the template's rate")
            rate_count, rate_window = count, window
        if overrides.budget is not None:
            tokens = _narrow("budget.tokens", tokens, overrides.budget.tokens)
            usd = _narrow(
                "budget.usd",
                usd,
                _usd_micros(overrides.budget.usd) if overrides.budget.usd is not None else None,
            )
        if overrides.min_trust is not None:
            if TRUST_RANK[overrides.min_trust] < TRUST_RANK[trust]:
                raise ValueError("limits.min_trust lowers the template's trust tier")
            trust = overrides.min_trust
    end = until or spec.until
    return WatcherBoundaries(
        max_fires=max_fires,
        min_interval_seconds=min_interval,
        rate_count=rate_count,
        rate_window_seconds=rate_window,
        max_depth=max_depth,
        budget_tokens=tokens,
        budget_usd_micros=usd,
        min_trust=trust,
        until_event=end.event if end is not None else None,
        until_deadline=end.deadline if end is not None else None,
    )


def _usd_micros(value: Decimal) -> int:
    return int((value * Decimal(1_000_000)).to_integral_value())


def compile_watcher(
    spec: WatcherSpec,
    *,
    watcher_id: str,
    origin: WatcherOrigin,
    pointer: str,
    template: str | None = None,
    overrides: WatcherLimits | None = None,
    until: WatcherUntil | None = None,
) -> WatcherDescriptor:
    """One authored (or published) watcher as its immutable descriptor. Pure."""

    on = spec.on
    kind = on.kind
    trigger = WatcherTrigger(
        kind=kind,
        name=on.event if kind == "event" else on.signal,
        absence_of=on.absence.of if on.absence is not None else (),
        seconds=(
            on.absence.for_
            if on.absence is not None
            else on.schedule.every
            if on.schedule is not None
            else None
        ),
    )
    return WatcherDescriptor(
        watcher_id=watcher_id,
        origin=origin,
        pointer=pointer,
        template=template,
        trigger=trigger,
        where=parse_condition(on.where) if on.where is not None else None,
        active_while=parse_condition(on.while_) if on.while_ is not None else None,
        actions=spec.then,
        boundaries=resolve_boundaries(spec, overrides, until),
    )


def wait_condition_id(node_key: str) -> str:
    """The run-control wait an ``event_wait`` node's declared StageGraph wait is held under."""

    return f"{WAIT_CONDITION_PREFIX}{node_key}"


# --- Evaluation ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """One fact a watcher may react to: a committed mission event or an ingested signal.

    ``types`` lists every name the fact answers to (the canonical type first, then its public
    alias); ``data`` is its bounded, redacted payload; ``trust`` is a signal's ingress tier.
    """

    source: Literal["event", "signal"]
    ref: str
    types: tuple[str, ...]
    at: datetime
    seq: int | None = None
    causation_ref: str | None = None
    node_key: str | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    trust: TrustTier | None = None

    @property
    def trigger_key(self) -> str:
        return f"{self.source}:{self.ref}"


@dataclass(frozen=True)
class FiringRecord:
    """A ``watcher.fired`` or ``watcher.failed`` already in the journal."""

    watcher_id: str
    trigger_key: str
    at: datetime
    depth: int
    outcome: Literal["fired", "failed"]
    request_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TriggerRef:
    kind: TriggerKind
    ref: str
    type: str | None = None
    seq: int | None = None


@dataclass(frozen=True)
class PlannedAction:
    index: int
    spec: WatcherActionSpec
    request_id: UUID


@dataclass(frozen=True)
class Firing:
    watcher: WatcherDescriptor
    trigger_key: str
    trigger: TriggerRef
    at: datetime
    depth: int
    actions: tuple[PlannedAction, ...]
    included: Mapping[str, Any] = field(default_factory=dict)
    trust: TrustTier | None = None


@dataclass(frozen=True)
class Suppression:
    watcher_id: str
    trigger_key: str
    reason: SuppressionReason


@dataclass(frozen=True)
class HeldTrigger:
    """A matched fact whose firing waits for the run to declare the wait it releases.

    A ``satisfy_wait`` firing is only issued once its wait is active, so an event that comes
    before the StageGraph reaches the ``event_wait`` stage is held (not fired, not counted)
    and released on the first pass that sees the wait declared.
    """

    watcher_id: str
    observation: Observation


@dataclass(frozen=True)
class WatcherPlanInput:
    run_id: str
    descriptors: tuple[WatcherDescriptor, ...]
    observations: tuple[Observation, ...]
    history: tuple[FiringRecord, ...]
    armed_at: datetime
    now: datetime
    run: Mapping[str, Any] = field(default_factory=dict)
    run_terminal: bool = False
    last_seen: Mapping[str, datetime] = field(default_factory=dict)
    usage: Mapping[str, int] = field(default_factory=dict)
    retired: frozenset[str] = frozenset()
    # The run's active wait condition ids, and the triggers earlier passes held for them.
    waits: frozenset[str] = frozenset()
    held: tuple[HeldTrigger, ...] = ()


@dataclass(frozen=True)
class WatcherPlan:
    firings: tuple[Firing, ...]
    suppressed: tuple[Suppression, ...]
    retired: frozenset[str]
    next_deadline: datetime | None
    held: tuple[HeldTrigger, ...] = ()


def action_request_id(run_id: str, watcher_id: str, trigger_key: str, index: int) -> UUID:
    """The request id of one action of one firing: replaying the firing replays the command."""

    return uuid5(_NAMESPACE, f"v1:{run_id}:{watcher_id}:{trigger_key}:{index}")


def firing_event_id(run_id: str, watcher_id: str, trigger_key: str, *, failed: bool) -> str:
    """The journal event id of a firing's record (the outbox dedupe key)."""

    return f"{WATCHER_FAILED if failed else WATCHER_FIRED}:{run_id}:{watcher_id}:{trigger_key}"


def plan_watchers(data: WatcherPlanInput) -> WatcherPlan:
    """Plan one evaluation pass. Deterministic: the same journal, clock and history always
    yield the same firings, keys and request ids."""

    return _Planner(data).run()


class _Planner:
    def __init__(self, data: WatcherPlanInput) -> None:
        self.data = data
        self.fires: dict[str, list[datetime]] = {}
        self.keys: dict[str, set[str]] = {}
        self.depth_of_request: dict[str, int] = {}
        for record in data.history:
            self.fires.setdefault(record.watcher_id, []).append(record.at)
            self.keys.setdefault(record.watcher_id, set()).add(record.trigger_key)
            for request_id in record.request_ids:
                self.depth_of_request[request_id] = record.depth
        for moments in self.fires.values():
            moments.sort()
        self.retired = set(data.retired)
        self.firings: list[Firing] = []
        self.suppressed: list[Suppression] = []
        self.deadlines: list[datetime] = []
        self.held: dict[str, Observation] = {}

    def run(self) -> WatcherPlan:
        by_id = {descriptor.watcher_id: descriptor for descriptor in self.data.descriptors}
        for held in self.data.held:
            descriptor = by_id.get(held.watcher_id)
            if descriptor is not None:
                self._observe(descriptor, held.observation)
        for observation in self.data.observations:
            for descriptor in self.data.descriptors:
                self._observe(descriptor, observation)
        if not self.data.run_terminal:
            for descriptor in self.data.descriptors:
                if descriptor.trigger.kind == "absence":
                    self._absence(descriptor)
                elif descriptor.trigger.kind == "schedule":
                    self._schedule(descriptor)
        return WatcherPlan(
            firings=tuple(self.firings),
            suppressed=tuple(self.suppressed),
            retired=frozenset(self.retired),
            next_deadline=min(self.deadlines) if self.deadlines else None,
            held=tuple(
                HeldTrigger(watcher_id, observation)
                for watcher_id, observation in sorted(self.held.items())
                if watcher_id not in self.retired
            ),
        )

    # -- facts --------------------------------------------------------------------------

    def _observe(self, descriptor: WatcherDescriptor, observation: Observation) -> None:
        watcher_id = descriptor.watcher_id
        if watcher_id in self.retired:
            return
        bounds = descriptor.boundaries
        ends = bounds.until_deadline is not None and observation.at >= bounds.until_deadline
        if bounds.until_event is not None and observation.source == "event":
            ends = ends or any(
                event_type_matches(bounds.until_event, name) for name in observation.types
            )
        if ends:
            self.retired.add(watcher_id)
            return
        matched = _matched_type(descriptor.trigger, observation)
        if matched is None or observation.trigger_key in self.keys.get(watcher_id, set()):
            return
        context = self._context(descriptor, observation, matched)
        if descriptor.where is not None and not evaluate_condition(descriptor.where, context):
            return
        if descriptor.active_while is not None and not evaluate_condition(
            descriptor.active_while, context
        ):
            return
        if not self._waits_declared(descriptor) and (
            len(self.fires.get(watcher_id, ())) < descriptor.boundaries.max_fires
        ):
            # Keep the earliest match; it fires once the run declares the wait.
            self.held.setdefault(watcher_id, observation)
            return
        self._decide(
            descriptor,
            trigger_key=observation.trigger_key,
            trigger=TriggerRef(
                kind=descriptor.trigger.kind,
                ref=observation.ref,
                type=matched,
                seq=observation.seq,
            ),
            at=observation.at,
            depth=self._depth(observation) + 1,
            # A signal without a recorded tier is trusted as little as possible.
            trust=observation.trust
            or ("environment_key" if observation.source == "signal" else None),
            context=context,
        )

    def _waits_declared(self, descriptor: WatcherDescriptor) -> bool:
        return all(
            wait_condition_id(action.satisfy_wait.node) in self.data.waits
            for action in descriptor.actions
            if action.satisfy_wait is not None
        )

    def _depth(self, observation: Observation) -> int:
        if observation.source == "event" and observation.types[0] in WATCHER_EVENTS:
            depth = observation.data.get("depth")
            return depth if isinstance(depth, int) and not isinstance(depth, bool) else 0
        if observation.causation_ref is not None:
            return self.depth_of_request.get(observation.causation_ref, 0)
        return 0

    def _context(
        self,
        descriptor: WatcherDescriptor,
        observation: Observation | None,
        matched: str | None,
    ) -> dict[str, Any]:
        context: dict[str, Any] = {
            "run": dict(self.data.run),
            "watcher": {
                "id": descriptor.watcher_id,
                "fires": len(self.fires.get(descriptor.watcher_id, ())),
            },
        }
        if observation is not None:
            context["event"] = {
                **observation.data,
                "type": matched,
                "ref": observation.ref,
                "source": observation.source,
            }
            if observation.node_key is not None:
                context["unit"] = {"key": observation.node_key}
        return context

    # -- clocks -------------------------------------------------------------------------

    def _absence(self, descriptor: WatcherDescriptor) -> None:
        if descriptor.watcher_id in self.retired:
            return
        trigger = descriptor.trigger
        assert trigger.seconds is not None
        seen = [
            self.data.last_seen[item] for item in trigger.absence_of if item in self.data.last_seen
        ]
        fired = self.fires.get(descriptor.watcher_id, [])
        baseline = max([self.data.armed_at, *seen, *fired[-1:]])
        deadline = baseline + timedelta(seconds=trigger.seconds)
        key = f"absence:{baseline.isoformat()}"
        self._timer(descriptor, deadline, key)

    def _schedule(self, descriptor: WatcherDescriptor) -> None:
        if descriptor.watcher_id in self.retired:
            return
        seconds = descriptor.trigger.seconds
        assert seconds is not None
        every = timedelta(seconds=seconds)
        ticks = int((self.data.now - self.data.armed_at) / every)
        if ticks >= 1:
            self._timer(descriptor, self.data.armed_at + ticks * every, f"schedule:{ticks}")
        self.deadlines.append(self.data.armed_at + (ticks + 1) * every)

    def _timer(self, descriptor: WatcherDescriptor, at: datetime, key: str) -> None:
        bounds = descriptor.boundaries
        # A clock trigger held by its interval or rate fires once they allow it, at that
        # moment; the deadline is always a future instant, so the evaluator never spins.
        due = self._clock_due(descriptor, at)
        if bounds.until_deadline is not None and due >= bounds.until_deadline:
            self.retired.add(descriptor.watcher_id)
            return
        if due > self.data.now:
            self.deadlines.append(due)
            return
        if key in self.keys.get(descriptor.watcher_id, set()):
            return
        context = self._context(descriptor, None, None)
        if descriptor.active_while is not None and not evaluate_condition(
            descriptor.active_while, context
        ):
            return
        if not self._waits_declared(descriptor):
            # A due clock that would satisfy an undeclared wait stays due: it fires on the
            # first pass (each pass reads the run's waits) that sees the wait declared.
            return
        fired = self._decide(
            descriptor,
            trigger_key=key,
            trigger=TriggerRef(kind=descriptor.trigger.kind, ref=key),
            at=due,
            depth=1,
            trust=None,
            context=context,
        )
        seconds = descriptor.trigger.seconds
        spent = len(self.fires.get(descriptor.watcher_id, ())) >= bounds.max_fires
        if fired is not None and not spent and descriptor.trigger.kind == "absence":
            # The silence restarts at this firing; a schedule reports its next tick itself.
            assert seconds is not None
            following = self._clock_due(descriptor, due + timedelta(seconds=seconds))
            if following > self.data.now:
                self.deadlines.append(following)

    def _clock_due(self, descriptor: WatcherDescriptor, at: datetime) -> datetime:
        """The earliest moment, not before ``at`` nor the last firing, at which the watcher's
        ``min_interval`` and rate admit another firing (``at`` once ``max_fires`` is spent:
        the refusal is then final and needs no deadline)."""

        bounds = descriptor.boundaries
        fires = self.fires.get(descriptor.watcher_id, [])
        if not fires or len(fires) >= bounds.max_fires:
            return at
        due = max(at, fires[-1])
        if bounds.min_interval_seconds is not None:
            due = max(due, fires[-1] + timedelta(seconds=bounds.min_interval_seconds))
        if len(fires) >= bounds.rate_count:
            window = timedelta(seconds=bounds.rate_window_seconds)
            due = max(due, fires[-bounds.rate_count] + window)
        return due

    # -- boundaries ---------------------------------------------------------------------

    def _decide(
        self,
        descriptor: WatcherDescriptor,
        *,
        trigger_key: str,
        trigger: TriggerRef,
        at: datetime,
        depth: int,
        trust: TrustTier | None,
        context: Mapping[str, Any],
    ) -> Firing | None:
        reason = self._refusal(descriptor, at=at, depth=depth, trust=trust)
        if reason is not None:
            self.suppressed.append(Suppression(descriptor.watcher_id, trigger_key, reason))
            return None
        run_id = self.data.run_id
        actions = tuple(
            PlannedAction(
                index=index,
                spec=spec,
                request_id=action_request_id(run_id, descriptor.watcher_id, trigger_key, index),
            )
            for index, spec in enumerate(descriptor.actions)
        )
        included = {
            path: read_path(context, path)
            for action in descriptor.actions
            if action.instruct is not None
            for path in action.instruct.include
        }
        firing = Firing(
            watcher=descriptor,
            trigger_key=trigger_key,
            trigger=trigger,
            at=at,
            depth=depth,
            actions=actions,
            included=included,
            trust=trust,
        )
        self.firings.append(firing)
        self.fires.setdefault(descriptor.watcher_id, []).append(at)
        self.fires[descriptor.watcher_id].sort()
        self.keys.setdefault(descriptor.watcher_id, set()).add(trigger_key)
        for action in actions:
            self.depth_of_request[str(action.request_id)] = depth
        return firing

    def _refusal(
        self, descriptor: WatcherDescriptor, *, at: datetime, depth: int, trust: TrustTier | None
    ) -> SuppressionReason | None:
        bounds = descriptor.boundaries
        fires = self.fires.get(descriptor.watcher_id, [])
        if depth > bounds.max_depth:
            return "recursion_bound"
        rank = TRUST_RANK[trust] if trust is not None else INTERNAL_TRUST
        if rank < TRUST_RANK[bounds.min_trust]:
            return "trust_tier"
        if len(fires) >= bounds.max_fires:
            return "max_fires"
        if (
            bounds.min_interval_seconds is not None
            and fires
            and at - fires[-1] < timedelta(seconds=bounds.min_interval_seconds)
        ):
            return "min_interval"
        window = timedelta(seconds=bounds.rate_window_seconds)
        if sum(1 for moment in fires if at - window < moment <= at) >= bounds.rate_count:
            return "rate_limited"
        if any(action.instruct is not None for action in descriptor.actions) and _over_budget(
            bounds, self.data.usage
        ):
            return "budget_exhausted"
        return None


def _matched_type(trigger: WatcherTrigger, observation: Observation) -> str | None:
    if trigger.kind != observation.source or trigger.name is None:
        return None
    for name in observation.types:
        if event_type_matches(trigger.name, name):
            return name
    return None


def _over_budget(bounds: WatcherBoundaries, usage: Mapping[str, int]) -> bool:
    if (
        bounds.budget_tokens is not None
        and usage.get(USAGE_DIMENSIONS["tokens"], 0) >= bounds.budget_tokens
    ):
        return True
    return (
        bounds.budget_usd_micros is not None
        and usage.get(USAGE_DIMENSIONS["usd_micros"], 0) >= bounds.budget_usd_micros
    )


# --- The journal record of a firing --------------------------------------------------------

ActionStatus = Literal["recorded", "admitted", "replayed", "rejected", "failed"]


@dataclass(frozen=True)
class ActionOutcome:
    index: int
    kind: str
    request_id: UUID
    status: ActionStatus
    detail: str | None = None
    facts: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"recorded", "admitted", "replayed"}


def firing_payload(firing: Firing, outcomes: Sequence[ActionOutcome]) -> dict[str, Any]:
    """The reference-only payload of ``watcher.fired`` / ``watcher.failed``.

    It names the watcher, the trigger and every action's request id and outcome; a notify
    action adds ``notify_kind`` and ``message`` for the coordinator inbox. Fact bodies never
    enter the journal: ``included`` values reach the instructed run only.
    """

    watcher = firing.watcher
    payload: dict[str, Any] = {
        "watcher_id": watcher.watcher_id,
        "origin": watcher.origin,
        "trigger_key": firing.trigger_key,
        "trigger": {
            "kind": firing.trigger.kind,
            "ref": firing.trigger.ref,
            "type": firing.trigger.type,
            "seq": firing.trigger.seq,
        },
        "trigger_type": firing.trigger.type or firing.trigger.kind,
        "fired_at": firing.at.isoformat(),
        "depth": firing.depth,
        "outcome": "fired" if all(item.ok for item in outcomes) else "failed",
        "actions": [
            {
                "index": item.index,
                "kind": item.kind,
                "request_id": str(item.request_id),
                "status": item.status,
                **({"detail": item.detail[:MAX_FACT_CHARS]} if item.detail else {}),
                **({"facts": dict(item.facts)} if item.facts else {}),
            }
            for item in outcomes
        ],
    }
    if firing.trust is not None:
        payload["trust"] = firing.trust
    notify = next((action.notify for action in watcher.actions if action.notify), None)
    if notify is not None:
        payload["notify_kind"] = notify.kind
        if notify.text is not None:
            payload["message"] = notify.text
    return payload


def firing_record(payload: Mapping[str, Any], event_type: str) -> FiringRecord | None:
    """A journal ``watcher.*`` payload back as history, or None when it is not one."""

    watcher_id = payload.get("watcher_id")
    key = payload.get("trigger_key")
    fired_at = payload.get("fired_at")
    depth = payload.get("depth")
    if not (
        isinstance(watcher_id, str)
        and isinstance(key, str)
        and isinstance(fired_at, str)
        and isinstance(depth, int)
    ):
        return None
    actions = payload.get("actions")
    request_ids = tuple(
        str(item["request_id"])
        for item in (actions if isinstance(actions, list) else [])
        if isinstance(item, Mapping) and isinstance(item.get("request_id"), str)
    )
    return FiringRecord(
        watcher_id=watcher_id,
        trigger_key=key,
        at=datetime.fromisoformat(fired_at),
        depth=depth,
        outcome="failed" if event_type == WATCHER_FAILED else "fired",
        request_ids=request_ids,
    )


__all__ = [
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_FIRES",
    "DEFAULT_RATE",
    "DRIVING_TRUST",
    "MAX_DEPTH",
    "MAX_WATCHERS",
    "RUN_FACTS",
    "RUN_LIFECYCLES",
    "RUN_OUTCOMES",
    "RUN_PHASES",
    "USAGE_DIMENSIONS",
    "WAIT_CONDITION_PREFIX",
    "WATCHER_DESCRIPTOR_SCHEMA_VERSION",
    "WATCHER_EVENTS",
    "WATCHER_FACTS",
    "WATCHER_FAILED",
    "WATCHER_FIRED",
    "WATCHER_SPEC_SCHEMA_VERSION",
    "AbsenceTrigger",
    "ActionOutcome",
    "CommandAction",
    "Firing",
    "FiringRecord",
    "HeldTrigger",
    "InstructAction",
    "NotifyAction",
    "Observation",
    "PlannedAction",
    "ProbeAction",
    "SatisfyWaitAction",
    "ScheduleTrigger",
    "Suppression",
    "TriggerRef",
    "TrustTier",
    "WatcherActionSpec",
    "WatcherBoundaries",
    "WatcherBudget",
    "WatcherDeclaration",
    "WatcherDescriptor",
    "WatcherLimits",
    "WatcherPlan",
    "WatcherPlanInput",
    "WatcherSpec",
    "WatcherTrigger",
    "WatcherTriggerSpec",
    "WatcherUntil",
    "action_request_id",
    "compile_watcher",
    "firing_event_id",
    "firing_payload",
    "firing_record",
    "parse_rate",
    "plan_watchers",
    "resolve_boundaries",
    "wait_condition_id",
]
