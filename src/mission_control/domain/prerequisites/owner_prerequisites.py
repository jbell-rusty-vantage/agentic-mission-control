"""`mc.owner_prerequisite.v1`: what only the owner can do, and how far it is proven
(materialization-observation SPEC-05 section 1; ADR-0047).

An Owner Prerequisite is a human-only step a lane needs before a mission spawns: a plan, a
dashboard setting, a provider environment created in a web UI, an interactive login. The
record carries

* the **steps** in order, plain text or a paste block naming a **generated content** item by
  ``content_ref``. Generated content is rendered by Mission Control from the same Environment
  Kit and network policy the mission binds, so what the owner pastes is what the binding
  expects; ``generated_from`` names that kit pin and policy digest, and every item carries the
  sha256 of its exact text. It names variables and secret references only, never a value;
* the **verification method**, strongest first: ``api_probe`` (Mission Control reads provider
  state), ``probe_mission`` (a minimal real launch emits a readiness signal), ``file_check`` (a
  local file or credential exists and has not expired), ``attestation`` (the owner says so; the
  weakest, recorded as such);
* its **freshness**: when it must be revalidated, when a credential expires and how early that
  is flagged, and which binding inputs make the generated content drift.

:class:`OwnerPrerequisiteRecord` is what the store keeps per installation scope: the current
definition, its state (``unmet``, ``attested``, ``verified``) and the evidence that set it.
Evidence cites the definition digest it proved; re-registering a changed definition keeps the
evidence, which then no longer matches and drifts. :func:`assess_prerequisite` is the pure
freshness rule a preflight applies before launch.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.authoring.canonical import stable_json_digest
from mission_control.domain.capabilities.bundles import sha256_hex
from mission_control.domain.capabilities.host_support import LaneProfile
from mission_control.domain.execution.bindings import EnvironmentBinding
from mission_control.domain.execution.lanes import DIGEST_PATTERN

OWNER_PREREQUISITE_SCHEMA: Final = "mc.owner_prerequisite.v1"
OWNER_PREREQUISITE_RECORD_SCHEMA: Final = "mc.owner_prerequisite_record.v1"
# `<lane or provider>.<area>[.<subject>]`, e.g. `claude_cloud.environment.envkit-python-uv-node-3`.
PREREQUISITE_ID_PATTERN: Final = r"^[a-z][a-z0-9_]{0,63}(?:\.[a-z0-9][a-z0-9_-]{0,127}){1,3}$"
CONTENT_REF_PATTERN: Final = r"^generated/[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*$"
# An attested value is a provider identifier (an `env_...` id, an `ENV_ID`), never a secret.
ATTESTED_VALUE_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$"
MAX_GENERATED_CHARS: Final = 262_144
DEFAULT_WARN_BEFORE: Final = timedelta(days=7)

PrerequisiteProvider = Literal["cursor", "anthropic", "openai", "github", "mission_control"]
GeneratedMediaType = Literal[
    "text/plain", "text/x-shellscript", "text/markdown", "application/json"
]
DriftInput = Literal["kit_digest", "policy_digest"]


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PrerequisiteScope(StrEnum):
    """Where the step is done: once per account or org, per repository, per provider
    environment, per worker host or per human user."""

    ACCOUNT = "account"
    ORG = "org"
    REPO = "repo"
    ENVIRONMENT = "environment"
    HOST = "host"
    USER = "user"


class VerificationMethod(StrEnum):
    """How a prerequisite is proven, strongest first."""

    API_PROBE = "api_probe"
    PROBE_MISSION = "probe_mission"
    FILE_CHECK = "file_check"
    ATTESTATION = "attestation"

    @property
    def verifies(self) -> bool:
        """Whether this method can make a prerequisite ``verified``; an attestation only
        ever makes it ``attested``."""

        return self is not VerificationMethod.ATTESTATION


class LaneBlock(_Contract):
    """The lane features an unmet prerequisite blocks."""

    lane: LaneProfile
    features: tuple[str, ...] = Field(default=("launch",), min_length=1)


class PasteStep(_Contract):
    """A step that pastes one generated content item into a provider field."""

    paste: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    content_ref: str = Field(pattern=CONTENT_REF_PATTERN, max_length=256)


PrerequisiteStep = PasteStep | str


class Verification(_Contract):
    """``probe`` names what runs the check: a probe mission pin, a provider read, a file."""

    method: VerificationMethod
    probe: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def _probe_named(self) -> Verification:
        if self.method is not VerificationMethod.ATTESTATION and self.probe is None:
            raise ValueError(f"a {self.method.value} verification names its probe")
        return self


class Freshness(_Contract):
    """``revalidate_after`` makes verified evidence stale (a warning); ``expires_after``
    is a credential's hard lifetime, flagged ``warn_before`` it ends and blocking after;
    ``on_change_of`` names the binding inputs whose change makes generated content drift."""

    revalidate_after: timedelta | None = None
    expires_after: timedelta | None = None
    warn_before: timedelta = DEFAULT_WARN_BEFORE
    on_change_of: tuple[DriftInput, ...] = ()

    @model_validator(mode="after")
    def _positive(self) -> Freshness:
        for name in ("revalidate_after", "expires_after"):
            value = getattr(self, name)
            if value is not None and value <= timedelta(0):
                raise ValueError(f"{name} is a positive duration")
        if self.warn_before < timedelta(0):
            raise ValueError("warn_before is not negative")
        if len(set(self.on_change_of)) != len(self.on_change_of):
            raise ValueError("on_change_of must not repeat")
        return self


class GeneratedFrom(_Contract):
    """The binding inputs generated content was rendered from: the Environment Kit pin and
    the resolved network policy digest (``mc.environment_binding.v1`` ``setup_pin`` and
    ``network_policy_ref``)."""

    kit: str | None = Field(default=None, min_length=1, max_length=512)
    policy_digest: str | None = Field(default=None, pattern=DIGEST_PATTERN)

    @classmethod
    def of_binding(cls, binding: EnvironmentBinding) -> GeneratedFrom:
        return cls(kit=binding.setup_pin, policy_digest=binding.network_policy_ref)

    def drift(self, bound: GeneratedFrom, inputs: Iterable[DriftInput]) -> tuple[str, ...]:
        """Why content rendered from ``self`` no longer matches ``bound``."""

        reasons: list[str] = []
        for item in inputs:
            if item == "kit_digest" and self.kit != bound.kit:
                reasons.append(f"rendered from kit {self.kit}; the binding pins {bound.kit}")
            if item == "policy_digest" and self.policy_digest != bound.policy_digest:
                reasons.append(
                    f"rendered from network policy {self.policy_digest}; the binding seals "
                    f"{bound.policy_digest}"
                )
        return tuple(reasons)


def content_digest(content: str) -> str:
    return "sha256:" + sha256_hex(content.encode("utf-8"))


class GeneratedContent(_Contract):
    """One paste-ready item and the digest of its exact text."""

    ref: str = Field(pattern=CONTENT_REF_PATTERN, max_length=256)
    media_type: GeneratedMediaType
    content: str = Field(min_length=1, max_length=MAX_GENERATED_CHARS)
    digest: str = Field(pattern=DIGEST_PATTERN)

    @classmethod
    def render(cls, ref: str, media_type: GeneratedMediaType, content: str) -> GeneratedContent:
        return cls(ref=ref, media_type=media_type, content=content, digest=content_digest(content))

    @model_validator(mode="after")
    def _digest_is_content(self) -> GeneratedContent:
        if self.digest != content_digest(self.content):
            raise ValueError(f"{self.ref}: digest does not match the generated content")
        return self


class OwnerPrerequisite(_Contract):
    """``mc.owner_prerequisite.v1`` (see the module doc)."""

    schema_version: Literal["mc.owner_prerequisite.v1"] = OWNER_PREREQUISITE_SCHEMA
    id: str = Field(pattern=PREREQUISITE_ID_PATTERN, max_length=256)
    provider: PrerequisiteProvider
    scope: PrerequisiteScope
    title: str = Field(min_length=1, max_length=256)
    why: str = Field(min_length=1, max_length=1_024)
    blocks: tuple[LaneBlock, ...] = Field(min_length=1)
    steps: tuple[PrerequisiteStep, ...] = Field(min_length=1)
    verify: Verification
    freshness: Freshness = Field(default_factory=Freshness)
    generated_from: GeneratedFrom | None = None
    generated: tuple[GeneratedContent, ...] = ()

    @model_validator(mode="after")
    def _content_refs_resolve(self) -> OwnerPrerequisite:
        for step in self.steps:
            if isinstance(step, str) and not step.strip():
                raise ValueError("a text step is not blank")
        refs = [item.ref for item in self.generated]
        if len(refs) != len(set(refs)):
            raise ValueError("generated content refs are unique")
        pasted = {step.content_ref for step in self.steps if isinstance(step, PasteStep)}
        if missing := sorted(pasted - set(refs)):
            raise ValueError(f"steps paste content that is not generated: {', '.join(missing)}")
        if unused := sorted(set(refs) - pasted):
            raise ValueError(f"generated content no step pastes: {', '.join(unused)}")
        if self.generated and self.generated_from is None:
            raise ValueError("generated content names the binding inputs it was generated_from")
        if self.freshness.on_change_of and self.generated_from is None:
            raise ValueError("on_change_of needs generated_from to compare against")
        return self

    @property
    def digest(self) -> str:
        """The definition's content identity; evidence cites it."""

        return stable_json_digest(self)

    @property
    def content_digests(self) -> dict[str, str]:
        return {item.ref: item.digest for item in self.generated}

    def content(self, ref: str) -> GeneratedContent:
        return next(item for item in self.generated if item.ref == ref)


# --- The stored record ----------------------------------------------------------------------


class PrerequisiteState(StrEnum):
    UNMET = "unmet"
    ATTESTED = "attested"
    VERIFIED = "verified"


class PrerequisiteEvidence(_Contract):
    """What set a prerequisite's state: the method, the definition it proved and, for a
    credential, when it expires. ``value`` is an attested identifier, never a secret."""

    method: VerificationMethod
    definition_digest: str = Field(pattern=DIGEST_PATTERN)
    recorded_at: AwareDatetime
    evidence_ref: str | None = Field(default=None, min_length=1, max_length=1_024)
    value: str | None = Field(default=None, pattern=ATTESTED_VALUE_PATTERN)
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _cites_its_proof(self) -> PrerequisiteEvidence:
        if self.method.verifies and self.evidence_ref is None:
            raise ValueError(f"{self.method.value} evidence cites its evidence_ref")
        if self.expires_at is not None and self.expires_at <= self.recorded_at:
            raise ValueError("evidence expires after it is recorded")
        return self


class EvidenceRefused(ValueError):
    """Evidence for a definition other than the stored one."""


class OwnerPrerequisiteRecord(_Contract):
    """One prerequisite as an installation scope stores it."""

    schema_version: Literal["mc.owner_prerequisite_record.v1"] = OWNER_PREREQUISITE_RECORD_SCHEMA
    prerequisite: OwnerPrerequisite
    definition_digest: str = Field(pattern=DIGEST_PATTERN)
    state: PrerequisiteState = PrerequisiteState.UNMET
    evidence: PrerequisiteEvidence | None = None

    @classmethod
    def of(cls, prerequisite: OwnerPrerequisite) -> OwnerPrerequisiteRecord:
        """A newly registered, unmet prerequisite."""

        return cls(prerequisite=prerequisite, definition_digest=prerequisite.digest)

    @model_validator(mode="after")
    def _state_follows_evidence(self) -> OwnerPrerequisiteRecord:
        if self.definition_digest != self.prerequisite.digest:
            raise ValueError("definition_digest does not match the prerequisite")
        if self.state != self.state_of(self.evidence):
            raise ValueError(f"a {self.state.value} prerequisite carries matching evidence")
        return self

    @staticmethod
    def state_of(evidence: PrerequisiteEvidence | None) -> PrerequisiteState:
        if evidence is None:
            return PrerequisiteState.UNMET
        return (
            PrerequisiteState.VERIFIED if evidence.method.verifies else PrerequisiteState.ATTESTED
        )

    @property
    def id(self) -> str:
        return self.prerequisite.id

    def registered(self, prerequisite: OwnerPrerequisite) -> OwnerPrerequisiteRecord:
        """The record with ``prerequisite`` as its current definition. Evidence is kept: it
        cites the definition it proved, so a changed definition drifts until proven again."""

        if prerequisite.id != self.id:
            raise ValueError(f"{prerequisite.id} is not {self.id}")
        if prerequisite == self.prerequisite:
            return self
        return self.model_copy(
            update={"prerequisite": prerequisite, "definition_digest": prerequisite.digest}
        )

    def evidenced(self, evidence: PrerequisiteEvidence) -> OwnerPrerequisiteRecord:
        if evidence.definition_digest != self.definition_digest:
            raise EvidenceRefused(
                f"{self.id}: the evidence proves definition {evidence.definition_digest}, the "
                f"stored definition is {self.definition_digest}"
            )
        return self.model_copy(update={"evidence": evidence, "state": self.state_of(evidence)})


# --- Assessment -----------------------------------------------------------------------------


class PrerequisiteStanding(StrEnum):
    """What a preflight reports. ``expiring`` and ``stale`` warn; the rest block launch."""

    MET = "met"
    EXPIRING = "expiring"
    STALE = "stale"
    DRIFTED = "drifted"
    EXPIRED = "expired"
    UNMET = "unmet"


BLOCKING_STANDINGS: Final[frozenset[PrerequisiteStanding]] = frozenset(
    {PrerequisiteStanding.DRIFTED, PrerequisiteStanding.EXPIRED, PrerequisiteStanding.UNMET}
)


class PrerequisiteAssessment(_Contract):
    prerequisite_id: str = Field(pattern=PREREQUISITE_ID_PATTERN)
    standing: PrerequisiteStanding
    state: PrerequisiteState
    method: VerificationMethod | None = None
    expires_at: AwareDatetime | None = None
    reasons: tuple[str, ...] = ()

    @property
    def blocking(self) -> bool:
        return self.standing in BLOCKING_STANDINGS


def assess_prerequisite(
    record: OwnerPrerequisiteRecord,
    *,
    now: datetime,
    bound: GeneratedFrom | None = None,
) -> PrerequisiteAssessment:
    """The record's standing at ``now`` for a launch bound to ``bound`` (the binding's kit pin
    and network policy digest; ``None`` when the caller has no binding to compare)."""

    prerequisite = record.prerequisite
    evidence = record.evidence

    def standing(value: PrerequisiteStanding, *reasons: str) -> PrerequisiteAssessment:
        return PrerequisiteAssessment(
            prerequisite_id=prerequisite.id,
            standing=value,
            state=record.state,
            method=None if evidence is None else evidence.method,
            expires_at=None if evidence is None else evidence.expires_at,
            reasons=reasons,
        )

    if evidence is None:
        return standing(PrerequisiteStanding.UNMET, "not attested or verified")
    drift: list[str] = []
    if evidence.definition_digest != record.definition_digest:
        drift.append(
            f"the steps or generated content changed since it was {record.state.value}; repeat them"
        )
    if bound is not None and prerequisite.generated_from is not None:
        drift.extend(prerequisite.generated_from.drift(bound, prerequisite.freshness.on_change_of))
    if drift:
        return standing(PrerequisiteStanding.DRIFTED, *drift)
    if evidence.expires_at is not None:
        if now >= evidence.expires_at:
            return standing(PrerequisiteStanding.EXPIRED, f"expired at {evidence.expires_at}")
        if now >= evidence.expires_at - prerequisite.freshness.warn_before:
            return standing(PrerequisiteStanding.EXPIRING, f"expires at {evidence.expires_at}")
    # A declared probe proves a particular fact; another method cannot substitute
    # for it merely because it is ranked stronger in the general documentation.
    if prerequisite.verify.method.verifies and evidence.method != prerequisite.verify.method:
        return standing(
            PrerequisiteStanding.UNMET,
            f"requires {prerequisite.verify.method.value} verification; "
            f"only {evidence.method.value} evidence is recorded",
        )
    revalidate = prerequisite.freshness.revalidate_after
    if revalidate is not None and now >= evidence.recorded_at + revalidate:
        return standing(
            PrerequisiteStanding.STALE,
            f"last {record.state.value} at {evidence.recorded_at}; revalidate every {revalidate}",
        )
    return standing(PrerequisiteStanding.MET)


__all__ = [
    "BLOCKING_STANDINGS",
    "CONTENT_REF_PATTERN",
    "OWNER_PREREQUISITE_RECORD_SCHEMA",
    "OWNER_PREREQUISITE_SCHEMA",
    "PREREQUISITE_ID_PATTERN",
    "DriftInput",
    "EvidenceRefused",
    "Freshness",
    "GeneratedContent",
    "GeneratedFrom",
    "GeneratedMediaType",
    "LaneBlock",
    "OwnerPrerequisite",
    "OwnerPrerequisiteRecord",
    "PasteStep",
    "PrerequisiteAssessment",
    "PrerequisiteEvidence",
    "PrerequisiteProvider",
    "PrerequisiteScope",
    "PrerequisiteStanding",
    "PrerequisiteState",
    "PrerequisiteStep",
    "Verification",
    "VerificationMethod",
    "assess_prerequisite",
    "content_digest",
]
