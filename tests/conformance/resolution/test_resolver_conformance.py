"""Resolver conformance (ADR-0063, design §10): the three registries as fixtures.

Every refusal code is reachable and pointed; unknown lane, application or model refuse; vendor
pairing honours the lane's routes; data class and family admission; the digest is stable across
registration order; a caller cannot obtain a runtime naming a lane the registry does not know.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import pytest

from mission_control.application.resolution.ports import LaneRegistration
from mission_control.application.resolution.registries import (
    ApplicationRegistry,
    DescribeOnlyLane,
    LaneRegistry,
    ModelCatalog,
)
from mission_control.application.resolution.resolver import RuntimeResolver
from mission_control.domain.resolution.configuration import Family, Vendor
from mission_control.domain.resolution.profiles import ApplicationProfile, LaneDeclaration
from mission_control.domain.resolution.resolved import (
    REFUSAL_CODES,
    RefusalCode,
    ResolutionRefused,
    ResolvedRuntime,
)
from mission_control.domain.resolution.selection import RuntimeSelection
from tests.conformance.lanes.compile.fixtures import CANONICAL_ITEMS, canonical_agent
from tests.conformance.lanes.compile.stub import (
    NARROW_DECLARATION,
    STUB_DECLARATION,
    StubLaneAdapter,
)
from tests.conformance.resolution.fixtures import AI_ENGINEER, APPLICATIONS, BIOTECH, MODELS


def _registration(declaration: LaneDeclaration, **adapter: Any) -> LaneRegistration:
    return LaneRegistration(
        profile=declaration.lane_profile,
        declaration=declaration,
        adapter=StubLaneAdapter(declaration, **adapter),
        harness_factory=lambda _deps: DescribeOnlyLane(declaration.describe),
    )


def _resolver(
    *,
    lanes: Iterable[LaneRegistration] | None = None,
    applications: Iterable[ApplicationProfile] = APPLICATIONS,
    allow_unqualified: bool = True,
    backend_contracts: dict[str, tuple[str, str]] | None = None,
) -> RuntimeResolver:
    registry = LaneRegistry()
    for registration in lanes or (
        _registration(STUB_DECLARATION),
        _registration(NARROW_DECLARATION),
    ):
        registry.register(registration)
    return RuntimeResolver(
        registry,
        ApplicationRegistry(applications),
        ModelCatalog(MODELS),
        allow_unqualified_lanes=allow_unqualified,
        backend_contracts=backend_contracts,
    )


def _selection(
    lane: str = "deep_agents",
    *,
    vendor: Vendor = "anthropic",
    family: Family = "GoalDirected",
    application: str = "ai-engineer",
    model_profile: str | None = None,
    required: frozenset[str] = frozenset(),
    lane_options: dict[str, Any] | None = None,
    data_class: str = "internal",
) -> RuntimeSelection:
    agent = canonical_agent(lane, vendor=vendor, required=required)
    if data_class != agent.data_class:
        agent = type(agent).create(
            **{
                **{k: getattr(agent, k) for k in ("lane_profile", "node_ref", "instructions_ref")},
                "model": agent.model,
                "items": agent.items,
                "budgets": agent.budgets,
                "data_class": data_class,
                "data_class_source": agent.data_class_source,
            }
        )
    if model_profile is not None:
        agent = type(agent).create(
            lane_profile=agent.lane_profile,
            node_ref=agent.node_ref,
            instructions_ref=agent.instructions_ref,
            model=agent.model.model_copy(update={"profile": model_profile}),
            items=agent.items,
            budgets=agent.budgets,
            data_class=agent.data_class,
            data_class_source=agent.data_class_source,
        )
    return RuntimeSelection(
        lane_profile=lane,
        model_profile=agent.model.profile,
        family=family,
        node_role="executor",
        application_id=application,
        agent=agent,
        lane_options=lane_options or {},
    )


def _refusal(result: ResolvedRuntime | ResolutionRefused) -> ResolutionRefused:
    assert isinstance(result, ResolutionRefused), result
    return result


# One way to reach each refusal code; every code in the closed vocabulary must appear here.
REACH: dict[RefusalCode, Callable[[], tuple[RuntimeResolver, RuntimeSelection]]] = {
    "LANE_UNKNOWN": lambda: (_resolver(), _selection("codex")),
    "LANE_UNQUALIFIED": lambda: (
        _resolver(
            lanes=(
                _registration(
                    STUB_DECLARATION.model_copy(
                        update={"describe": STUB_DECLARATION.describe.unqualified()}
                    )
                ),
            ),
            allow_unqualified=False,
        ),
        _selection(),
    ),
    "APPLICATION_UNKNOWN": lambda: (_resolver(), _selection(application="genomics")),
    "MODEL_UNKNOWN": lambda: (_resolver(), _selection(model_profile="unknown.default")),
    "MODEL_ROUTE_UNSUPPORTED": lambda: (
        _resolver(),
        _selection("claude_agent_sdk", vendor="openai", family="StageGraph"),
    ),
    "DATA_CLASS_NOT_ADMITTED": lambda: (_resolver(), _selection(data_class="phi")),
    "BLUEPRINT_FAMILY_UNSUPPORTED": lambda: (
        _resolver(),
        _selection("claude_agent_sdk", family="EvaluatorOptimizer"),
    ),
    "ITEM_UNSUPPORTED_ON_LANE": lambda: (
        _resolver(),
        _selection(required=frozenset({"python-uv"})),
    ),
    "ITEM_PIN_UNSERVED": lambda: (
        _resolver(
            lanes=(
                _registration(
                    STUB_DECLARATION,
                    served_pins=frozenset(item.pin for item in CANONICAL_ITEMS[1:]),
                ),
            )
        ),
        _selection(),
    ),
    "APPLY_CONTRACT_MISMATCH": lambda: (
        _resolver(backend_contracts={"aiengineer-postgres": ("knowledge-ingestion-intent", "v2")}),
        _selection(),
    ),
    "LANE_OPTIONS_INVALID": lambda: (_resolver(), _selection(lane_options={"turbo": True})),
}


def test_every_refusal_code_has_a_reachable_case() -> None:
    assert set(REACH) == set(REFUSAL_CODES)


@pytest.mark.parametrize("code", REFUSAL_CODES)
def test_each_refusal_is_reachable_and_pointed(code: RefusalCode) -> None:
    resolver, selection = REACH[code]()
    refusal = _refusal(resolver.resolve(selection))

    assert refusal.code == code
    assert refusal.pointer.startswith("/")
    assert refusal.reason and refusal.remedy
    if code not in {"LANE_UNKNOWN", "APPLICATION_UNKNOWN", "MODEL_UNKNOWN"}:
        assert refusal.lane_profile == selection.lane_profile


def test_a_resolved_runtime_carries_the_catalog_model_and_the_application_side() -> None:
    runtime = _resolver().resolve(_selection(application="biotech"))
    assert isinstance(runtime, ResolvedRuntime)

    assert runtime.agent.model.model_id == "claude-sonnet-5-5"
    assert runtime.lane_binding.lane_profile == "deep_agents"
    assert runtime.knowledge == BIOTECH.knowledge
    assert runtime.outputs == BIOTECH.outputs
    assert runtime.application_revision == BIOTECH.revision


def test_the_catalog_overrides_an_authored_model_id() -> None:
    selection = _selection()
    authored = selection.agent.model.model_copy(update={"model_id": "claude-opus-5-5"})
    agent = type(selection.agent).create(
        lane_profile=selection.agent.lane_profile,
        node_ref=selection.agent.node_ref,
        instructions_ref=selection.agent.instructions_ref,
        model=authored,
        items=selection.agent.items,
        budgets=selection.agent.budgets,
        data_class=selection.agent.data_class,
        data_class_source=selection.agent.data_class_source,
    )
    runtime = _resolver().resolve(selection.model_copy(update={"agent": agent}))
    assert isinstance(runtime, ResolvedRuntime)
    assert runtime.agent.model.model_id == "claude-sonnet-5-5"


@pytest.mark.parametrize("vendor", ["anthropic", "openai"])
def test_vendor_pairing_honours_the_lane_routes(vendor: Vendor) -> None:
    on_deep = _resolver().resolve(_selection(vendor=vendor))
    on_narrow = _resolver().resolve(
        _selection("claude_agent_sdk", vendor=vendor, family="StageGraph")
    )

    assert isinstance(on_deep, ResolvedRuntime)
    route = NARROW_DECLARATION.route(vendor)
    assert route is not None
    if route.verdict == "unsupported":
        assert _refusal(on_narrow).code == "MODEL_ROUTE_UNSUPPORTED"
    else:
        assert isinstance(on_narrow, ResolvedRuntime)


def test_an_unqualified_family_needs_the_local_proof_flag() -> None:
    selection = _selection("claude_agent_sdk", family="GoalDirected")
    assert isinstance(_resolver().resolve(selection), ResolvedRuntime)
    refused = _refusal(_resolver(allow_unqualified=False).resolve(selection))
    assert refused.code in {"LANE_UNQUALIFIED", "BLUEPRINT_FAMILY_UNSUPPORTED"}


def test_the_application_ceiling_bounds_the_data_class() -> None:
    confidential = _selection(data_class="confidential")
    assert isinstance(_resolver().resolve(confidential), ResolvedRuntime)
    narrow = AI_ENGINEER.model_copy(update={"data_class_ceiling": "internal"})
    refused = _refusal(_resolver(applications=(narrow, BIOTECH)).resolve(confidential))
    assert refused.code == "DATA_CLASS_NOT_ADMITTED"
    assert "application ai-engineer" in refused.reason


def test_the_digest_is_stable_across_registration_order() -> None:
    forward = _resolver(
        lanes=(_registration(STUB_DECLARATION), _registration(NARROW_DECLARATION))
    ).resolve(_selection())
    backward = _resolver(
        lanes=(_registration(NARROW_DECLARATION), _registration(STUB_DECLARATION)),
        applications=tuple(reversed(APPLICATIONS)),
    ).resolve(_selection())

    assert isinstance(forward, ResolvedRuntime) and isinstance(backward, ResolvedRuntime)
    assert forward.runtime_digest == backward.runtime_digest
    assert forward == backward


def test_a_runtime_only_harness_is_not_resolvable() -> None:
    registry = LaneRegistry([DescribeOnlyLane(STUB_DECLARATION.describe)])
    resolver = RuntimeResolver(
        registry,
        ApplicationRegistry(APPLICATIONS),
        ModelCatalog(MODELS),
        allow_unqualified_lanes=True,
    )
    assert _refusal(resolver.resolve(_selection())).code == "LANE_UNKNOWN"


def test_registries_refuse_duplicates() -> None:
    with pytest.raises(ValueError, match="already registered"):
        ApplicationRegistry((AI_ENGINEER, AI_ENGINEER))
    with pytest.raises(ValueError, match="already registered"):
        ModelCatalog((MODELS[0], MODELS[0]))
    registry = LaneRegistry()
    registry.register(_registration(STUB_DECLARATION))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(_registration(STUB_DECLARATION))
