"""Network policy resolution (materialization SPEC-01 section 5; MO-15).

A ``mission/v2`` environment declares one ``network`` policy; a lane enforces a *resolved*
one. Resolution turns the declaration into the exact hosts a session may reach:

- ``allowlist``: the declared ``allow`` entries, plus the pinned Environment Kit's required
  egress when ``include_kit`` is set, plus every host Mission Control itself needs;
- ``allow_all``: no list, but the hosts Mission Control needs are still recorded;
- ``none``: nothing, which refuses a run that needs a Mission Control host.

Mission Control needs two hosts of its own. The **Signal Ingress** host is required whenever
the run's callbacks are (``include_signal_ingress``, or a minted ``mint:signal_token`` the
agent would post with; SPEC-04). The **Model Gateway** host is required when a harness reaches
its model through the gateway instead of holding a provider key (a Sandbox Host placement,
SPEC-06 section 2). Both are installation facts the caller supplies; a required host that is
not configured is a refusal, never a silently dropped callback.

The resolved policy is what ``mc.environment_binding.v1`` seals (``network``) and its digest is
the binding's ``network_policy_ref``. Pure: no provider, catalog or installation is contacted.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.mission_environment import (
    DeclaredEnvironment,
    EgressHost,
    KitSelection,
    NetworkMode,
    NetworkPolicy,
    host_covers,
)

SIGNAL_TOKEN_REF: Final = "mint:signal_token"  # noqa: S105 - a broker reference, not a secret

SIGNAL_INGRESS_UNCONFIGURED: Final = "SIGNAL_INGRESS_UNCONFIGURED"
MODEL_GATEWAY_UNCONFIGURED: Final = "MODEL_GATEWAY_UNCONFIGURED"
KIT_EGRESS_UNRESOLVED: Final = "KIT_EGRESS_UNRESOLVED"
NETWORK_FORBIDS_REQUIRED_HOST: Final = "NETWORK_FORBIDS_REQUIRED_HOST"

UnresolvableField = Literal["network", "kit.pin"]


class NetworkPolicyUnresolvable(ValueError):
    """The declared policy cannot become an enforceable one; ``field`` is the manifest
    environment field path an author (or the installation) has to change."""

    def __init__(self, code: str, message: str, field: UnresolvableField = "network") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


class NetworkHosts(BaseModel):
    """The installation's own hosts a run may need: where agents post signals and where a
    sandboxed harness reaches its model. ``None`` means the installation configures none."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_ingress: EgressHost | None = None
    model_gateway: EgressHost | None = None


class ResolvedNetworkPolicy(BaseModel):
    """The exact egress one lane binding runs under.

    ``hosts`` is the effective allowlist (sorted, unique) and is empty unless the mode is
    ``allowlist``. ``signal_ingress`` and ``model_gateway`` name the Mission Control hosts the run
    requires; under ``allowlist`` they are always in ``hosts``. ``kit`` is the Environment Kit
    whose egress the list includes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: NetworkMode
    hosts: tuple[EgressHost, ...] = ()
    signal_ingress: EgressHost | None = None
    model_gateway: EgressHost | None = None
    kit: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def _consistent(self) -> ResolvedNetworkPolicy:
        if self.hosts != tuple(sorted(set(self.hosts))):
            raise ValueError("resolved hosts are sorted and unique")
        if self.mode != "allowlist" and self.hosts:
            raise ValueError(f"a {self.mode} policy carries no host list")
        if self.mode == "none" and self.required:
            raise ValueError("a closed network cannot require a Mission Control host")
        if self.mode == "allowlist" and not set(self.required) <= set(self.hosts):
            raise ValueError("an allowlist includes every required Mission Control host")
        return self

    @property
    def required(self) -> tuple[str, ...]:
        """The Mission Control hosts the run needs, in a stable order."""

        return tuple(host for host in (self.signal_ingress, self.model_gateway) if host)

    @property
    def digest(self) -> str:
        """``network_policy_ref``: the content identity of the resolved policy."""

        return sha256_digest(self)

    def allows(self, host: str) -> bool:
        """Whether this policy admits ``host`` (an exact entry or a ``*.`` suffix)."""

        if self.mode == "allow_all":
            return True
        return any(host_covers(entry, host) for entry in self.hosts)


def requires_signal_ingress(environment: DeclaredEnvironment) -> bool:
    """Whether the run's callbacks need the Signal Ingress host: the policy asks for it, or
    the agent is handed a minted signal token it can only use against the ingress."""

    network = environment.network
    observation = getattr(environment, "observation", None)
    if observation is not None and observation.gates is not None:
        return True
    if network is not None and network.include_signal_ingress:
        return True
    return any(item.ref == SIGNAL_TOKEN_REF for item in environment.secrets or ())


def resolve_network_policy(
    network: NetworkPolicy,
    *,
    kit: KitSelection | None,
    kit_egress: Sequence[str] | None,
    hosts: NetworkHosts,
    signal_ingress: bool,
    model_gateway: bool = False,
) -> ResolvedNetworkPolicy:
    """Resolve ``network`` for one lane binding.

    ``kit_egress`` is the resolved ``requires.egress`` of ``kit`` (``None`` when it could not
    be resolved); it is read only when the policy includes the kit. ``signal_ingress`` and
    ``model_gateway`` say whether the run requires those hosts (see the module docstring).
    """

    required: list[tuple[str, str | None, str]] = []
    if signal_ingress:
        required.append(("Signal Ingress", hosts.signal_ingress, SIGNAL_INGRESS_UNCONFIGURED))
    if model_gateway:
        required.append(("Model Gateway", hosts.model_gateway, MODEL_GATEWAY_UNCONFIGURED))
    for name, host, code in required:
        if host is None:
            raise NetworkPolicyUnresolvable(
                code, f"the run requires the {name} host and the installation configures none"
            )
        if network.mode == "none":
            raise NetworkPolicyUnresolvable(
                NETWORK_FORBIDS_REQUIRED_HOST,
                f"network mode none forbids the {name} host {host} the run requires",
            )
    included_kit = kit if kit is not None and network.include_kit else None
    granted: Iterable[str] = ()
    if network.mode == "allowlist":
        kit_hosts: Sequence[str] = ()
        if included_kit is not None:
            if kit_egress is None:
                raise NetworkPolicyUnresolvable(
                    KIT_EGRESS_UNRESOLVED,
                    f"network.include_kit needs the egress of kit {included_kit.pin}, which "
                    "did not resolve",
                    "kit.pin",
                )
            kit_hosts = kit_egress
        granted = (*network.allow, *kit_hosts, *(host for _, host, _ in required if host))
    return ResolvedNetworkPolicy(
        mode=network.mode,
        hosts=tuple(sorted(set(granted))),
        signal_ingress=hosts.signal_ingress if signal_ingress else None,
        model_gateway=hosts.model_gateway if model_gateway else None,
        kit=included_kit.pin if included_kit is not None and network.mode == "allowlist" else None,
    )


__all__ = [
    "KIT_EGRESS_UNRESOLVED",
    "MODEL_GATEWAY_UNCONFIGURED",
    "NETWORK_FORBIDS_REQUIRED_HOST",
    "SIGNAL_INGRESS_UNCONFIGURED",
    "SIGNAL_TOKEN_REF",
    "NetworkHosts",
    "NetworkPolicyUnresolvable",
    "ResolvedNetworkPolicy",
    "requires_signal_ingress",
    "resolve_network_policy",
]
