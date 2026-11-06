"""W1 D2: the authorized operator review route reaches KS review, and the wait settles.

Over the deterministic trusted KS double (``tests/fixtures/trusted_knowledge.py``): an official
use decision waits ``review_pending``; the operator review (application handler -> the one KS
review path, ``ReviewRelay``) refuses, typed ``unauthorized_review`` and before anything is sent,
an actor without ``knowledge.review`` and an actor that is the run's producer or one of its
evaluators; KS refuses an unqualified reviewer (also ``unauthorized_review``); a qualified review
creates the exact successor and the bridge's next pass settles and promotes. The HTTP route,
the operator MCP tool and ``missionctl knowledge review`` reach the same handler.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP

from mission_control.application.installations.registry import (
    ApplicationBinding,
    ApplicationRegistry,
    InstallationObservation,
)
from mission_control.application.knowledge.evaluator_plans import AUDITOR_SUBJECT, JUDGE_SUBJECT
from mission_control.application.knowledge.judgment import ReviewRelay
from mission_control.application.knowledge.review import (
    REVIEW_PERMISSION,
    KnowledgeReviewRequest,
    KnowledgeReviewService,
    ResolvedRun,
    ReviewRejected,
)
from mission_control.contracts.knowledge_protocol import Ref
from mission_control.domain.policies.contracts import ActorContext
from mission_control.interfaces.cli import main as cli
from mission_control.interfaces.http.knowledge_reviews import REGISTRY
from mission_control.interfaces.http.knowledge_reviews import router as reviews_router
from mission_control.interfaces.http.mission_control import MissionPrincipal, get_mission_principal
from mission_control.interfaces.mcp.coordinator_server import CoordinatorPrincipal, _principal_call
from mission_control.interfaces.mcp.knowledge_review_tools import (
    KNOWLEDGE_REVIEW_TOOL,
    ScopedKnowledgeReviews,
    register_knowledge_review_tools,
)
from tests.unit.knowledge.test_gateway import INSTALLATION, TENANT
from tests.unit.knowledge.test_trusted_judgment import (
    PRODUCER,
    ScriptedRunner,
    evaluators,
    head_of,
    world,
)
from tests.unit.subscriptions.test_mo43_wake_channels import missionctl  # noqa: F401 (fixture)

pytestmark = pytest.mark.asyncio

REVIEWER = ActorContext(actor_id="operator:reviewer-1", permissions=frozenset({REVIEW_PERMISSION}))
LAUNCHER = "operator:launcher"
OTHER_RUN = "99999999-9999-4999-8999-999999999999"
# The ledger mission every fake run belongs to (the reviewer origin names it, never the run id).
MISSION = "33333333-3333-4333-8333-333333333333"


class Runs:
    """The tenant's runs and who admitted/owns/revised each (``PostgresRunActors`` fake)."""

    def __init__(self, runs: dict[str, frozenset[str]]) -> None:
        self.runs = runs

    async def resolve_run(self, request_scope: str, run_id: str) -> ResolvedRun | None:
        actors = self.runs.get(run_id)
        if actors is None:
            return None
        return ResolvedRun(run_key=run_id, mission_id=MISSION, actors=actors)


async def waiting() -> tuple[Any, Any, Any, Ref, KnowledgeReviewService]:
    """An official use decision waiting on review, and the tenant's review service."""

    w, subject = await world("biotech")
    bridge = w.bridge(ScriptedRunner({"judge": "full_support"}))
    outcome = await bridge.assess(subject, evaluators(w), w.stack.access, w.use())
    assert outcome.state == "waiting" and outcome.reason == "review_pending"
    decision = Ref.model_validate(outcome.resolution.current)  # type: ignore[union-attr]
    service = KnowledgeReviewService(
        ReviewRelay(bridge._gateway, clock=w.clock),  # type: ignore[attr-defined]
        runs=Runs(
            {
                subject.run_id: frozenset({LAUNCHER, "operator:revision-author"}),
                OTHER_RUN: frozenset({LAUNCHER}),
            }
        ),
        assessments=w.stack.store,
        request_scope=w.stack.access.scope,
        issuer="mission-control",
        producer_subject=PRODUCER.subject,
        clock=w.clock,
    )
    return w, subject, bridge, decision, service


def request(w: Any, decision: Ref, **overrides: Any) -> KnowledgeReviewRequest:
    body: dict[str, Any] = {
        "decision": decision.model_dump(mode="json"),
        "outcome": "approve",
        "bound_effect_digest": w.ks.decisions[decision.id]["boundEffectDigest"],
        "rationale": "the cited quotes state the sizes",
        **overrides,
    }
    return KnowledgeReviewRequest.model_validate(body)


async def test_an_authorized_review_resolves_the_wait_and_promotes() -> None:
    w, subject, _bridge, decision, service = await waiting()
    w.ks.grants.add(REVIEWER.actor_id)
    reviewed = await service.review(subject.run_id, request(w, decision), REVIEWER)
    assert reviewed["reviewer"] == REVIEWER.actor_id
    assert reviewed["review"]["successor"]["id"] == f"{decision.id}-rv"
    (review_call,) = [call for call in w.ks.calls if call[0] == "report.review"]
    assert review_call[1:] == ("human_reviewer", REVIEWER.actor_id)
    # Provenance slice 1: the reviewer origin names the run's ledger mission, no activation.
    reviewer = service.reviewer(
        ResolvedRun(run_key=subject.run_id, mission_id=MISSION, actors=frozenset()),
        REVIEWER.actor_id,
        decision,
    )
    origin = reviewer.access.origin
    assert (origin.mission_id, origin.run_id, origin.activation_id) == (
        MISSION,
        subject.run_id,
        None,
    )
    # The settlement's next pass (a fresh process) re-resolves the successor and promotes.
    fresh = w.bridge(ScriptedRunner({}))
    resolved = await fresh.resume(subject, w.stack.access, w.use(), attempt=1)
    assert resolved.state == "settled" and resolved.result == "pass" and resolved.promoted
    assert await head_of(w, subject) == subject.revision.revision_id


@pytest.mark.parametrize(
    "actor",
    [
        ActorContext(actor_id="operator:reviewer-1", permissions=frozenset({"workflow_run.read"})),
        ActorContext(actor_id=PRODUCER.subject, permissions=frozenset({REVIEW_PERMISSION})),
        ActorContext(
            actor_id=f"{PRODUCER.subject}:reconciler", permissions=frozenset({REVIEW_PERMISSION})
        ),
        ActorContext(actor_id=JUDGE_SUBJECT, permissions=frozenset({REVIEW_PERMISSION})),
        ActorContext(actor_id=AUDITOR_SUBJECT, permissions=frozenset({REVIEW_PERMISSION})),
        # S4: whoever launched or revised the run never approves its decision.
        ActorContext(actor_id=LAUNCHER, permissions=frozenset({REVIEW_PERMISSION})),
        ActorContext(
            actor_id="operator:revision-author", permissions=frozenset({REVIEW_PERMISSION})
        ),
    ],
)
async def test_an_unauthorized_review_is_refused_before_anything_is_sent(
    actor: ActorContext,
) -> None:
    w, subject, _bridge, decision, service = await waiting()
    w.ks.grants.add(actor.actor_id)  # even a KS grant does not make the producer a reviewer
    sent = len(w.ks.calls)
    with pytest.raises(ReviewRejected) as refused:
        await service.review(subject.run_id, request(w, decision), actor)
    assert refused.value.code == "unauthorized_review"
    assert len(w.ks.calls) == sent  # nothing reached KS
    assert decision.id not in w.ks.superseded_by


async def test_the_run_is_resolved_and_must_be_the_decisions_run() -> None:
    """S3: an unknown run, another run of the tenant, or another digest of the decision is
    refused before anything is sent (the reviewer origin never names the wrong run)."""

    w, subject, _bridge, decision, service = await waiting()
    w.ks.grants.add(REVIEWER.actor_id)
    sent = len(w.ks.calls)
    cases = (
        ("00000000-0000-4000-8000-000000000000", decision, "not_found"),
        (OTHER_RUN, decision, "decision_not_in_run"),
        (
            subject.run_id,
            decision.model_copy(update={"digest": "sha256:" + "e" * 64}),
            "decision_not_in_run",
        ),
    )
    for run_id, named, code in cases:
        with pytest.raises(ReviewRejected) as refused:
            await service.review(run_id, request(w, named), REVIEWER)
        assert refused.value.code == code
    assert len(w.ks.calls) == sent and decision.id not in w.ks.superseded_by


async def test_the_same_review_twice_is_one_ks_effect() -> None:
    w, subject, _bridge, decision, service = await waiting()
    w.ks.grants.add(REVIEWER.actor_id)
    first = await service.review(subject.run_id, request(w, decision), REVIEWER)
    again = await service.review(subject.run_id, request(w, decision), REVIEWER)
    assert again["review"] == first["review"]
    assert [call for call in w.ks.calls if call[0] == "report.review"] == [
        ("report.review", "human_reviewer", REVIEWER.actor_id)
    ]
    assert list(w.ks.superseded_by) == [decision.id]  # one adjudication, one successor


async def test_ks_refusals_stay_typed() -> None:
    w, subject, _bridge, decision, service = await waiting()
    with pytest.raises(ReviewRejected) as unqualified:
        await service.review(subject.run_id, request(w, decision), REVIEWER)
    assert (unqualified.value.code, unqualified.value.ks_code) == (
        "unauthorized_review",
        "SCOPE_DENIED",
    )
    w.ks.grants.add(REVIEWER.actor_id)
    with pytest.raises(ReviewRejected) as mis_signed:
        await service.review(
            subject.run_id,
            request(w, decision, bound_effect_digest="sha256:" + "f" * 64),
            REVIEWER,
        )
    assert mis_signed.value.code == "review_refused"
    other_tenant = decision.model_copy(update={"tenant": "another-tenant"})
    with pytest.raises(ReviewRejected) as scoped:
        await service.review(subject.run_id, request(w, other_tenant), REVIEWER)
    assert scoped.value.code == "invalid"


def _principal(actor: ActorContext) -> MissionPrincipal:
    return MissionPrincipal(
        installation_id=INSTALLATION,
        application_id="biotech",
        tenant_id=TENANT,
        issuer="https://issuer.invalid",
        audiences=frozenset({"authenticated"}),
        actor=actor,
    )


def _registry() -> ApplicationRegistry:
    registry = ApplicationRegistry(
        (
            ApplicationBinding.seal(
                application_id="biotech",
                installation_id=UUID(INSTALLATION),
                binding_version="1",
                supabase_project_ref="project",
                database_secret_ref="TEST_DATABASE_URL",
                accepted_issuers={"https://issuer.invalid"},
                accepted_audiences={"authenticated"},
                required_component_version="1",
            ),
        )
    )
    registry.observe(
        "biotech",
        InstallationObservation(UUID(INSTALLATION), "biotech", "project", frozenset({"1"})),
    )
    return registry


def review_app(service: KnowledgeReviewService, actor: ActorContext) -> FastAPI:
    app = FastAPI()
    app.state.mission_control_registry = _registry()
    app.include_router(reviews_router)
    app.dependency_overrides[get_mission_principal] = lambda: _principal(actor)
    setattr(app.state, REGISTRY, {(UUID(INSTALLATION), "biotech", UUID(TENANT)): service})
    return app


async def test_http_route_relays_and_refuses_typed() -> None:
    w, subject, _bridge, decision, service = await waiting()
    w.ks.grants.add(REVIEWER.actor_id)
    body = request(w, decision).model_dump(mode="json")
    path = f"/v1/applications/biotech/runs/{subject.run_id}/knowledge-reviews"
    outsider = ActorContext(actor_id="operator:other", permissions=frozenset())
    with TestClient(review_app(service, outsider)) as http:
        refused = http.post(path, json=body)
    assert refused.status_code == 403
    assert refused.json()["detail"]["code"] == "unauthorized_review"
    with TestClient(review_app(service, REVIEWER)) as http:
        reviewed = http.post(path, json=body)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review"]["successor"]["id"] == f"{decision.id}-rv"


class _Resolver:
    def __init__(self, actor: ActorContext, scope: str) -> None:
        self.principal = CoordinatorPrincipal(
            actor_id=actor.actor_id,
            tenant_scope=scope,
            roles=frozenset(),
            permissions=actor.permissions,
            request_scope=scope,
        )

    async def resolve(self, _context: Any) -> CoordinatorPrincipal:
        return self.principal


async def test_operator_mcp_tool_reaches_the_same_handler() -> None:
    w, subject, _bridge, decision, service = await waiting()
    scope = service.request_scope
    body = request(w, decision).model_dump(mode="json")
    judge = ActorContext(actor_id=JUDGE_SUBJECT, permissions=REVIEWER.permissions)
    for actor, ok in ((judge, False), (REVIEWER, True)):
        w.ks.grants.add(actor.actor_id)
        server = FastMCP("knowledge-review-test")
        register_knowledge_review_tools(
            server,
            ScopedKnowledgeReviews({scope: service}),
            _Resolver(actor, scope),
            call=_principal_call,
        )
        async with Client(server) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert KNOWLEDGE_REVIEW_TOOL in names
            answer = await client.call_tool(
                KNOWLEDGE_REVIEW_TOOL, {"run_id": subject.run_id, "request": body}
            )
        assert answer.data["ok"] is ok, answer.data
        if not ok:
            assert answer.data["error"]["code"] == "FORBIDDEN"
            assert answer.data["error"]["details"]["code"] == "unauthorized_review"


async def test_missionctl_knowledge_review_posts_the_same_body(
    missionctl: Any,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    w, subject, _bridge, decision, service = await waiting()
    w.ks.grants.add(REVIEWER.actor_id)
    missionctl(review_app(service, REVIEWER))
    decision_file = tmp_path / "decision.json"
    decision_file.write_text(json.dumps(decision.model_dump(mode="json")), encoding="utf-8")
    argv = [
        "knowledge",
        "review",
        subject.run_id,
        "--decision-file",
        str(decision_file),
        "--outcome",
        "approve",
        "--bound-effect-digest",
        w.ks.decisions[decision.id]["boundEffectDigest"],
        "--rationale",
        "the cited quotes state the sizes",
    ]
    assert cli.main(argv) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["review"]["successor"]["id"] == f"{decision.id}-rv"


async def test_a_missing_runtime_grant_fails_closed_typed() -> None:
    """B1: a runtime login without SELECT on the run tables is `review_unavailable`, never 500."""

    from mission_control.application.knowledge.review import RunActorsUnavailable

    class Ungranted:
        async def resolve_run(self, request_scope: str, run_id: str) -> ResolvedRun | None:
            raise RunActorsUnavailable("the runtime login lacks SELECT on mission_control.mission")

    w, subject, _bridge, decision, service = await waiting()
    service._runs = Ungranted()  # type: ignore[assignment]
    with pytest.raises(ReviewRejected) as refused:
        await service.review(subject.run_id, request(w, decision), REVIEWER)
    assert refused.value.code == "review_unavailable"
    assert "mission_control.mission" in str(refused.value)


async def test_the_evaluator_attempt_reset_route_is_authorized_and_audited() -> None:
    """W1 fix G S2: the operator reset after ``evaluator_attempts_exhausted`` (same authorization
    as a review: permission, never the launcher), audited on the superseding wait."""

    from mission_control.application.knowledge.judgment import (
        RESET_FINDING,
        EvaluatorAttemptReset,
        EvaluatorUnavailable,
    )

    w, subject = await world("biotech", review_required=False)

    class Failing(ScriptedRunner):
        async def evaluate(self, evaluator: Any, subject: Any) -> Any:
            self.calls.append(evaluator.role)
            raise EvaluatorUnavailable("judge run failed: ValidationError", billed=True)

    exhausted = await w.bridge(Failing({})).assess(subject, evaluators(w), w.stack.access, w.use())
    assert exhausted.exhausted
    service = KnowledgeReviewService(
        ReviewRelay(w.bridge(ScriptedRunner({}))._gateway, clock=w.clock),  # type: ignore[attr-defined]
        runs=Runs({subject.run_id: frozenset({LAUNCHER})}),
        assessments=w.stack.store,
        request_scope=w.stack.access.scope,
        issuer="mission-control",
        producer_subject=PRODUCER.subject,
        clock=w.clock,
        resets=EvaluatorAttemptReset(w.stack.outputs, w.stack.store, clock=w.clock),
    )
    path = f"/v1/applications/biotech/runs/{subject.run_id}/evaluator-attempt-resets"
    body = {"revision_id": subject.revision.revision_id, "role": "judge", "reason": "fixed"}
    launcher = ActorContext(actor_id=LAUNCHER, permissions=frozenset({REVIEW_PERMISSION}))
    outsider = ActorContext(actor_id="operator:other", permissions=frozenset())
    for actor in (outsider, launcher):
        with TestClient(review_app(service, actor)) as http:
            refused = http.post(path, json=body)
        assert (
            refused.status_code == 403 and refused.json()["detail"]["code"] == "unauthorized_review"
        )
    with TestClient(review_app(service, REVIEWER)) as http:
        idle = http.post(path, json={**body, "role": "auditor"})
        reset = http.post(path, json=body)
        again = http.post(path, json=body)
    assert idle.status_code == 409 and idle.json()["detail"]["code"] == "nothing_to_reset"
    assert reset.status_code == 200, reset.text
    assert reset.json()["operator"] == REVIEWER.actor_id
    assert again.status_code == 409
    rows = await w.stack.store.output_assessments(w.stack.access.scope, subject.run_id)
    (audited,) = [row for row in rows if row.assessment_id == reset.json()["assessment_id"]]
    assert any(f.code == RESET_FINDING and REVIEWER.actor_id in f.message for f in audited.findings)
