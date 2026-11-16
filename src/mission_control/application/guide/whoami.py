"""Who the caller is: the verified principal and its operator grant, as this server reads them.

A Coordinator that has only the MCP server cannot read a deployment file, so the server says
which actor it authenticated, in which tenant, which permissions the operator grant gives it,
which sponsorship and approval refs it may bind (a fork names one as `sponsorship_ref`), and
which `reviewers` entries of a Human Task it satisfies (`reviews_as`: its actor id and every
`reviewer:<name>` permission). It reads the verified principal only: nothing a request body or
a token's editable metadata says, and nothing about another principal, so it needs an
authenticated caller and no further permission.

`server` adds what this process can and cannot do for a control a lane declares: a lane whose
saved state it cannot read names the deployment prerequisite here, the same sentence the
`state-as-of` refusal carries, so a Coordinator knows before it asks.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from mission_control.application.execution.harness.time_travel import TimeTravelRegistry
from mission_control.application.resolution.registries import LaneRegistry
from mission_control.domain.programs.human_gate import reviewer_roles, reviews_as

WHOAMI_SCHEMA: Final = "mc.whoami.v1"


@dataclass(frozen=True, slots=True)
class PrincipalFacts:
    """The verified principal as a transport hands it over (HTTP bearer or MCP gate)."""

    actor_id: str
    installation_id: str
    application_id: str
    tenant_id: str
    request_scope: str
    permissions: frozenset[str]
    authority_refs: frozenset[str] = frozenset()
    sponsorship_refs: frozenset[str] = frozenset()
    approval_refs: frozenset[str] = frozenset()


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LaneTimeTravel(_Frozen):
    """One bound lane's time travel on this server: what the lane declares and whether this
    process composed the reader behind `state-as-of`."""

    lane_profile: str
    declared_read: str | None = None
    declared_fork: str | None = None
    state_as_of: Literal["readable", "not_composed", "not_declared"]
    # What the deployment must provide before `state-as-of` answers for this lane.
    prerequisite: str | None = Field(default=None, exclude_if=lambda value: value is None)


class ServerFacts(_Frozen):
    time_travel: tuple[LaneTimeTravel, ...] = ()
    # Whether this server composes external capability discovery and candidate inspection.
    external_discovery: Literal["composed", "not_composed"] = "not_composed"
    # What this process still needs before every composed discovery call answers.
    external_discovery_prerequisite: str | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class WhoAmI(_Frozen):
    schema_version: Literal["mc.whoami.v1"] = WHOAMI_SCHEMA
    actor_id: str
    application_id: str
    installation_id: str
    tenant_id: str
    request_scope: str
    permissions: tuple[str, ...]
    authority_refs: tuple[str, ...]
    # The sponsorships this principal may bind: a fork's `sponsorship_ref` is one of them.
    sponsorship_refs: tuple[str, ...]
    approval_refs: tuple[str, ...]
    # `r` for every permission `reviewer:r`.
    reviewer_roles: tuple[str, ...]
    # Every Human Task `reviewers` entry this principal satisfies: its actor id and its roles.
    reviews_as: tuple[str, ...]
    server: ServerFacts | None = Field(default=None, exclude_if=lambda value: value is None)


def server_facts(
    lanes: LaneRegistry,
    time_travel: TimeTravelRegistry | None,
    *,
    external_discovery: bool = False,
    external_discovery_prerequisite: str | None = None,
) -> ServerFacts:
    """What this process composed for the controls its bound lanes declare."""

    rows: list[LaneTimeTravel] = []
    for profile in lanes.profiles():
        declared = lanes.describe(profile).time_travel
        if declared is None:
            rows.append(LaneTimeTravel(lane_profile=profile, state_as_of="not_declared"))
            continue
        readable = time_travel is not None and time_travel.supports(profile)
        rows.append(
            LaneTimeTravel(
                lane_profile=profile,
                declared_read=str(declared.read),
                declared_fork=str(declared.fork),
                state_as_of="readable" if readable else "not_composed",
                prerequisite=None
                if readable
                else (time_travel.prerequisite(profile) if time_travel is not None else None)
                or "this process composed no time travel reader for the lane",
            )
        )
    return ServerFacts(
        time_travel=tuple(rows),
        external_discovery="composed" if external_discovery else "not_composed",
        external_discovery_prerequisite=(
            external_discovery_prerequisite if external_discovery else None
        ),
    )


def whoami(principal: PrincipalFacts, server: ServerFacts | None = None) -> WhoAmI:
    """The caller's identity and grant, sorted so two calls answer the same document."""

    return WhoAmI(
        actor_id=principal.actor_id,
        application_id=principal.application_id,
        installation_id=principal.installation_id,
        tenant_id=principal.tenant_id,
        request_scope=principal.request_scope,
        permissions=_sorted(principal.permissions),
        authority_refs=_sorted(principal.authority_refs),
        sponsorship_refs=_sorted(principal.sponsorship_refs),
        approval_refs=_sorted(principal.approval_refs),
        reviewer_roles=reviewer_roles(principal.permissions),
        reviews_as=reviews_as(principal.actor_id, principal.permissions),
        server=server,
    )


def _sorted(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(values))


__all__ = [
    "WHOAMI_SCHEMA",
    "LaneTimeTravel",
    "PrincipalFacts",
    "ServerFacts",
    "WhoAmI",
    "server_facts",
    "whoami",
]
