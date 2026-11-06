"""`mc.environment_preparation.v1`: the readiness ladder of one attempt's environment
(materialization-observation SPEC-01 section 8; MO-16).

The sealed `mc.environment_binding.v1` says what an attempt runs in; it is frozen before the
attempt prepares, so it cannot carry what preparation observed. This record does: one per
harness execution generation, it climbs

    declared -> rendered -> delivered -> prepared -> discovered -> exercised

* `declared`: the sealed binding names the environment (kit pin, secret declarations, network
  policy digest);
* `rendered`: the Host Projection's files and digests exist (the observed configuration digest);
* `delivered`: they were written to the leased worktree, committed at a SHA or synced to a
  provider environment;
* `prepared`: a preparation receipt arrived (a worker-hosted lane's own prepare receipt, or the
  mission layer's `.mission/setup/receipt.json` received through a frame or signal; on a cloud
  lane with no mission layer, a provider-side Discovery Proof, whose digest is the receipt);
* `discovered`: the provider reported loading the configuration (a Discovery Proof that names
  every item and reads every digest of the record's `discovery` expectation, MO-34);
* `exercised`: a projected control ran (a hook fired).

The ladder never regresses and is contiguous up to `prepared`; `discovered` and `exercised` are
observations after preparation, so a fired hook may record `exercised` on a lane that reports no
discovery. A launch policy names the minimum level a session may start at (default `prepared`
for worker-hosted lanes, `delivered` for cloud lanes, SPEC-01 section 8).

`declaration_digest` identifies what the binding declared about the environment; the manifest
Validation Report and the start receipt cite it, and every record of that environment carries
it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal
from uuid import UUID, uuid5

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.authoring.canonical import stable_json_digest
from mission_control.domain.capabilities.gates import SignalGatePolicy
from mission_control.domain.execution.bindings import EnvironmentBinding
from mission_control.domain.execution.discovery import DiscoveryExpectation
from mission_control.domain.execution.lanes import (
    DIGEST_PATTERN,
    PLACEMENT_OF_PROFILE,
    LaneProfileName,
)

ENVIRONMENT_PREPARATION_SCHEMA: Final = "mc.environment_preparation.v1"
ENVIRONMENT_DECLARATION_SCHEMA: Final = "mc.environment_declaration.v1"
# The closing-facts error code (and settlement failure code) of a session the launch policy
# refused to start.
ENVIRONMENT_NOT_READY: Final = "environment_not_ready"
_PREPARATION_NAMESPACE: Final = UUID("6f1d2b0e-5a8c-4d3e-9b7a-0c4e8f2a1d16")
_CHANNEL_PATTERN: Final = r"^[a-z][a-z0-9_]{0,63}$"


class ReadinessLevel(StrEnum):
    DECLARED = "declared"
    RENDERED = "rendered"
    DELIVERED = "delivered"
    PREPARED = "prepared"
    DISCOVERED = "discovered"
    EXERCISED = "exercised"


READINESS_LADDER: Final[tuple[ReadinessLevel, ...]] = tuple(ReadinessLevel)


def readiness_rank(level: ReadinessLevel) -> int:
    return READINESS_LADDER.index(level)


def readiness_at_least(level: ReadinessLevel, minimum: ReadinessLevel) -> bool:
    return readiness_rank(level) >= readiness_rank(minimum)


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReadinessRefused(ValueError):
    """An advance that would skip a preparation level or contradict a recorded receipt."""


# --- What the binding declared --------------------------------------------------------------------


class EnvironmentDeclaration(_Contract):
    """What a lane binding declares about its environment: the kit pin, the Secret Broker
    declarations (names and references, never values) and the network policy digest.

    A Cursor binding carries no environment binding, so a Cursor declaration names
    only its lane profile."""

    schema_version: Literal["mc.environment_declaration.v1"] = ENVIRONMENT_DECLARATION_SCHEMA
    lane_profile: LaneProfileName
    setup_pin: str | None = Field(default=None, min_length=1, max_length=512)
    secret_refs: tuple[str, ...] = ()
    in_environment_observation: bool | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )
    signal_gates: SignalGatePolicy | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        json_schema_extra={"digest_omit_default": True},
    )
    network_policy_ref: str | None = Field(default=None, min_length=1, max_length=256)

    @classmethod
    def of(
        cls, lane_profile: str, fields: dict[str, object] | None = None
    ) -> EnvironmentDeclaration:
        """From a lane profile name and `EnvironmentSelections.binding_fields()`."""

        return cls.model_validate({"lane_profile": lane_profile, **(fields or {})})

    @classmethod
    def of_binding(
        cls, lane_profile: LaneProfileName, environment: EnvironmentBinding | None
    ) -> EnvironmentDeclaration:
        if environment is None:
            return cls(lane_profile=lane_profile)
        return cls(
            lane_profile=lane_profile,
            setup_pin=environment.setup_pin,
            secret_refs=environment.secret_refs,
            in_environment_observation=environment.in_environment_observation,
            signal_gates=environment.signal_gates,
            network_policy_ref=environment.network_policy_ref,
        )

    @property
    def digest(self) -> str:
        return stable_json_digest(self)


# --- The record ---------------------------------------------------------------------------------


class PreparationDelivery(_Contract):
    """One prepared item and the channel that delivered it (`worktree`, `branch_commit`,
    `provider_environment`, `repository_file`, `owner_prerequisite`)."""

    item: str = Field(min_length=1, max_length=128)
    channel: str = Field(pattern=_CHANNEL_PATTERN)
    ref: str | None = Field(default=None, min_length=1, max_length=1_024)


class SecretChannel(_Contract):
    """A declared secret by name with the channel its lane delivers it through (the Secret
    Broker's `DeliveryChannel`, or `owner_prerequisite` where no per-run channel exists)."""

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
    channel: str = Field(pattern=_CHANNEL_PATTERN)


class ReadinessMark(_Contract):
    level: ReadinessLevel
    reached_at: AwareDatetime
    evidence_ref: str = Field(min_length=1, max_length=1_024)


def preparation_id(request_scope: str, harness_execution_id: UUID, generation: int) -> UUID:
    """The deterministic identity of one harness execution generation's preparation."""

    return uuid5(_PREPARATION_NAMESPACE, f"{request_scope}|{harness_execution_id}|{generation}")


class EnvironmentPreparation(_Contract):
    """`mc.environment_preparation.v1` (see the module doc)."""

    schema_version: Literal["mc.environment_preparation.v1"] = ENVIRONMENT_PREPARATION_SCHEMA
    preparation_id: UUID
    run_key: str = Field(min_length=1, max_length=512)
    harness_execution_id: UUID
    generation: int = Field(ge=1)
    lane_profile: LaneProfileName
    binding_digest: str = Field(pattern=DIGEST_PATTERN)
    declaration: EnvironmentDeclaration
    declaration_digest: str = Field(pattern=DIGEST_PATTERN)
    observed_config_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    deliveries: tuple[PreparationDelivery, ...] = ()
    secrets: tuple[SecretChannel, ...] = ()
    receipt_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)
    readiness: ReadinessLevel
    marks: tuple[ReadinessMark, ...] = Field(min_length=1)
    omissions: tuple[str, ...] = ()
    degradations: tuple[str, ...] = ()
    # What the lane's discovery mechanism must report (recorded at prepare; None on a lane
    # without one, which never reaches `discovered`).
    discovery: DiscoveryExpectation | None = None

    @model_validator(mode="after")
    def ladder_is_consistent(self) -> EnvironmentPreparation:
        if self.declaration.lane_profile != self.lane_profile:
            raise ValueError("the declaration belongs to another lane profile")
        if self.declaration_digest != self.declaration.digest:
            raise ValueError("declaration_digest does not match the declaration")
        ranks = [readiness_rank(mark.level) for mark in self.marks]
        if ranks != sorted(set(ranks)):
            raise ValueError("readiness marks ascend the ladder, one mark per level")
        prepared = readiness_rank(ReadinessLevel.PREPARED)
        reached = ranks[-1]
        if ranks[: prepared + 1] != list(range(min(reached, prepared) + 1)):
            raise ValueError("the ladder is contiguous from declared up to prepared")
        if self.marks[-1].level != self.readiness:
            raise ValueError("readiness is the highest level marked")
        if reached >= prepared and self.receipt_digest is None:
            raise ValueError("a prepared environment cites its receipt_digest")
        if reached < prepared and self.receipt_digest is not None:
            raise ValueError("a receipt makes the environment prepared")
        return self

    def mark(self, level: ReadinessLevel) -> ReadinessMark | None:
        return next((item for item in self.marks if item.level is level), None)

    def advanced(
        self,
        level: ReadinessLevel,
        *,
        at: AwareDatetime,
        evidence_ref: str,
        receipt_digest: str | None = None,
    ) -> EnvironmentPreparation:
        """This record at `level`; a level already reached returns it unchanged (idempotent,
        the ladder never regresses). Below `prepared` a level is reached only from the one
        before it, `prepared` needs a receipt, and `discovered`/`exercised` follow preparation."""

        if readiness_at_least(self.readiness, level):
            if receipt_digest is not None and receipt_digest != self.receipt_digest:
                raise ReadinessRefused("the environment already cites another receipt")
            return self
        current, target = readiness_rank(self.readiness), readiness_rank(level)
        prepared = readiness_rank(ReadinessLevel.PREPARED)
        if target <= prepared and target != current + 1:
            raise ReadinessRefused(f"{level} needs {READINESS_LADDER[target - 1]} first")
        if target > prepared and current < prepared:
            raise ReadinessRefused(f"{level} is observed only after the environment is prepared")
        if level is ReadinessLevel.PREPARED and receipt_digest is None:
            raise ReadinessRefused("prepared needs the preparation receipt digest")
        update: dict[str, object] = {
            "readiness": level,
            "marks": (
                *self.marks,
                ReadinessMark(level=level, reached_at=at, evidence_ref=evidence_ref),
            ),
        }
        if level is ReadinessLevel.PREPARED:
            update["receipt_digest"] = receipt_digest
        return EnvironmentPreparation.model_validate({**self.model_dump(), **update})

    def merged(self, later: EnvironmentPreparation) -> EnvironmentPreparation:
        """`later` (a re-observation of the same preparation) applied over this record: every
        level it reached beyond this one, in order; facts never move once recorded.

        A generation prepared again (a worker restarted before its native session was recorded
        re-prepares into the same lease) brings its own receipt: the receipt recorded first
        stays, so the re-preparation is admitted at the level already reached."""

        if (later.preparation_id, later.binding_digest, later.declaration_digest) != (
            self.preparation_id,
            self.binding_digest,
            self.declaration_digest,
        ):
            raise ReadinessRefused("another preparation cannot be merged into this one")
        merged = self
        for item in later.marks:
            receipt = None
            if item.level is ReadinessLevel.PREPARED and merged.receipt_digest is None:
                receipt = later.receipt_digest
            merged = merged.advanced(
                item.level,
                at=item.reached_at,
                evidence_ref=item.evidence_ref,
                receipt_digest=receipt,
            )
        if merged is self:
            return self
        return merged.model_copy(
            update={
                "observed_config_digest": self.observed_config_digest
                or later.observed_config_digest,
                "deliveries": self.deliveries or later.deliveries,
                "secrets": self.secrets or later.secrets,
                "discovery": self.discovery or later.discovery,
                "omissions": later.omissions,
                "degradations": later.degradations,
            }
        )


# --- Launch policy --------------------------------------------------------------------------------


class ReadinessRequirement(_Contract):
    """What a node role's environment must reach before its session starts.

    `declaration_source` says where the cited declaration comes from. `sealed_binding` is the
    role's sealed launch binding: every preparation record of that environment carries the same
    `declaration_digest`, so records are found by `(run_key, declaration_digest)`. The start
    receipt cites this. `manifest` is what the manifest alone declares. The Validation Report
    cites this, because it is compiled before any deployment binding is applied. A deployment
    host binding can add a kit, secret or network policy, and then the records carry another
    digest."""

    mission_key: str = Field(min_length=1)
    node_key: str = Field(min_length=1)
    role: Literal["node", "verifier"] = "node"
    pointer: str
    lane_profile: LaneProfileName
    minimum: ReadinessLevel
    declaration_source: Literal["manifest", "sealed_binding"]
    declaration_digest: str = Field(pattern=DIGEST_PATTERN)


class ReadinessDecision(_Contract):
    admitted: bool
    minimum: ReadinessLevel
    readiness: ReadinessLevel
    reason: str | None = None


class LaunchReadinessPolicy(_Contract):
    """The minimum readiness a session may start at, by the lane's placement."""

    worker_hosted: ReadinessLevel = ReadinessLevel.PREPARED
    cloud: ReadinessLevel = ReadinessLevel.DELIVERED

    def minimum(self, lane_profile: LaneProfileName) -> ReadinessLevel:
        placement = PLACEMENT_OF_PROFILE[lane_profile]
        return self.cloud if placement == "cloud" else self.worker_hosted

    def decide(self, preparation: EnvironmentPreparation) -> ReadinessDecision:
        minimum = self.minimum(preparation.lane_profile)
        admitted = readiness_at_least(preparation.readiness, minimum)
        reason = None
        if not admitted:
            gaps = "; ".join(preparation.omissions) or "no evidence of the next level"
            reason = (
                f"{preparation.lane_profile} needs {minimum} before its session starts; the "
                f"environment reached {preparation.readiness} ({gaps})"
            )
        return ReadinessDecision(
            admitted=admitted, minimum=minimum, readiness=preparation.readiness, reason=reason
        )


__all__ = [
    "ENVIRONMENT_DECLARATION_SCHEMA",
    "ENVIRONMENT_NOT_READY",
    "ENVIRONMENT_PREPARATION_SCHEMA",
    "READINESS_LADDER",
    "EnvironmentDeclaration",
    "EnvironmentPreparation",
    "LaunchReadinessPolicy",
    "PreparationDelivery",
    "ReadinessDecision",
    "ReadinessLevel",
    "ReadinessMark",
    "ReadinessRefused",
    "ReadinessRequirement",
    "SecretChannel",
    "preparation_id",
    "readiness_at_least",
    "readiness_rank",
]
