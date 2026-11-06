"""Environment preparation records and the launch readiness gate (SPEC-01 section 8; MO-16).

`lane.turn` prepares a Session Lane, then hands the `PreparedSession` here before the session
starts. `preparation_of` reads it into `mc.environment_preparation.v1` against the sealed
binding: `declared` from the binding, `rendered` from the projection digests (the observed
configuration digest), `delivered` from the workspace the files were written to (a leased
worktree or a cloud branch commit, plus the kit's mission layer and, on `cursor_cloud`, the
provider environment or committed environment file holding its base layer, MO-13), and
`prepared` from a worker-hosted lane's prepare receipt.
When the binding pins an Environment Kit, `prepared` needs the passing
`.mission/setup/receipt.json` the lane's mission layer wrote (MO-12, `setup_receipt_digest`);
a cloud lane's mission layer reports through a receipt signal, so it stops at `delivered` and
says so. The record is
persisted (merged, never regressing) and the launch policy decides whether the session may
start. Evidence raises the ladder further: a Discovery Proof that names every item and reads
every digest the prepare recorded as its `discovery` expectation (`discovered`, SPEC-02 section 6;
MO-34, `discovery.py`), and a hook frame showing a projected control ran (`exercised`).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol
from uuid import UUID

from mission_control.application.environments.discovery import proof_gaps
from mission_control.application.secrets.delivery import DeliveryChannel
from mission_control.application.secrets.references import declarations
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.execution.bindings import ProviderExecutionBinding
from mission_control.domain.execution.discovery import DiscoveryReport
from mission_control.domain.execution.environment_preparation import (
    EnvironmentDeclaration,
    EnvironmentPreparation,
    LaunchReadinessPolicy,
    PreparationDelivery,
    ReadinessDecision,
    ReadinessLevel,
    ReadinessMark,
    ReadinessRefused,
    SecretChannel,
    preparation_id,
    readiness_at_least,
)
from mission_control.domain.execution.lanes import (
    PLACEMENT_OF_PROFILE,
    CursorExecutionBinding,
    CursorProviderEnvironment,
    LaneProfileName,
    PreparedSession,
)
from mission_control.domain.frames.contracts import FrameKind

_LOGGER = logging.getLogger(__name__)
_DIGEST_PREFIX = "sha256:"
# SPEC-02 section 4 delivery modes, by the workspace reference a lane's prepare returns. A
# hosted agent API's prepare delivers into the provider's own environment and agent resources
# (`provider_environment:<id>`, read back after the sync, HL-07/HL-08).
_WORKSPACE_CHANNELS: Final[dict[str, str]] = {
    "workspace_lease": "worktree_write",
    "workspace": "worktree_write",
    "branch": "branch_commit",
    "provider_environment": "provider_environment",
}
# The Secret Broker channel each lane delivers its declared secrets through (ADR-0043);
# a lane without a per-run channel leaves them to the owner (SPEC-05).
_SECRET_CHANNELS: Final[dict[str, str]] = {
    "cursor_local": DeliveryChannel.PROCESS_ENVIRONMENT.value,
    "claude_agent_sdk": DeliveryChannel.PROCESS_ENVIRONMENT.value,
    "codex": DeliveryChannel.PROCESS_ENVIRONMENT.value,
    "cursor_cloud": DeliveryChannel.CURSOR_LAUNCH_ENV_VARS.value,
    "claude_managed": DeliveryChannel.PROVIDER_VAULT.value,
    "codex_agents": DeliveryChannel.PROVIDER_VAULT.value,
}
OWNER_PREREQUISITE: Final = "owner_prerequisite"
PROVIDER_ENVIRONMENT: Final = "provider_environment"
REPOSITORY_FILE: Final = "repository_file"
# MO-13: the prepared digest of a hosted lane's base layer and the channel that holds it (a
# saved provider environment, or the repository's committed environment file).
_BASE_LAYERS: Final = (
    ("provider_environment_digest", PROVIDER_ENVIRONMENT),
    ("provider_environment_file_digest", REPOSITORY_FILE),
)

# Observed levels remembered per worker process (oldest forgotten first): a forgotten one costs
# one read and an idempotent advance, never a second mark.
OBSERVED_MEMORY: Final = 4_096


class PreparingAttempt(Protocol):
    """What the gate knows of the attempt (`LaneExecutionIdentity`)."""

    @property
    def request_scope(self) -> str: ...

    @property
    def run_key(self) -> str: ...

    @property
    def attempt_no(self) -> int: ...

    @property
    def lane_profile(self) -> str: ...

    @property
    def harness_execution_id(self) -> UUID: ...


class EnvironmentPreparationRepository(Protocol):
    async def record(
        self, request_scope: str, preparation: EnvironmentPreparation
    ) -> EnvironmentPreparation:
        """Insert `preparation`, or merge it into the stored record of the same identity
        (`EnvironmentPreparation.merged`); returns what is stored."""
        ...

    async def get(
        self, request_scope: str, preparation_id: UUID
    ) -> EnvironmentPreparation | None: ...

    async def for_run(
        self, request_scope: str, run_key: str
    ) -> tuple[EnvironmentPreparation, ...]: ...


class InMemoryEnvironmentPreparationRepository:
    """The repository port over a dict (unit tests and local composition)."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, UUID], EnvironmentPreparation] = {}

    async def record(
        self, request_scope: str, preparation: EnvironmentPreparation
    ) -> EnvironmentPreparation:
        key = (request_scope, preparation.preparation_id)
        stored = self.records.get(key)
        merged = preparation if stored is None else stored.merged(preparation)
        self.records[key] = merged
        return merged

    async def get(self, request_scope: str, preparation_id: UUID) -> EnvironmentPreparation | None:
        return self.records.get((request_scope, preparation_id))

    async def for_run(self, request_scope: str, run_key: str) -> tuple[EnvironmentPreparation, ...]:
        return tuple(
            record
            for (scope, _id), record in self.records.items()
            if scope == request_scope and record.run_key == run_key
        )


def _is_digest(value: str | None) -> bool:
    return value is not None and value.startswith(_DIGEST_PREFIX) and len(value) == 71


def _observed_config_digest(prepared: PreparedSession) -> str | None:
    """The Host Projection digest the lane rendered, else the digest of its projection
    digests (the Cursor lanes name rules, agents and hooks digests separately)."""

    digests = prepared.projection_digests
    if _is_digest(digests.get("projection_digest")):
        return digests["projection_digest"]
    return sha256_digest(sorted(digests.items())) if digests else None


def _deliveries(prepared: PreparedSession) -> tuple[PreparationDelivery, ...]:
    reference = prepared.workspace_ref
    if reference is None:
        return ()
    channel = _WORKSPACE_CHANNELS.get(reference.partition(":")[0])
    if channel is None:
        return ()
    digests = prepared.projection_digests
    items = ["host_projection"]
    if "packet_digest" in digests:
        items.append("context_packet")
    if "setup_digest" in digests:
        items.append("mission_layer")
    deliveries = [PreparationDelivery(item=item, channel=channel, ref=reference) for item in items]
    deliveries += [
        PreparationDelivery(item="base_layer", channel=holder, ref=f"config:{digests[key]}")
        for key, holder in _BASE_LAYERS
        if _is_digest(digests.get(key))
    ]
    return tuple(deliveries)


def _provider_environment(
    binding: ProviderExecutionBinding | CursorExecutionBinding,
) -> CursorProviderEnvironment | None:
    if isinstance(binding, CursorExecutionBinding) and binding.cloud is not None:
        return binding.cloud.provider_environment
    return None


def _secrets(
    lane_profile: str,
    binding: ProviderExecutionBinding | CursorExecutionBinding,
    prepared: PreparedSession,
) -> tuple[SecretChannel, ...]:
    provider = _provider_environment(binding)
    if provider is not None:
        # Only an environment Mission Control synced holds the declared values by name
        # (MO-13); a bound environment, a committed file or generated content leaves them to
        # the owner.
        synced = provider.strategy == "sync" and _is_digest(
            prepared.projection_digests.get("provider_environment_digest")
        )
        channel = DeliveryChannel.CURSOR_ENVIRONMENT.value if synced else OWNER_PREREQUISITE
        return tuple(
            SecretChannel(name=item.name, channel=channel)
            for item in declarations(provider.secret_refs)
            if item.ref.scheme != "mint"
        )
    if not isinstance(binding, ProviderExecutionBinding):
        return ()
    channel = _SECRET_CHANNELS.get(lane_profile, OWNER_PREREQUISITE)
    return tuple(
        SecretChannel(name=item.name, channel=channel)
        for item in declarations(binding.environment.secret_refs)
    )


def declaration_of(
    binding: ProviderExecutionBinding | CursorExecutionBinding,
) -> EnvironmentDeclaration:
    """What a sealed binding declares about its environment: the declaration every preparation
    record under `binding` carries, and the one the start receipt cites. A `cursor_cloud`
    binding with a provider environment declares its kit, secrets and network policy."""

    provider = _provider_environment(binding)
    if provider is not None:
        network = binding.network if isinstance(binding, CursorExecutionBinding) else None
        return EnvironmentDeclaration(
            lane_profile=binding.lane_profile,
            setup_pin=provider.kit_pin,
            secret_refs=provider.secret_refs,
            network_policy_ref=network.digest if network is not None else None,
        )
    environment = binding.environment if isinstance(binding, ProviderExecutionBinding) else None
    return EnvironmentDeclaration.of_binding(binding.lane_profile, environment)


def preparation_of(
    attempt: PreparingAttempt,
    binding: ProviderExecutionBinding | CursorExecutionBinding,
    prepared: PreparedSession,
    *,
    at: datetime,
) -> EnvironmentPreparation:
    """The ladder one `prepare` proves for `binding` (see the module doc)."""

    profile: LaneProfileName = binding.lane_profile
    environment = binding.environment if isinstance(binding, ProviderExecutionBinding) else None
    declaration = declaration_of(binding)
    degradations: list[str] = []
    provider = _provider_environment(binding)
    if provider is not None:
        degradations += [
            f"secrets: {item.name} is minted per run and no cursor_cloud channel delivers it"
            for item in declarations(provider.secret_refs)
            if item.ref.scheme == "mint"
        ]
    elif environment is None:
        degradations.append(
            "environment_binding: mc.cursor_binding carries no environment binding, so no "
            "kit, secret or network declaration reaches this lane"
        )
    record = EnvironmentPreparation(
        preparation_id=preparation_id(
            attempt.request_scope, attempt.harness_execution_id, attempt.attempt_no
        ),
        run_key=attempt.run_key,
        harness_execution_id=attempt.harness_execution_id,
        generation=attempt.attempt_no,
        lane_profile=profile,
        binding_digest=binding.binding_digest,
        declaration=declaration,
        declaration_digest=declaration.digest,
        secrets=_secrets(profile, binding, prepared),
        readiness=ReadinessLevel.DECLARED,
        marks=(
            ReadinessMark(
                level=ReadinessLevel.DECLARED,
                reached_at=at,
                evidence_ref=f"binding:{binding.binding_digest}",
            ),
        ),
        degradations=tuple(degradations),
        discovery=prepared.discovery,
    )
    omissions: list[str] = []
    mission_layer = environment is not None and environment.setup_pin is not None
    record = _climb(record, prepared, mission_layer, omissions, at)
    return record.model_copy(update={"omissions": tuple(omissions)})


def _climb(
    record: EnvironmentPreparation,
    prepared: PreparedSession,
    mission_layer: bool,
    omissions: list[str],
    at: datetime,
) -> EnvironmentPreparation:
    observed = _observed_config_digest(prepared)
    if observed is None:
        omissions.append("rendered: the prepare receipt names no projection digest")
        return record
    record = record.advanced(
        ReadinessLevel.RENDERED, at=at, evidence_ref=f"projection:{observed}"
    ).model_copy(update={"observed_config_digest": observed})
    deliveries = _deliveries(prepared)
    if not deliveries:
        omissions.append("delivered: the prepare receipt names no worktree or branch")
        return record
    record = record.advanced(
        ReadinessLevel.DELIVERED, at=at, evidence_ref=deliveries[0].ref or "workspace"
    ).model_copy(update={"deliveries": deliveries})
    if PLACEMENT_OF_PROFILE[record.lane_profile] == "cloud":
        omissions.append(
            "prepared: a provider-hosted environment is prepared only by the mission layer's "
            "receipt signal"
        )
        return record
    if mission_layer:
        setup_receipt = prepared.projection_digests.get("setup_receipt_digest")
        if not _is_digest(setup_receipt):
            omissions.append(
                f"prepared: Environment Kit {record.declaration.setup_pin} declares a mission "
                "layer and no .mission/setup/receipt.json was received"
            )
            return record
        return record.advanced(
            ReadinessLevel.PREPARED,
            at=at,
            evidence_ref=f"setup_receipt:{setup_receipt}",
            receipt_digest=setup_receipt,
        )
    receipt = prepared.materialization_ref
    if not _is_digest(receipt):
        omissions.append("prepared: the prepare receipt carries no materialization digest")
        return record
    return record.advanced(
        ReadinessLevel.PREPARED, at=at, evidence_ref=f"receipt:{receipt}", receipt_digest=receipt
    )


@dataclass(frozen=True)
class DiscoveryOutcome:
    """What one Discovery Proof did: the stored record, and why it did not raise the ladder
    (`gaps`, empty when the record is `discovered` or above)."""

    preparation: EnvironmentPreparation | None
    gaps: tuple[str, ...] = ()


class EnvironmentNotReady(Exception):
    """The launch policy refused to start the session at this readiness."""

    def __init__(self, preparation: EnvironmentPreparation, decision: ReadinessDecision) -> None:
        super().__init__(decision.reason or "the environment is not ready")
        self.preparation = preparation
        self.decision = decision


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EnvironmentPreparationService:
    """Records preparations, gates session start on the launch policy and raises the ladder
    from observed frames."""

    def __init__(
        self,
        repository: EnvironmentPreparationRepository,
        *,
        policy: LaunchReadinessPolicy | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._policy = policy or LaunchReadinessPolicy()
        self._clock = clock
        # Levels already recorded per preparation in this process: a hook firing on every tool
        # call writes `exercised` once. Bounded, because the worker outlives its executions.
        self._observed: OrderedDict[tuple[UUID, ReadinessLevel], None] = OrderedDict()

    @property
    def policy(self) -> LaunchReadinessPolicy:
        return self._policy

    async def admit_start(
        self,
        attempt: PreparingAttempt,
        binding: ProviderExecutionBinding | CursorExecutionBinding,
        prepared: PreparedSession,
    ) -> EnvironmentPreparation:
        """Record what `prepare` proved; raise `EnvironmentNotReady` when this prepare proved
        less than the minimum, or when the stored record of this generation refuses the
        preparation (fail closed: the unit settles instead of retrying a contradiction).

        The policy decides on this prepare's evidence, not on the stored record: a generation
        prepared again that proves less is refused, although its record keeps the levels an
        earlier prepare reached (they never regress)."""

        observed = preparation_of(attempt, binding, prepared, at=self._clock())
        try:
            record = await self._repository.record(attempt.request_scope, observed)
        except ReadinessRefused as contradiction:
            stored = await self._repository.get(attempt.request_scope, observed.preparation_id)
            record = stored or observed
            minimum = self._policy.minimum(record.lane_profile)
            raise EnvironmentNotReady(
                record,
                ReadinessDecision(
                    admitted=False,
                    minimum=minimum,
                    readiness=record.readiness,
                    reason=f"the recorded environment refuses this preparation: {contradiction}",
                ),
            ) from contradiction
        decision = self._policy.decide(observed)
        if not decision.admitted:
            raise EnvironmentNotReady(record, decision)
        return record

    async def observed(
        self, attempt: PreparingAttempt, kind: FrameKind, *, evidence_ref: str
    ) -> EnvironmentPreparation | None:
        """Raise the ladder from one persisted frame: a hook frame shows a projected control
        ran (`exercised`). Evidence only, never an error."""

        if kind is not FrameKind.HOOK_INVOKED:
            return None
        identity = self._identity(attempt)
        if (identity, ReadinessLevel.EXERCISED) in self._observed:
            return None
        try:
            stored = await self._repository.get(attempt.request_scope, identity)
            if stored is None:
                return None
            if not readiness_at_least(stored.readiness, ReadinessLevel.PREPARED):
                return stored
            advanced = stored.advanced(
                ReadinessLevel.EXERCISED, at=self._clock(), evidence_ref=evidence_ref
            )
            if advanced is not stored:
                stored = await self._repository.record(attempt.request_scope, advanced)
        except Exception:
            # Readiness above `prepared` is evidence: a lost observation never fails the turn.
            _LOGGER.warning("the readiness observation was not recorded", exc_info=True)
            return None
        self._remember(identity, ReadinessLevel.EXERCISED)
        return stored

    async def discovered(
        self, attempt: PreparingAttempt, report: DiscoveryReport, *, evidence_ref: str
    ) -> DiscoveryOutcome:
        """Raise the ladder to `discovered` from one Discovery Proof: a discovery frame, a
        lane's read-back, or a cloud lane's `materialization.observed` signal (its drainer
        names the attempt the signal's run token binds).

        The report is compared with the expectation the prepare recorded (`proof_gaps`); one
        that falls short changes nothing and says why. On a cloud lane with no mission layer a
        provider-side proof also lifts `prepared`, citing the report digest as its receipt.
        Evidence only, never an error."""

        identity = self._identity(attempt)
        try:
            stored = await self._repository.get(attempt.request_scope, identity)
            if stored is None:
                return DiscoveryOutcome(None, ("no environment preparation is recorded",))
            if (identity, ReadinessLevel.DISCOVERED) in self._observed:
                return DiscoveryOutcome(stored)
            gaps = proof_gaps(stored, report)
            if gaps:
                _LOGGER.info(
                    "a %s report does not prove discovery: %s", report.mechanism, "; ".join(gaps)
                )
                return DiscoveryOutcome(stored, gaps)
            at = self._clock()
            advanced = stored
            if not readiness_at_least(stored.readiness, ReadinessLevel.PREPARED):
                advanced = stored.advanced(
                    ReadinessLevel.PREPARED,
                    at=at,
                    evidence_ref=evidence_ref,
                    receipt_digest=report.digest,
                )
            advanced = advanced.advanced(
                ReadinessLevel.DISCOVERED, at=at, evidence_ref=evidence_ref
            )
            if advanced is not stored:
                stored = await self._repository.record(attempt.request_scope, advanced)
        except Exception:
            _LOGGER.warning("the discovery proof was not recorded", exc_info=True)
            return DiscoveryOutcome(None, ("the discovery proof was not recorded",))
        self._remember(identity, ReadinessLevel.DISCOVERED)
        return DiscoveryOutcome(stored)

    @staticmethod
    def _identity(attempt: PreparingAttempt) -> UUID:
        return preparation_id(
            attempt.request_scope, attempt.harness_execution_id, attempt.attempt_no
        )

    def _remember(self, identity: UUID, level: ReadinessLevel) -> None:
        self._observed[(identity, level)] = None
        if len(self._observed) > OBSERVED_MEMORY:
            self._observed.popitem(last=False)


__all__ = [
    "OWNER_PREREQUISITE",
    "DiscoveryOutcome",
    "EnvironmentNotReady",
    "EnvironmentPreparationRepository",
    "EnvironmentPreparationService",
    "InMemoryEnvironmentPreparationRepository",
    "PreparingAttempt",
    "declaration_of",
    "preparation_of",
]
