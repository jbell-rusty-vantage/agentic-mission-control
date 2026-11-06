"""The lane compile conformance contract (ADR-0063, design §10).

One `CompileConformance` per registered lane, beside that lane's runtime conformance adapter.
The suite (`test_compile_conformance.py`) drives every entry in `registry.COMPILE_LANES` with the
canonical fixtures and checks describe honesty at compile, required-item refusal, purity and
idempotence, vendor routes and that only bytes and receipts cross the port. A lane that cannot
run a check declares a `DeclaredException` citing where it is proven instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Protocol

from mission_control.application.resolution.ports import LaneAdapter
from mission_control.domain.resolution.profiles import LaneDeclaration
from tests.conformance.lanes.contract import DeclaredException


class CompileCheck(StrEnum):
    DESCRIBE_HONESTY = "describe_honesty"
    # Split from describe honesty by OC-R1: whether receipt rows carry the item's pin digest.
    # A lane that receipts the digest of what it materialized declares an exception.
    RECEIPT_ITEM_DIGESTS = "receipt_item_digests"
    REQUIRED_REFUSAL = "required_refusal"
    IDEMPOTENT = "idempotent"
    VENDOR_ROUTES = "vendor_routes"
    OPAQUE_PORT = "opaque_port"


class CompileConformance(Protocol):
    @property
    def profile(self) -> str: ...

    def adapter(self) -> LaneAdapter: ...

    def declaration(self) -> LaneDeclaration: ...

    def options(self) -> Mapping[str, Any]:
        """A valid `lane_options` block for the canonical fixtures."""
        ...

    @property
    def exceptions(self) -> Mapping[CompileCheck, DeclaredException]: ...


__all__ = ["CompileCheck", "CompileConformance"]
