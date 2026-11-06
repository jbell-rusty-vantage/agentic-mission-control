"""Compiled Stage Graph routes, named release groups and typed stage facts (OVE-171, WI-08).

OUTPUT-CONTRACTS §7: ordering edges, named data bindings, release groups and conditional routing
are distinct. A compiled blueprint carries them as closed typed contracts:

- ``StageFact``: one named fact the host reads from a stage's accepted, schema-validated
  structured output at a JSON pointer (never agent prose, never a provider assertion).
- ``StageRoute``: an explicit ``all_matching`` or ordered ``first_match`` route whose branches are
  closed comparisons over pinned stage facts, releasing named target stages; ``else`` targets are
  released only when every branch is conclusively false.
- ``JoinGroup``: the named all/any/quorum release group of one consumer join, with its exact
  members in declared position order, the subjects their selected set must cover together and the
  first-qualifying selection policy.

``GRAPH_SEMANTICS_V1`` marks a blueprint compiled with these semantics (visible optional
omission, producer-level group thresholds and exact selection, route gating). A blueprint without
the marker keeps the earlier semantics, so a run admitted before this cutover replays unchanged.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

GraphSemantics = Literal["oc-graph-routes-v1"]
GRAPH_SEMANTICS_V1: Final[GraphSemantics] = "oc-graph-routes-v1"

# A fact value is a bounded scalar: facts travel in the family projection (W1 D10).
MAX_FACT_STRING_CHARS: Final = 256
MAX_ROUTES: Final = 32
MAX_BRANCHES: Final = 16
MAX_PREDICATES: Final = 8
MAX_IN_VALUES: Final = 32
MAX_GROUP_SUBJECTS: Final = 64

FactValueType = Literal["string", "integer", "boolean"]
FactScalar = StrictBool | StrictInt | Annotated[StrictStr, StringConstraints(max_length=256)]
PredicateOp = Literal["eq", "ne", "lt", "le", "gt", "ge", "in", "not_in"]
RouteMode = Literal["all_matching", "first_match"]
ORDERED_OPS: Final = frozenset({"lt", "le", "gt", "ge"})
SET_OPS: Final = frozenset({"in", "not_in"})


def _identifier(value: str) -> str:
    if not value or value != unicodedata.normalize("NFC", value):
        raise ValueError("graph route identifiers must be non-empty Unicode NFC")
    if any(ord(character) < 32 or character == "\x7f" for character in value):
        raise ValueError("graph route identifiers cannot contain control characters")
    return value


def scalar_type(value: object) -> FactValueType | None:
    """The fact type of a scalar (``bool`` before ``int``: a JSON boolean is never a number)."""

    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, str):
        return "string"
    return None


class _Route(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StageFact(_Route):
    """A named fact of one stage: the scalar at ``pointer`` in its accepted ``output_slot_id``."""

    fact_id: str = Field(max_length=128)
    output_slot_id: str = Field(max_length=200)
    pointer: str = Field(pattern=r"^(/[^/]+)+$", max_length=512)
    value_type: FactValueType

    _ids = field_validator("fact_id", "output_slot_id")(_identifier)


class FactPredicate(_Route):
    """A closed typed comparison of one stage fact with an authored literal."""

    stage_id: str = Field(max_length=200)
    fact_id: str = Field(max_length=128)
    op: PredicateOp
    value: FactScalar | tuple[FactScalar, ...]

    _ids = field_validator("stage_id", "fact_id")(_identifier)

    @model_validator(mode="after")
    def _typed(self) -> FactPredicate:
        values = self.value if isinstance(self.value, tuple) else (self.value,)
        if (self.op in SET_OPS) != isinstance(self.value, tuple):
            raise ValueError("in/not_in compare with a list; every other operator a scalar")
        if not values or len(values) > MAX_IN_VALUES:
            raise ValueError(f"a predicate compares with 1..{MAX_IN_VALUES} values")
        types = {scalar_type(item) for item in values}
        if len(types) != 1:
            raise ValueError("a predicate's values share one fact type")
        if self.op in ORDERED_OPS and types != {"integer"}:
            raise ValueError("ordered comparisons apply to integer facts only")
        return self

    @property
    def value_type(self) -> FactValueType:
        first = self.value[0] if isinstance(self.value, tuple) else self.value
        kind = scalar_type(first)
        if kind is None:  # pragma: no cover - the validator admits scalars only
            raise ValueError("predicate value is not a scalar")
        return kind


class RouteBranch(_Route):
    """One branch: every predicate must hold (a conjunction) to release its targets."""

    branch_id: str = Field(max_length=128)
    predicates: tuple[FactPredicate, ...] = Field(min_length=1, max_length=MAX_PREDICATES)
    target_stage_ids: tuple[str, ...] = Field(min_length=1)

    _ids = field_validator("branch_id")(_identifier)

    @field_validator("target_stage_ids")
    @classmethod
    def _targets(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({_identifier(item) for item in value}))
        if len(normalized) != len(value):
            raise ValueError("branch targets are unique")
        return normalized


class StageRoute(_Route):
    """An explicit conditional route; branch order is declared order and is never sorted."""

    route_id: str = Field(max_length=128)
    mode: RouteMode
    branches: tuple[RouteBranch, ...] = Field(min_length=1, max_length=MAX_BRANCHES)
    else_stage_ids: tuple[str, ...] = ()

    _ids = field_validator("route_id")(_identifier)

    @field_validator("else_stage_ids")
    @classmethod
    def _else(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({_identifier(item) for item in value}))
        if len(normalized) != len(value):
            raise ValueError("else targets are unique")
        return normalized

    @model_validator(mode="after")
    def _branches(self) -> StageRoute:
        ids = [item.branch_id for item in self.branches]
        if len(ids) != len(set(ids)) or "else" in ids:
            raise ValueError("branch identities are unique and never 'else'")
        return self

    @property
    def target_stage_ids(self) -> frozenset[str]:
        return frozenset(
            {stage for branch in self.branches for stage in branch.target_stage_ids}
            | set(self.else_stage_ids)
        )

    @property
    def fact_stage_ids(self) -> frozenset[str]:
        return frozenset(
            predicate.stage_id for branch in self.branches for predicate in branch.predicates
        )


class MemberCoverage(_Route):
    """The subjects one group member's output covers (authored, static)."""

    producer_stage_id: str = Field(max_length=200)
    subjects: tuple[str, ...] = Field(min_length=1, max_length=MAX_GROUP_SUBJECTS)

    _ids = field_validator("producer_stage_id")(_identifier)

    @field_validator("subjects")
    @classmethod
    def _subjects(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({_identifier(item) for item in value}))


class JoinGroup(_Route):
    """A named release group: exact members, threshold on distinct members, coverage, selection.

    ``member_stage_ids`` is the declared position order (the stable tie-break of the durable
    eligibility order). ``coverage_subjects`` must be covered by the selected set together; a
    quorum never waives it. Selection is the first qualifying distinct set in durable
    eligibility order (producer acceptance order, then position).
    """

    group_id: str = Field(max_length=128)
    member_stage_ids: tuple[str, ...] = Field(min_length=1)
    coverage_subjects: tuple[str, ...] = Field(default=(), max_length=MAX_GROUP_SUBJECTS)
    member_coverage: tuple[MemberCoverage, ...] = ()
    selection: Literal["first_qualifying"] = "first_qualifying"

    _ids = field_validator("group_id")(_identifier)

    @field_validator("coverage_subjects")
    @classmethod
    def _coverage(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({_identifier(item) for item in value}))

    @model_validator(mode="after")
    def _members(self) -> JoinGroup:
        if len(set(self.member_stage_ids)) != len(self.member_stage_ids):
            raise ValueError("group members are distinct")
        covered = [item.producer_stage_id for item in self.member_coverage]
        if len(set(covered)) != len(covered) or not set(covered) <= set(self.member_stage_ids):
            raise ValueError("member coverage names each group member at most once")
        reachable = {subject for item in self.member_coverage for subject in item.subjects}
        if not set(self.coverage_subjects) <= reachable:
            raise ValueError("no member set can cover every group coverage subject")
        return self

    def covers(self, producer_stage_id: str) -> frozenset[str]:
        return frozenset(
            subject
            for item in self.member_coverage
            if item.producer_stage_id == producer_stage_id
            for subject in item.subjects
        )


MAX_REVISIT_VISITS: Final = 16


class FactRef(_Route):
    stage_id: str = Field(max_length=200)
    fact_id: str = Field(max_length=128)

    _ids = field_validator("stage_id", "fact_id")(_identifier)


class CarriedOutput(_Route):
    """An exit output carried into the region entry on a revisit (the selected prior cycle's
    accepted revision, never an older attempt)."""

    stage_id: str = Field(max_length=200)
    output_slot_id: str = Field(max_length=200)

    _ids = field_validator("stage_id", "output_slot_id")(_identifier)


class RevisitRegion(_Route):
    """OVE-171 (01-STAGE_GRAPH §8): an explicit bounded Revisit Region.

    A declared entry and exit over a known stage set; a hard visit cap (``max_visits`` counts
    the first visit); a deterministic stop: ``until`` predicates over pinned facts when
    authored, otherwise fulfillment (every required obligation the region's stages owe is
    accepted); an optional integer ``progress`` fact with ``patience`` (no-progress limit).
    Cap or no-progress exhaustion is a governed terminal outcome of the region, never success.
    """

    region_id: str = Field(max_length=128)
    stage_ids: tuple[str, ...] = Field(min_length=1)
    entry_stage_id: str = Field(max_length=200)
    exit_stage_id: str = Field(max_length=200)
    max_visits: int = Field(ge=2, le=MAX_REVISIT_VISITS)
    until: tuple[FactPredicate, ...] = Field(default=(), max_length=MAX_PREDICATES)
    progress: FactRef | None = None
    patience: int | None = Field(default=None, ge=1, le=MAX_REVISIT_VISITS)
    carry: tuple[CarriedOutput, ...] = ()

    _ids = field_validator("region_id", "entry_stage_id", "exit_stage_id")(_identifier)

    @field_validator("stage_ids")
    @classmethod
    def _stages(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({_identifier(item) for item in value}))
        if len(normalized) != len(value):
            raise ValueError("region stages are unique")
        return normalized

    @model_validator(mode="after")
    def _shape(self) -> RevisitRegion:
        members = set(self.stage_ids)
        if self.entry_stage_id not in members or self.exit_stage_id not in members:
            raise ValueError("a region's entry and exit are region stages")
        if (self.patience is None) != (self.progress is None):
            raise ValueError("a progress fact and its patience are declared together")
        if any(item.stage_id not in members for item in self.until):
            raise ValueError("a region's stop rule reads facts of its own stages")
        if self.progress is not None and self.progress.stage_id not in members:
            raise ValueError("a region's progress fact belongs to one of its stages")
        if any(item.stage_id != self.exit_stage_id for item in self.carry):
            raise ValueError("a region carries outputs of its exit stage")
        return self


__all__ = [
    "GRAPH_SEMANTICS_V1",
    "MAX_FACT_STRING_CHARS",
    "MAX_REVISIT_VISITS",
    "MAX_ROUTES",
    "CarriedOutput",
    "FactPredicate",
    "FactRef",
    "FactScalar",
    "FactValueType",
    "GraphSemantics",
    "JoinGroup",
    "MemberCoverage",
    "RevisitRegion",
    "RouteBranch",
    "RouteMode",
    "StageFact",
    "StageRoute",
    "scalar_type",
]
