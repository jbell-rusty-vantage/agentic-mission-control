"""In-memory :class:`~mission_control.application.ports.knowledge.InvocationLocator` (tests).

Runs map their public key to the ledger mission id; activations are keyed by
``(run_key, unit_key)``. Same contract as the PostgreSQL adapter: an unknown run raises
:class:`~mission_control.domain.knowledge.origin.MissionIdentityUnavailable`, an unknown or
absent unit key resolves no activation.
"""

from __future__ import annotations

from collections.abc import Mapping

from mission_control.domain.knowledge.origin import MissionIdentityUnavailable


class InMemoryInvocationLocator:
    def __init__(
        self,
        missions: Mapping[str, str] | None = None,
        activations: Mapping[tuple[str, str], str] | None = None,
    ) -> None:
        self.missions: dict[str, str] = dict(missions or {})
        self.activations: dict[tuple[str, str], str] = dict(activations or {})
        self.calls: list[tuple[str, str, str | None]] = []

    async def locate(
        self, request_scope: str, run_key: str, unit_key: str | None
    ) -> tuple[str, str | None]:
        self.calls.append((request_scope, run_key, unit_key))
        mission_id = self.missions.get(run_key)
        if mission_id is None:
            raise MissionIdentityUnavailable(f"run {run_key} has no ledger mission id")
        activation = None if unit_key is None else self.activations.get((run_key, unit_key))
        return mission_id, activation


__all__ = ["InMemoryInvocationLocator"]
