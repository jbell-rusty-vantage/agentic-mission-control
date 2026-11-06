"""Data Class admission: which mission data a lane profile may receive (SPEC-06 section 8).

Every mission declares a Data Class, from least to most sensitive ``public``, ``internal``,
``confidential``, ``phi`` or ``secret``. Neither hosted agent API is ZDR-eligible
(DECISIONS C3): transcripts persist until deleted and tool inputs and outputs pass through
the provider. So ``claude_managed`` and ``codex_agents`` admit only ``public`` and
``internal`` by default; an Application may widen that up to ``confidential``, never to
``phi`` or ``secret``. A mission that declares no class is refused on those lanes rather than
assumed harmless. Profiles without a policy row admit every class (a Sandbox Host lane
inherits its sandbox provider's policy, which is not modelled yet). An Application's policy is
its Application Binding's widening over the defaults (``application_policy``); an Application
that widens nothing gets the defaults, never a permissive policy.

Pure: a lane profile, the mission's class and the admitted policy in, an issue or nothing out.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.execution.lanes import (
    HOSTED_AGENT_API_PROFILES,
    LANE_PROFILES,
    LaneProfileName,
)

DataClass = Literal["public", "internal", "confidential", "phi", "secret"]
# OC-R4: whether a node's class was declared by the mission or is its fail-closed default
# (`undeclared_data_class`). Every lane carries it; it enters the configuration digest.
DataClassSource = Literal["declared", "ceiling_default"]
# Least to most sensitive.
DATA_CLASSES: Final[tuple[DataClass, ...]] = ("public", "internal", "confidential", "phi", "secret")

DATA_CLASS_NOT_ADMITTED: Final = "DATA_CLASS_NOT_ADMITTED"
DATA_CLASS_UNDECLARED: Final = "DATA_CLASS_UNDECLARED"

# SPEC-06 section 8: the default admission of the non-ZDR hosted agent APIs and the widest
# class an Application may admit there.
HOSTED_AGENT_API_DEFAULT: Final[frozenset[DataClass]] = frozenset({"public", "internal"})
HOSTED_AGENT_API_CEILING: Final[DataClass] = "confidential"


def _up_to(ceiling: DataClass) -> frozenset[DataClass]:
    return frozenset(DATA_CLASSES[: DATA_CLASSES.index(ceiling) + 1])


def _defaults() -> dict[str, frozenset[DataClass]]:
    return dict.fromkeys(HOSTED_AGENT_API_PROFILES, HOSTED_AGENT_API_DEFAULT)


class DataClassPolicy(BaseModel):
    """The classes each restricted lane profile admits; a profile absent here admits every
    class. ``widened`` builds an Application's policy over the defaults, and the validator
    holds every restricted profile at or below its ceiling."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    admitted: Mapping[str, frozenset[DataClass]] = Field(default_factory=_defaults)

    @model_validator(mode="after")
    def _within_ceiling(self) -> DataClassPolicy:
        unknown = sorted(set(self.admitted) - set(LANE_PROFILES))
        if unknown:
            raise ValueError(f"unknown lane profile(s): {', '.join(unknown)}")
        allowed = _up_to(HOSTED_AGENT_API_CEILING)
        for profile in HOSTED_AGENT_API_PROFILES:
            classes = self.admitted.get(profile)
            if classes is None:
                raise ValueError(f"lane profile {profile} needs a data class policy")
            beyond = sorted(classes - allowed, key=DATA_CLASSES.index)
            if beyond:
                raise ValueError(
                    f"lane profile {profile} cannot admit {', '.join(beyond)}: its ceiling is "
                    f"{HOSTED_AGENT_API_CEILING} (SPEC-06 section 8)"
                )
        return self

    def widened(self, profile: LaneProfileName, classes: Iterable[DataClass]) -> DataClassPolicy:
        """This policy with ``profile`` also admitting ``classes`` (still ceiling-checked)."""

        current = self.admitted.get(profile)
        if current is None:
            raise ValueError(f"lane profile {profile} has no data class policy to widen")
        return DataClassPolicy(admitted={**self.admitted, profile: current | frozenset(classes)})

    def admits(self, profile: str, data_class: DataClass | None) -> bool:
        classes = self.admitted.get(profile)
        if classes is None:
            return True
        return data_class is not None and data_class in classes


DEFAULT_DATA_CLASS_POLICY: Final = DataClassPolicy()


def application_policy(
    widening: Mapping[LaneProfileName, Iterable[DataClass]],
) -> DataClassPolicy:
    """The defaults with each profile also admitting its widened classes (ceiling-checked)."""

    policy = DEFAULT_DATA_CLASS_POLICY
    for profile, classes in widening.items():
        policy = policy.widened(profile, classes)
    return policy


def undeclared_data_class(
    lane_profile: str,
    ceiling: DataClass,
    *,
    policy: DataClassPolicy = DEFAULT_DATA_CLASS_POLICY,
) -> DataClass | None:
    """What a mission that declares no Data Class is handled as, failing closed (OC-R4).

    Never assumed harmless: it is the most sensitive class both the lane admits and the
    Application's ceiling admits, i.e. the worst its Application may carry there. A lane that
    admits only declared classes (the hosted agent APIs) returns ``None``: it refuses the
    mission as ``DATA_CLASS_UNDECLARED`` (``admit_data_class``). So the class follows the
    ceiling, not a fixed stand-in: under a ``confidential`` ceiling an undeclared mission is
    ``confidential``, where a declared ``internal`` mission stays ``internal``.
    """

    if lane_profile in policy.admitted:
        return None
    return ceiling


class DataClassIssue(BaseModel):
    """One refused (lane profile, data class) pair, pointed at the manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1)
    pointer: str
    lane_profile: str = Field(min_length=1)
    data_class: DataClass | None
    message: str = Field(min_length=1)


def admit_data_class(
    lane_profile: str,
    data_class: DataClass | None,
    *,
    policy: DataClassPolicy = DEFAULT_DATA_CLASS_POLICY,
    pointer: str = "/data_class",
) -> DataClassIssue | None:
    """The refusal of a mission of ``data_class`` on ``lane_profile``, or ``None`` if admitted."""

    if policy.admits(lane_profile, data_class):
        return None
    admitted = sorted(policy.admitted[lane_profile], key=DATA_CLASSES.index)
    if data_class is None:
        return DataClassIssue(
            code=DATA_CLASS_UNDECLARED,
            pointer=pointer,
            lane_profile=lane_profile,
            data_class=None,
            message=(
                f"lane profile {lane_profile} is not ZDR-eligible and admits only data class "
                f"{', '.join(admitted)}; the mission declares none"
            ),
        )
    return DataClassIssue(
        code=DATA_CLASS_NOT_ADMITTED,
        pointer=pointer,
        lane_profile=lane_profile,
        data_class=data_class,
        message=(
            f"lane profile {lane_profile} is not ZDR-eligible and admits only data class "
            f"{', '.join(admitted)}, not {data_class}"
        ),
    )


__all__ = [
    "DATA_CLASSES",
    "DATA_CLASS_NOT_ADMITTED",
    "DATA_CLASS_UNDECLARED",
    "DEFAULT_DATA_CLASS_POLICY",
    "HOSTED_AGENT_API_CEILING",
    "HOSTED_AGENT_API_DEFAULT",
    "DataClass",
    "DataClassIssue",
    "DataClassPolicy",
    "DataClassSource",
    "admit_data_class",
    "application_policy",
    "undeclared_data_class",
]
