"""M02/K07 gateway seam (SPRINT-V-DESIGN §9): journal first, receipt first, fresh credentials.

Credentials are real: an Ed25519 issuer (active + retiring key) mints compact JWS and the fake
binding verifies every call with the pinned JWKS, issuer, audience, window and single-use
``jti`` before applying K01 dispatch admission (origin, effect scope, effect-scoped recovery).
Every scenario runs twice: against the fake directly (``direct``) and through the real HTTP
client over the in-process K01 HTTP surface (``http``), so the transport adds no semantics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from mission_control.adapters.knowledge.credentials import (
    CredentialRejected,
    generate_signing_key,
)
from mission_control.application.knowledge.access import (
    CredentialMismatch,
    InvocationAccess,
    RecoveryAccess,
    RecoveryGrant,
    to_wire_origin,
    verify_credential_claims,
)
from mission_control.application.knowledge.gateway import KnowledgeGateway
from mission_control.application.knowledge.operations import KnowledgeCall, KnowledgeRefused
from mission_control.application.ports.knowledge import CredentialRequest, KnowledgeProtocolRefusal
from mission_control.contracts.knowledge_protocol import (
    Governors,
    Origin,
    bind_effect,
    bound_effect_digest,
    canonical_json,
    digest_bytes,
)
from mission_control.contracts.knowledge_protocol_results import CredentialClaims
from mission_control.domain.knowledge.effects import JournalState
from mission_control.domain.knowledge.origin import InvocationOrigin
from tests.fixtures.knowledge_binding import (
    AUDIENCE,
    BINDING,
    FakeKnowledgeBinding,
    InMemoryKnowledgeHandleStore,
    InMemoryKnowledgeJournal,
    Issuer,
    RecordingMinter,
    SteppingClock,
    http_client_over,
    knowledge_port,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "knowledge_protocol"
GOLDEN = json.loads(
    (FIXTURES / "knowledge-operation-protocol.v2.golden.json").read_text(encoding="utf-8")
)
VECTORS = {vector["id"]: vector for vector in GOLDEN["vectors"]}
INSTALLATION = "00000000-0000-7000-8000-000000000001"
TENANT = "00000000-0000-7000-8000-0000000000aa"
P, D, U = JournalState.PREPARED, JournalState.DISPATCHED, JournalState.UNCERTAIN
TRANSPORTS = ["direct", "http"]


def schema(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / f"{name}.v2.schema.json").read_text(encoding="utf-8"))


def recovery_schema_is_effect_scoped() -> bool:
    """True once E-KS's effect-scoped `credential-claims.v2` lands in the fixtures."""

    recovery = json.dumps(schema("credential-claims")["properties"]["recovery"])  # type: ignore[index]
    return '"scope"' in recovery


def origin(attempt: int = 1, **updates: object) -> InvocationOrigin:
    values: dict[str, object] = {
        "issuer": "mission-control",
        "installation_id": INSTALLATION,
        "application_id": "biotech",
        "tenant_id": TENANT,
        "mission_id": "11111111-1111-4111-8111-111111111111",
        "run_id": "22222222-2222-4222-8222-222222222222",
        "activation_id": "33333333-3333-4333-8333-333333333333",
        "operation_id": "op-research-1",
        "attempt": attempt,
        "generation": 1,
        "lane": "deep_agents",
        **updates,
    }
    return InvocationOrigin.model_validate(values)


@dataclass
class Harness:
    clock: SteppingClock
    issuer: Issuer
    minter: RecordingMinter
    client: FakeKnowledgeBinding
    journal: InMemoryKnowledgeJournal
    handles: InMemoryKnowledgeHandleStore
    gateway: KnowledgeGateway
    sleeps: list[float]

    def access(
        self, attempt: int = 1, grant: RecoveryGrant | None = None, invocation: str = "inv-0001"
    ) -> InvocationAccess:
        return InvocationAccess(
            origin=origin(attempt),
            subject="mission-control-runtime",
            invocation_id=invocation,
            authenticated_at=self.clock.now,
            recovery_grant=grant,
        )

    def recovery(self, issuer: str = "mission-control") -> RecoveryAccess:
        return RecoveryAccess(
            installation_id=INSTALLATION,
            application_id="biotech",
            tenant_id=TENANT,
            issuer=issuer,
            subject="mission-control-reconciler",
            authority_ref="recovery-grant-7",
            invocation_id="inv-0009",
            authenticated_at=self.clock.now,
        )

    async def transitions(self, effect_key: str) -> list[tuple[object, object]]:
        return list(await self.journal.transitions(self.access().scope, effect_key))


def harness(transport: str = "direct", max_polls: int = 3, **drift: object) -> Harness:
    clock = SteppingClock()
    issuer = Issuer(clock=clock)
    minter = RecordingMinter(issuer.minter(), drift=dict(drift))
    fake = FakeKnowledgeBinding(verifier=issuer.verifier(), clock=clock)
    journal = InMemoryKnowledgeJournal()
    handles = InMemoryKnowledgeHandleStore()
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = fake if transport == "direct" else http_client_over(fake, sleep=sleep)
    gateway = KnowledgeGateway(
        client=client,
        journal=journal,
        handles=handles,
        minter=minter,
        knowledge=knowledge_port(BINDING),
        audience=AUDIENCE,
        max_polls=max_polls,
        clock=clock,
        sleep=sleep,
    )
    return Harness(clock, issuer, minter, fake, journal, handles, gateway, sleeps)


def call(payload: object | None = None, **updates: object) -> KnowledgeCall:
    values: dict[str, object] = {
        "operation": "knowledge.apply",
        "capability_pin": "ai-engineer.research@1:knowledge.apply",
        "native_contract": {"name": "knowledge-ingestion-intent", "version": "v1"},
        "payload": {"intent": "add", "claims": ["c-1"]} if payload is None else payload,
        "governors": Governors(
            deadline="2026-10-24T20:10:00Z",
            maxItems=64,
            partialResults="forbid",
            budget={"calls": 10, "tokens": 1000, "costUsd": "0.50"},
        ),
        **updates,
    }
    return KnowledgeCall.model_validate(values)


# ---------------------------------------------------------------- origin mapping


def test_invocation_access_maps_to_the_golden_wire_origin() -> None:
    vector = VECTORS["origin-identity"]
    wire = vector["origin"]
    mission = wire["mission"]
    mapped = to_wire_origin(
        InvocationOrigin(
            issuer=wire["issuer"],
            installation_id=wire["installationId"],
            application_id=wire["applicationId"],
            tenant_id=wire["tenantId"],
            mission_id=mission["missionId"],
            run_id=mission["runId"],
            activation_id=mission["activationId"],
            operation_id=mission["operationId"],
            attempt=mission["operationAttempt"],
            generation=mission["executionGeneration"],
            lane=mission["lane"],
        ),
        subject=wire["subject"],
        invocation_id=wire["invocationId"],
        authenticated_at=SteppingClock().now,
    )
    assert mapped == Origin.model_validate(wire)
    assert mapped.digest() == vector["digest"]


def test_agent_supplied_origin_is_not_part_of_a_call() -> None:
    forged = call().model_dump() | {"origin": VECTORS["origin-identity"]["origin"]}
    with pytest.raises(ValidationError):
        KnowledgeCall.model_validate(forged)


# ---------------------------------------------------------------- receipt path


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_receipt_settles_applied_after_prepared_then_dispatched(transport: str) -> None:
    h = harness(transport)
    access = h.access()
    result = await h.gateway.invoke(call(), access)

    assert result.state is JournalState.APPLIED and result.receipt is not None
    assert await h.transitions(result.effect_key or "") == [(None, P), (P, D), (D, "applied")]
    (sent,) = h.client.calls_of("invoke")
    envelope = sent.envelope
    assert envelope is not None and envelope.effect is not None
    native = canonical_json(call().payload).encode()
    assert envelope.effect == bind_effect(result.effect_key or "", native, access.wire_origin())
    assert envelope.requestId == result.journal.knowledge_operation_id  # type: ignore[union-attr]
    claims = sent.claims
    assert (claims.iss, claims.aud, claims.tenant, claims.binding) == (
        "mission-control",
        AUDIENCE,
        TENANT,
        BINDING,
    )
    assert claims.operations == ["knowledge.apply"] and claims.dispatchId == envelope.dispatchId
    assert claims.effect is not None
    assert claims.effect.boundEffectDigest == envelope.effect.boundEffectDigest
    assert claims.exp - claims.iat == 300 and claims.recovery is None
    assert result.journal is not None and result.journal.receipt_digest == result.receipt.digest
    # Wire conformance of what crossed the boundary.
    jsonschema.validate(result.receipt.model_dump(mode="json"), schema("operation-receipt"))
    jsonschema.validate(claims.model_dump(mode="json"), schema("credential-claims"))
    jsonschema.validate(envelope.model_dump(mode="json"), schema("operation-envelope"))

    again = await h.gateway.invoke(call(), h.access(invocation="inv-0002"))
    assert again.state is JournalState.APPLIED and len(h.client.calls_of("invoke")) == 1


async def test_minted_credential_never_renders_its_token() -> None:
    h = harness()
    request = CredentialRequest(
        audience=AUDIENCE,
        binding=BINDING,
        origin=h.access().wire_origin(),
        operations=("knowledge.read",),
        dispatch_id="dispatch-1",
    )
    minted = h.minter.mint(request)
    assert minted.token not in repr(minted)
    private = str(h.issuer.active.key.as_dict(private=True)["d"])
    assert minted.token not in repr(h.minter.inner) and private not in repr(h.issuer.active)
    assert private not in repr(h.minter.inner)


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_binding_refusal_settles_rejected_with_its_code(transport: str) -> None:
    h = harness(transport)
    h.client.invoke_script.append("refuse:SCHEMA_UNSUPPORTED")
    result = await h.gateway.invoke(call(), h.access())
    assert result.state is JournalState.REJECTED
    assert result.journal is not None and result.journal.refusal_code == "SCHEMA_UNSUPPORTED"


# ---------------------------------------------------------------- origin and effect identity


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_later_attempt_without_exact_recovery_authority_is_origin_mismatch(
    transport: str,
) -> None:
    h = harness(transport)
    h.client.invoke_script.append("drop")
    first = await h.gateway.invoke(call(), h.access())
    assert first.state is U
    key = first.effect_key or ""
    digest = first.journal.bound_effect_digest  # type: ignore[union-attr]

    with pytest.raises(KnowledgeRefused) as refused:
        await h.gateway.invoke(call(), h.access(attempt=2))
    assert refused.value.code == "ORIGIN_MISMATCH"
    wrong = RecoveryGrant(
        authority_ref="grant-1", effect_key=key, bound_effect_digest="sha256:" + "0" * 64
    )
    with pytest.raises(KnowledgeRefused) as refused:
        await h.gateway.invoke(call(), h.access(attempt=2, grant=wrong))
    assert refused.value.code == "ORIGIN_MISMATCH"
    assert digest != wrong.bound_effect_digest
    assert len(h.client.calls_of("invoke")) == 1


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_forged_origin_is_refused_by_the_binding(transport: str) -> None:
    """An envelope whose originating origin is not the credential's caller (and no recovery
    authority) is ORIGIN_MISMATCH at the binding, even under a valid credential."""

    h = harness(transport)
    gateway_client = h.gateway._client  # the transport under test
    access = h.access()
    native = canonical_json(call().payload).encode()
    forged_origin = h.access(attempt=7).wire_origin()
    binding = bind_effect("forged-key-1", native, forged_origin)
    envelope = h.gateway._envelope(
        call(), access.wire_origin(), "dispatch-f", request_id="r-f", effect=binding
    )
    credential = h.minter.mint(
        CredentialRequest(
            AUDIENCE,
            BINDING,
            access.wire_origin(),
            ("knowledge.apply",),
            "dispatch-f",
            effect_key="forged-key-1",
            bound_effect_digest=binding.boundEffectDigest,
        )
    )
    with pytest.raises(KnowledgeProtocolRefusal) as refused:
        await gateway_client.invoke(envelope, credential.token)
    assert refused.value.error.code == "ORIGIN_MISMATCH"
    assert h.client.committed == {}


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_changed_bytes_under_the_same_effect_key_are_refused(transport: str) -> None:
    h = harness(transport)
    first = await h.gateway.invoke(call(effect_key="tool-call-1"), h.access())
    assert first.state is JournalState.APPLIED
    with pytest.raises(KnowledgeRefused) as refused:
        await h.gateway.invoke(
            call({"intent": "add", "claims": ["c-2"]}, effect_key="tool-call-1"), h.access()
        )
    assert refused.value.code == "EFFECT_CONFLICT"
    assert len(h.client.calls_of("invoke")) == 1


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_binding_refuses_changed_bytes_under_a_bound_key(transport: str) -> None:
    """Over the wire too: a second binding of the same key to other bytes is EFFECT_CONFLICT."""

    h = harness(transport)
    client = h.gateway._client
    access = h.access()
    caller = access.wire_origin()
    for index, payload in enumerate(({"v": 1}, {"v": 2})):
        native = canonical_json(payload).encode()
        binding = bind_effect("wire-key-1", native, caller)
        envelope = h.gateway._envelope(
            call(payload), caller, f"d-{index}", request_id=f"r-{index}", effect=binding
        )
        credential = h.minter.mint(
            CredentialRequest(
                AUDIENCE,
                BINDING,
                caller,
                ("knowledge.apply",),
                f"d-{index}",
                effect_key="wire-key-1",
                bound_effect_digest=binding.boundEffectDigest,
            )
        )
        if index == 0:
            await client.invoke(envelope, credential.token)
            continue
        with pytest.raises(KnowledgeProtocolRefusal) as refused:
            await client.invoke(envelope, credential.token)
        assert refused.value.error.code == "EFFECT_CONFLICT"


# ---------------------------------------------------------------- uncertainty and recovery


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_transport_failure_after_dispatch_stays_uncertain_and_is_never_auto_retried(
    transport: str,
) -> None:
    h = harness(transport)
    h.client.invoke_script.append("drop")
    result = await h.gateway.invoke(call(), h.access())
    assert result.state is U and result.refusal_code == "UNRESOLVED_EFFECT"
    assert result.lookup is not None and result.lookup.disposition == "not_found"
    assert await h.transitions(result.effect_key or "") == [(None, P), (P, D), (D, U)]

    again = await h.gateway.invoke(call(), h.access())
    assert again.state is U and again.refusal_code == "UNRESOLVED_EFFECT"
    assert len(h.client.calls_of("invoke")) == 1
    assert len(h.client.calls_of("receipt.get")) == 2


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_crash_after_native_commit_settles_from_the_receipt_lookup(transport: str) -> None:
    h = harness(transport)
    h.client.invoke_script.append("lost")
    result = await h.gateway.invoke(call(), h.access())
    assert result.state is JournalState.APPLIED
    assert result.journal is not None and result.journal.reconciled
    assert await h.transitions(result.effect_key or "") == [
        (None, P),
        (P, D),
        (D, U),
        (U, "applied"),
    ]


@pytest.mark.parametrize("transport", TRANSPORTS)
@pytest.mark.parametrize("code", ["INTERNAL", "UNRESOLVED_EFFECT"])
async def test_refusal_after_native_commit_stays_uncertain_and_settles_receipt_first(
    transport: str, code: str
) -> None:
    """WI-05: the binding committed natively and then refused (protocol receipt lost). The
    effect is never settled rejected; it stays uncertain, is never re-dispatched, and settles
    from the reconstructed receipt on a later lookup."""

    h = harness(transport)
    h.client.invoke_script.append(f"commit_refuse:{code}")
    h.client.lookups.append("unresolved")
    result = await h.gateway.invoke(call(), h.access())
    key = result.effect_key or ""
    assert result.state is U and result.refusal_code == "UNRESOLVED_EFFECT"
    assert await h.transitions(key) == [(None, P), (P, D), (D, U)]

    again = await h.gateway.invoke(call(), h.access())
    assert again.state is JournalState.APPLIED
    assert again.journal is not None and again.journal.reconciled
    assert again.journal.terminal_receipt_ref == h.client.committed[key].receipt_ref()
    assert len(h.client.calls_of("invoke")) == 1
    assert h.client.dispatches[key] == 1
    assert await h.transitions(key) == [(None, P), (P, D), (D, U), (U, "applied")]


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_a_not_journaled_refusal_of_a_first_dispatch_settles_rejected_and_stays_retryable(
    transport: str,
) -> None:
    """WI-05: KS states nothing was sent natively (a transient failure before the journal). A
    first dispatch is rejected at once: no retry is stranded behind an uncertain effect."""

    h = harness(transport)
    h.client.invoke_script.append("refuse:INTERNAL@not_journaled")
    result = await h.gateway.invoke(call(), h.access())
    assert result.state is JournalState.REJECTED
    assert result.journal is not None and result.journal.refusal_code == "INTERNAL"
    assert h.client.calls_of("receipt.get") == []


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_a_journaled_uncommitted_refusal_is_rejected_only_once_receipt_get_proves_no_commit(
    transport: str,
) -> None:
    h = harness(transport)
    h.client.invoke_script.append("refuse:INTERNAL@journaled_uncommitted")
    proven = await h.gateway.invoke(call(), h.access())
    assert proven.state is JournalState.REJECTED
    assert len(h.client.calls_of("receipt.get")) == 1

    # The lookup cannot prove it (unresolved): the effect stays uncertain, never rejected.
    h.client.invoke_script.append("refuse:INTERNAL@journaled_uncommitted")
    h.client.lookups.append("unresolved")
    unproven = await h.gateway.invoke(call(payload={"intent": "second"}), h.access())
    assert unproven.state is U and unproven.refusal_code == "UNRESOLVED_EFFECT"

    # Not fenced by KS (its commit may still be in flight): never rejected, even on not_found.
    h.client.invoke_script.append("refuse:STALE_DECISION@journaled_uncommitted!")
    unfenced = await h.gateway.invoke(call(payload={"intent": "third"}), h.access())
    assert unfenced.state is U and unfenced.refusal_code == "UNRESOLVED_EFFECT"


@pytest.mark.parametrize("transport", TRANSPORTS)
@pytest.mark.parametrize("state", ["committed", "unknown"])
async def test_a_committed_or_unknown_refusal_stays_uncertain_whatever_its_code(
    transport: str, state: str
) -> None:
    h = harness(transport)
    h.client.invoke_script.append(f"commit_refuse:STALE_DECISION@{state}")
    h.client.lookups.append("unresolved")
    result = await h.gateway.invoke(call(), h.access())
    assert result.state is U and result.refusal_code == "UNRESOLVED_EFFECT"
    settled = await h.gateway.invoke(call(), h.access())
    assert settled.state is JournalState.APPLIED
    assert len(h.client.calls_of("invoke")) == 1


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_definitive_refusal_after_dispatch_still_settles_rejected(transport: str) -> None:
    h = harness(transport)
    h.client.invoke_script.append("refuse:STALE_DECISION")
    result = await h.gateway.invoke(call(), h.access())
    assert result.state is JournalState.REJECTED
    assert result.journal is not None and result.journal.refusal_code == "STALE_DECISION"
    assert h.client.calls_of("receipt.get") == []


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_authorized_retry_presents_the_new_attempt_with_effect_scoped_recovery(
    transport: str,
) -> None:
    h = harness(transport)
    h.client.invoke_script.extend(["drop", "receipt"])
    first = await h.gateway.invoke(call(), h.access())
    record = first.journal
    assert record is not None and record.state is U
    grant = RecoveryGrant("grant-1", record.effect_key, record.bound_effect_digest)

    retried = await h.gateway.invoke(
        call(), h.access(attempt=2, grant=grant, invocation="inv-0002")
    )
    assert retried.state is JournalState.APPLIED
    one, two = h.client.calls_of("invoke")
    assert one.envelope is not None and two.envelope is not None
    assert one.envelope.input == two.envelope.input  # identical native bytes
    assert one.envelope.effect == two.envelope.effect  # originating origin stays attempt 1
    assert one.envelope.dispatchId != two.envelope.dispatchId
    assert one.claims.jti != two.claims.jti
    # The new attempt is the credential origin (current_caller_origin) ...
    assert two.claims.origin.kind == "mission_invocation"
    assert two.claims.origin.mission is not None
    assert two.claims.origin.mission.operationAttempt == 2
    # ... and it carries the effect-scoped recovery grant for exactly this effect.
    recovery = two.claims.recovery
    assert recovery is not None and recovery.scope == "effect"
    assert (recovery.authorityRef, recovery.effectKey, recovery.boundEffectDigest) == (
        "grant-1",
        record.effect_key,
        record.bound_effect_digest,
    )
    receipt = h.client.committed[record.effect_key]
    assert receipt.effect.currentCallerOrigin == two.claims.origin
    assert receipt.effect.originatingOrigin == one.envelope.effect.originatingOrigin
    assert receipt.effect.dispatchSequence == 2
    assert retried.journal is not None
    assert retried.journal.current_caller_origin == two.claims.origin
    assert await h.transitions(record.effect_key) == [
        (None, P),
        (P, D),
        (D, U),
        (U, D),
        (D, "applied"),
    ]
    if recovery_schema_is_effect_scoped():
        jsonschema.validate(two.claims.model_dump(mode="json"), schema("credential-claims"))


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_pending_dispatch_stays_unresolved_until_the_lookup_reports_delivery(
    transport: str,
) -> None:
    h = harness(transport)
    h.client.invoke_script.append("pending")
    first = await h.gateway.invoke(call(), h.access())
    # Admitted and queued: not applied, not a refusal; the effect stays unresolved.
    assert first.state is U and first.refusal_code is None
    document = first.document()
    assert document["receipt_outcome"] == "pending_dispatch" and document["pending_delivery"]
    key = first.effect_key or ""

    # The same call again never redispatches a queued effect.
    h.client.lookups.extend(["auto"])
    again = await h.gateway.invoke(call(), h.access())
    assert again.state is U and again.refusal_code is None and again.document()["pending_delivery"]
    assert len(h.client.calls_of("invoke")) == 1

    # Still in flight, then failed: unresolved (a failed delivery proves nothing).
    h.client.lookups.extend(["delivery:dispatched", "delivery:failed"])
    assert (await h.gateway.reconcile(key, h.recovery())).state is U
    failed = await h.gateway.reconcile(key, h.recovery())
    assert failed.state is U and not failed.document()["pending_delivery"]

    h.client.lookups.append("delivery:applied")
    settled = await h.gateway.reconcile(key, h.recovery())
    assert settled.state is JournalState.APPLIED
    assert settled.journal is not None and settled.journal.reconciled
    assert await h.transitions(key) == [(None, P), (P, D), (D, U), (U, "applied")]


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_apply_binds_the_plan_level_digest_and_keeps_the_payload_digest(
    transport: str,
) -> None:
    h = harness(transport)
    intent = {"schemaVersion": "biotech-knowledge-intent.v2", "intentId": "i-1"}
    payload = {"schemaVersion": "biotech-knowledge-apply.v1", "intent": intent, "exactUse": {}}
    result = await h.gateway.invoke(call(payload, plan=intent), h.access())
    assert result.state is JournalState.APPLIED
    envelope = h.client.calls_of("invoke")[-1].envelope
    assert envelope is not None and envelope.effect is not None
    caller = Origin.model_validate(envelope.effect.originatingOrigin.model_dump(mode="json"))
    assert envelope.effect.boundEffectDigest == bound_effect_digest(
        canonical_json(intent).encode(), caller
    )
    assert envelope.effect.semanticPayloadDigest == digest_bytes(canonical_json(payload).encode())
    # The same plan under other request bytes is the same bound effect; a changed plan is not.
    with pytest.raises(KnowledgeRefused) as refused:
        await h.gateway.invoke(
            call(payload, plan=intent | {"intentId": "i-2"}, effect_key=result.effect_key),
            h.access(),
        )
    assert refused.value.code == "EFFECT_CONFLICT"
    with pytest.raises(ValueError, match="knowledge.apply only"):
        call({"report": {}}, operation="report.register", plan=intent)


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_revoked_delivery_settles_a_pending_dispatch_effect_rejected(transport: str) -> None:
    h = harness(transport)
    h.client.invoke_script.append("pending")
    key = (await h.gateway.invoke(call(), h.access())).effect_key or ""
    h.client.lookups.append("delivery:revoked")
    revoked = await h.gateway.reconcile(key, h.recovery())
    assert revoked.state is JournalState.REJECTED
    assert len(h.client.calls_of("invoke")) == 1


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_fresh_read_only_recovery_settles_an_uncertain_effect(transport: str) -> None:
    h = harness(transport)
    h.client.invoke_script.append("lost")
    h.client.lookups.append("not_found")  # the first lookup races the native commit
    first = await h.gateway.invoke(call(), h.access())
    assert first.state is U
    key = first.effect_key or ""

    with pytest.raises(KnowledgeRefused) as refused:
        await h.gateway.reconcile(key, h.recovery(issuer="other-issuer"))
    assert refused.value.code == "SCOPE_DENIED"

    h.clock.advance(timedelta(hours=1))  # long after the invocation's credentials expired
    recovered = await h.gateway.reconcile(key, h.recovery())
    assert recovered.state is JournalState.APPLIED
    assert recovered.journal is not None and recovered.journal.reconciled
    lookup_claims = h.client.calls_of("receipt.get")[-1].claims
    assert lookup_claims.origin.kind == "recovery" and lookup_claims.origin.mission is None
    assert lookup_claims.recovery is not None and lookup_claims.recovery.scope == "read_only"
    assert lookup_claims.operations == ["receipt.get"]
    assert len(h.client.calls_of("invoke")) == 1


# ---------------------------------------------------------------- credential conformance


def test_claims_contract_refuses_wrong_tenant_long_lifetime_and_unscoped_recovery() -> None:
    h = harness()
    claims = h.minter.mint(
        CredentialRequest(AUDIENCE, BINDING, h.access().wire_origin(), ("knowledge.read",), "d-1")
    ).claims
    document = claims.model_dump(mode="json")
    with pytest.raises(ValidationError):
        CredentialClaims.model_validate(document | {"tenant": "other"})
    with pytest.raises(ValidationError):
        CredentialClaims.model_validate(document | {"exp": claims.iat + 301})
    # An effect-scoped grant on a read credential (no effect) is refused.
    with pytest.raises(ValidationError):
        CredentialClaims.model_validate(
            document
            | {
                "recovery": {
                    "scope": "effect",
                    "authorityRef": "g-1",
                    "effectKey": "k",
                    "boundEffectDigest": "sha256:" + "a" * 64,
                }
            }
        )
    # A read-only grant on a live mission origin is refused (it needs a recovery origin).
    with pytest.raises(ValidationError):
        CredentialClaims.model_validate(
            document
            | {
                "recovery": {
                    "scope": "read_only",
                    "authorityRef": "g-1",
                    "effectKey": None,
                    "boundEffectDigest": None,
                }
            }
        )


def test_claims_for_another_tenant_origin_fail_host_verification() -> None:
    h = harness()
    request = CredentialRequest(
        AUDIENCE, BINDING, h.access().wire_origin(), ("knowledge.read",), "d-1"
    )
    other = InvocationAccess(
        origin=origin(tenant_id="00000000-0000-7000-8000-0000000000bb"),
        subject="mission-control-runtime",
        invocation_id="inv-0001",
        authenticated_at=h.clock.now,
    )
    foreign = h.minter.mint(
        CredentialRequest(AUDIENCE, BINDING, other.wire_origin(), ("knowledge.read",), "d-1")
    )
    with pytest.raises(CredentialMismatch, match="origin.*tenant"):
        verify_credential_claims(foreign.claims, request, now=h.clock.now)


@pytest.mark.parametrize(
    ("drift", "field"),
    [({"aud": "some-other-service"}, "aud"), ({"iss": "another-issuer"}, "iss")],
    ids=["wrong-audience", "wrong-issuer"],
)
async def test_drifted_audience_or_issuer_is_refused_before_dispatch(
    drift: dict[str, str], field: str
) -> None:
    h = harness(**drift)
    with pytest.raises(KnowledgeRefused) as refused:
        await h.gateway.invoke(call(), h.access())
    assert refused.value.code == "SCOPE_DENIED" and field in str(refused.value)
    assert h.client.calls == []
    record = await h.journal.lookup(h.access().scope, refused.value.effect_key or "")
    assert record is not None and record.state is JournalState.REJECTED
    assert record.refusal_code == "SCOPE_DENIED"


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_binding_refuses_wrong_audience_issuer_expired_rotated_and_replayed(
    transport: str,
) -> None:
    h = harness(transport)
    client = h.gateway._client
    request = CredentialRequest(
        AUDIENCE, BINDING, h.access().wire_origin(), ("operation.get",), "d-1"
    )

    async def refused_with(token: str) -> str:
        with pytest.raises(KnowledgeProtocolRefusal) as refused:
            await client.describe(token)
        assert refused.value.error.code == "SCOPE_DENIED"
        return refused.value.error.message

    good = h.minter.inner.mint(
        CredentialRequest(
            AUDIENCE, BINDING, h.access().wire_origin(), ("knowledge.describe",), "d-0"
        )
    )
    assert (await client.describe(good.token)).binding == BINDING
    assert await refused_with(good.token) == "replay"
    assert await refused_with(h.minter.inner.mint(request).token) == "operation not granted"
    wrong_audience = CredentialRequest(
        "some-other-service", BINDING, h.access().wire_origin(), ("knowledge.describe",), "d-2"
    )
    assert await refused_with(h.minter.inner.mint(wrong_audience).token) == "wrong_audience"
    describe = CredentialRequest(
        AUDIENCE, BINDING, h.access().wire_origin(), ("knowledge.describe",), "d-3"
    )
    # The pinned key, another issuer name: the issuer pin refuses it.
    impostor = Issuer(clock=h.clock, issuer="another-issuer", active=h.issuer.active, retiring=None)
    assert await refused_with(impostor.minter().mint(describe).token) == "wrong_issuer"
    stranger = Issuer(
        clock=h.clock,
        issuer="another-issuer",
        active=generate_signing_key("other-k1"),
        retiring=None,
    )
    assert await refused_with(stranger.minter().mint(describe).token) == "unknown_kid"
    # A key that is neither the active nor the retiring pinned key fails closed.
    rotated = Issuer(clock=h.clock, active=generate_signing_key("mc-k3"), retiring=None)
    assert await refused_with(rotated.minter().mint(describe).token) == "unknown_kid"
    # A rotated key reusing a pinned kid with other material fails its signature.
    reused = Issuer(clock=h.clock, active=generate_signing_key("mc-k2"), retiring=None)
    assert await refused_with(reused.minter().mint(describe).token) == "bad_signature"
    # A token signed by the retiring key still verifies until it expires.
    retiring = Issuer(clock=h.clock, active=h.issuer.retiring, retiring=None)  # type: ignore[arg-type]
    old = retiring.minter().mint(describe)
    assert (await client.describe(old.token)).binding == BINDING
    expiring = h.minter.inner.mint(
        CredentialRequest(
            AUDIENCE, BINDING, h.access().wire_origin(), ("knowledge.describe",), "d-4"
        )
    )
    h.clock.advance(timedelta(seconds=331))
    assert await refused_with(expiring.token) == "expired"


def test_verifier_refuses_algorithm_and_type_outside_the_profile() -> None:
    h = harness()
    verifier = h.issuer.verifier()
    token = h.minter.inner.mint(
        CredentialRequest(AUDIENCE, BINDING, h.access().wire_origin(), ("knowledge.read",), "d")
    ).token
    header, body, signature = token.split(".")
    import base64

    def b64(document: dict[str, str]) -> str:
        raw = json.dumps(document).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    for forged, reason in (
        ({"alg": "HS256", "kid": "mc-k2", "typ": "ks-knowledge-operation+jwt"}, "algorithm"),
        ({"alg": "none", "kid": "mc-k2", "typ": "ks-knowledge-operation+jwt"}, "algorithm"),
        ({"alg": "EdDSA", "kid": "mc-k2", "typ": "JWT"}, "wrong_token_type"),
    ):
        with pytest.raises(CredentialRejected, match=reason):
            verifier.verify(f"{b64(forged)}.{body}.{signature}")
    with pytest.raises(CredentialRejected, match="bad_signature"):
        verifier.verify(f"{header}.{body}.{signature[:-4]}AAAA")


async def test_expired_credentials_are_never_reused() -> None:
    h = harness()
    await h.gateway.invoke(call(), h.access())
    await h.gateway.invoke(call({"intent": "add", "claims": ["c-9"]}), h.access())
    first, second = h.client.calls_of("invoke")
    assert first.claims.jti != second.claims.jti
    assert first.claims.dispatchId != second.claims.dispatchId
    assert len({claims.jti for claims in h.minter.minted}) == len(h.minter.minted)


# ---------------------------------------------------------------- handles and cancellation


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_handle_is_polled_with_bounded_retry_after_until_terminal(transport: str) -> None:
    h = harness(transport)
    h.client.invoke_script.append("handle")
    h.client.statuses.extend(["running", "succeeded"])
    result = await h.gateway.invoke(call(), h.access())
    assert result.state is JournalState.APPLIED and h.sleeps == [0.1]
    assert result.journal is not None and result.journal.operation_id is not None
    assert await h.transitions(result.effect_key or "") == [
        (None, P),
        (P, D),
        (D, D),
        (D, "applied"),
    ]
    stored = await h.handles.get(h.access().scope, BINDING, result.journal.operation_id)
    assert stored is not None and stored.state == "succeeded" and stored.effect_key

    bounded = harness(transport, max_polls=2)
    bounded.client.invoke_script.append("handle")
    pending = await bounded.gateway.invoke(call(), bounded.access())
    assert pending.state is D and pending.handle is not None
    assert len(bounded.client.calls_of("operation.get")) == 2


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_cancel_stops_new_calls_and_reconciles_outstanding_effects(transport: str) -> None:
    h = harness(transport, max_polls=1)
    h.client.invoke_script.append("handle")
    access = h.access()
    pending = await h.gateway.invoke(call(), access)
    assert pending.state is D

    (settled,) = await h.gateway.cancel(access, "cancel-1")
    assert settled.state is JournalState.REJECTED and settled.refusal_code == "CANCELLED"
    assert len(h.client.calls_of("operation.cancel")) == 1
    assert len(h.client.calls_of("receipt.get")) == 1

    invokes = len(h.client.calls_of("invoke"))
    with pytest.raises(KnowledgeRefused) as refused:
        await h.gateway.invoke(call({"intent": "other"}), access)
    assert refused.value.code == "CANCELLED"
    assert len(h.client.calls_of("invoke")) == invokes


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_stop_during_review_cancels_the_durable_handle_after_a_restart(
    transport: str,
) -> None:
    """`report.assess` reaches waiting_review; a new gateway (restart, empty memory) finds the
    open handle in the store, cancels it once with the stored request id and records it."""

    h = harness(transport, max_polls=2)
    h.client.operation_statuses["report.assess"] = __import__("collections").deque(
        ["running", "waiting_review"]
    )
    access = h.access()
    started = await h.gateway.invoke(
        call({"report": "r-1"}, operation="report.assess", request_key="assess-sub-1"), access
    )
    assert started.handle_record is not None and started.handle_record.state == "waiting_review"
    assert started.handle_record.pending_review_ref is not None

    restarted = KnowledgeGateway(
        client=h.gateway._client,
        journal=h.journal,
        handles=h.handles,
        minter=h.minter,
        knowledge=knowledge_port(BINDING),
        audience=AUDIENCE,
        clock=h.clock,
        sleep=h.gateway._sleep,
    )
    await restarted.cancel(access, "cancel-review-1")
    await restarted.cancel(access, "cancel-review-2")  # idempotent: nothing open any more
    stored = await h.handles.get(access.scope, BINDING, started.handle_record.handle.operationId)
    assert stored is not None and stored.state == "cancelled"
    assert stored.cancel_request_id == "cancel-review-1"
    assert len(h.client.calls_of("operation.cancel")) == 1
    with pytest.raises(KnowledgeRefused):
        await restarted.invoke(call(operation="report.assess"), access)


@pytest.mark.parametrize("transport", TRANSPORTS)
async def test_handle_start_is_idempotent_by_request_key(transport: str) -> None:
    h = harness(transport, max_polls=1)
    access = h.access()
    one = await h.gateway.invoke(
        call({"report": "r-1"}, operation="report.assess", request_key="assess-sub-1"), access
    )
    two = await h.gateway.invoke(
        call({"report": "r-1"}, operation="report.assess", request_key="assess-sub-1"), access
    )
    assert one.handle == two.handle
    assert len(h.handles.rows) == 1


# ---------------------------------------------------------------- apply by recorded decision


async def test_biotech_apply_of_a_recorded_decision_binds_the_plan_and_supplies_exact_use() -> None:
    from mission_control.adapters.knowledge.decisions import InMemoryUseDecisionStore
    from mission_control.application.ports.knowledge import RecordedUseDecision

    clock = SteppingClock()
    issuer = Issuer(clock=clock)
    fake = FakeKnowledgeBinding(
        verifier=issuer.verifier(), clock=clock, binding="biotech-graph", application="biotech"
    )
    decisions = InMemoryUseDecisionStore()
    gateway = KnowledgeGateway(
        client=fake,
        journal=InMemoryKnowledgeJournal(),
        handles=InMemoryKnowledgeHandleStore(),
        minter=RecordingMinter(issuer.minter()),
        decisions=decisions,
        knowledge=knowledge_port("biotech-graph"),
        audience=AUDIENCE,
        clock=clock,
    )
    access = InvocationAccess(
        origin=origin(),
        subject="mission-control-runtime",
        invocation_id="inv-0001",
        authenticated_at=clock.now,
    )
    intent = {"schemaVersion": "biotech-knowledge-intent.v2", "intentId": "kop-bg-1"}
    bound = bound_effect_digest(canonical_json(intent).encode(), access.wire_origin())

    async def record(name: str, digest: str) -> str:
        handle = f"kh:biotech-graph/decision/{name}@use-decision.v1"
        await decisions.record(
            access.scope,
            RecordedUseDecision(
                handle=handle,
                binding_id="biotech-graph",
                tenant_id=TENANT,
                use_decision_id=name,
                bound_effect_digest=digest,
                processed_epoch=3,
                plan=intent,
                use="knowledge_ingestion.fact_assert_state",
                audience="internal",
            ),
        )
        return handle

    governors = call().governors
    pin = "knowledge.knowledge_apply@1"
    result = await gateway.apply_decision(
        await record("ud-1", bound), access, capability_pin=pin, governors=governors
    )
    assert result.state is JournalState.APPLIED
    (sent,) = fake.calls_of("invoke")
    assert sent.envelope is not None and sent.envelope.input is not None
    assert sent.envelope.effect is not None
    assert sent.envelope.input.nativeContract.name == "biotech-knowledge-apply"
    assert sent.envelope.effect.boundEffectDigest == bound
    # K01 round 4: the decision's exact use is declared on the apply envelope.
    assert (sent.envelope.use, sent.envelope.audience) == (
        "knowledge_ingestion.fact_assert_state",
        "internal",
    )
    assert sent.envelope.input.inlinePayload == {
        "schemaVersion": "biotech-knowledge-apply.v1",
        "intent": intent,
        "exactUse": {"useDecisionId": "ud-1", "processedEpoch": 3, "normalizedValuesDigest": None},
    }
    # A recorded decision whose digest does not bind this plan and origin is refused locally.
    with pytest.raises(KnowledgeRefused) as conflict:
        await gateway.apply_decision(
            await record("ud-2", digest_bytes(b"other")),
            access,
            capability_pin=pin,
            governors=governors,
        )
    assert conflict.value.code == "EFFECT_CONFLICT"
    with pytest.raises(KnowledgeRefused) as missing:
        await gateway.apply_decision(
            "kh:biotech-graph/decision/none@use-decision.v1",
            access,
            capability_pin=pin,
            governors=governors,
        )
    assert missing.value.code == "NOT_FOUND"
    # W1 native write: a plan decision bound to another invocation's origin is never applied.
    foreign = "kh:biotech-graph/decision/ud-foreign@use-decision.v1"
    await decisions.record(
        access.scope,
        RecordedUseDecision(
            handle=foreign,
            binding_id="biotech-graph",
            tenant_id=TENANT,
            use_decision_id="ud-foreign",
            bound_effect_digest=bound,
            processed_epoch=3,
            plan=intent,
            subject_ref="kh:biotech-graph/report/r@research-report.v2#" + bound,
            invocation_ref="mc-inv:another-invocation",
            decision_digest=bound,
        ),
    )
    with pytest.raises(KnowledgeRefused) as foreign_origin:
        await gateway.apply_decision(foreign, access, capability_pin=pin, governors=governors)
    assert foreign_origin.value.code == "ORIGIN_MISMATCH"
    assert len(fake.calls_of("invoke")) == 1


async def test_the_apply_payload_layout_is_the_profiles_data_not_an_application_branch() -> None:
    """OC-R4: the gateway builds the native payload from the port's apply contract and layout.

    The Biotech envelope under another contract name carries that name; a layout the host does
    not build refuses before anything is journalled or sent."""

    from mission_control.adapters.knowledge.decisions import InMemoryUseDecisionStore
    from mission_control.application.ports.knowledge import RecordedUseDecision

    clock = SteppingClock()
    issuer = Issuer(clock=clock)
    fake = FakeKnowledgeBinding(
        verifier=issuer.verifier(), clock=clock, binding="biotech-graph", application="biotech"
    )
    access = InvocationAccess(
        origin=origin(),
        subject="mission-control-runtime",
        invocation_id="inv-0001",
        authenticated_at=clock.now,
    )
    intent = {"schemaVersion": "biotech-knowledge-intent.v2", "intentId": "kop-bg-9"}
    bound = bound_effect_digest(canonical_json(intent).encode(), access.wire_origin())

    def gateway(**port: str) -> tuple[KnowledgeGateway, InMemoryKnowledgeJournal]:
        journal = InMemoryKnowledgeJournal()
        return (
            KnowledgeGateway(
                client=fake,
                journal=journal,
                handles=InMemoryKnowledgeHandleStore(),
                minter=RecordingMinter(issuer.minter()),
                decisions=decisions,
                knowledge=knowledge_port("biotech-graph").model_copy(update=port),
                audience=AUDIENCE,
                clock=clock,
            ),
            journal,
        )

    decisions = InMemoryUseDecisionStore()
    handle = "kh:biotech-graph/decision/ud-9@use-decision.v1"
    await decisions.record(
        access.scope,
        RecordedUseDecision(
            handle=handle,
            binding_id="biotech-graph",
            tenant_id=TENANT,
            use_decision_id="ud-9",
            bound_effect_digest=bound,
            processed_epoch=1,
            plan=intent,
        ),
    )
    governors = call().governors
    pin = "knowledge.knowledge_apply@1"
    unknown, journal = gateway(intent_schema_ref="mc.knowledge_apply_payload.unknown.v1")
    with pytest.raises(KnowledgeRefused) as refused:
        await unknown.apply_decision(handle, access, capability_pin=pin, governors=governors)
    assert refused.value.code == "SCHEMA_UNSUPPORTED"
    assert not fake.calls_of("invoke") and not journal.rows
    renamed, _ = gateway(apply_contract_name="graph-apply", apply_contract_version="v2")
    await renamed.apply_decision(handle, access, capability_pin=pin, governors=governors)
    (sent,) = fake.calls_of("invoke")
    assert sent.envelope is not None and sent.envelope.input is not None
    assert sent.envelope.input.nativeContract.model_dump() == {
        "name": "graph-apply",
        "version": "v2",
    }
    assert sent.envelope.input.inlinePayload["schemaVersion"] == "graph-apply.v2"


async def test_every_retransmission_carries_a_fresh_jti_and_dispatch_id() -> None:
    """R3 O5: the binding's credential-use registry is unique per (tenant, issuer, dispatch
    id), so a retried transmission must present a new dispatch id as well as a new `jti`."""

    from mission_control.application.ports.knowledge import CredentialRequest

    h = harness()
    source = h.gateway._fresh(
        CredentialRequest(
            audience=AUDIENCE,
            binding=BINDING,
            origin=h.access().wire_origin(),
            operations=("receipt.get",),
            dispatch_id="dispatch-original",
        )
    )
    verifier = h.issuer.verifier()
    first, second = verifier.verify(source()), verifier.verify(source())
    assert first.jti != second.jti
    assert first.dispatchId != second.dispatchId
    assert "dispatch-original" not in {first.dispatchId, second.dispatchId}
