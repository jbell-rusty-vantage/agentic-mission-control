"""M01: knowledge boundary identities are pure, deterministic and refuse illegal shapes."""

from __future__ import annotations

import os
import subprocess
import sys
from itertools import product
from pathlib import Path

import pytest
from pydantic import ValidationError

from mission_control.domain.knowledge.effects import (
    LEGAL_TRANSITIONS,
    TERMINAL_STATES,
    EffectConflict,
    EffectIdentity,
    IllegalJournalTransition,
    JournalState,
    is_legal_transition,
    require_transition,
)
from mission_control.domain.knowledge.handles import HandleKind, QualifiedHandle
from mission_control.domain.knowledge.lineage import (
    ROLE_ACTORS,
    ActorKind,
    LineageFact,
    ProvenanceRole,
)
from mission_control.domain.knowledge.origin import InvocationOrigin

ROOT = Path(__file__).resolve().parents[4]
DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def origin(**updates: object) -> InvocationOrigin:
    values: dict[str, object] = {
        "issuer": "mc-installation",
        "installation_id": "inst-1",
        "application_id": "ai-engineer",
        "tenant_id": "tenant-1",
        "mission_id": "mission-1",
        "run_id": "run-1",
        "activation_id": "activation-1",
        "operation_id": "goal-iteration/1/executor",
        "attempt": 1,
        "generation": 1,
        "lane": "deep_agents",
        **updates,
    }
    return InvocationOrigin.model_validate(values)


def effect(**updates: object) -> EffectIdentity:
    return EffectIdentity.prepare(
        origin(**updates),
        capability_pin="ai-engineer.research@1:report.publish",
        semantic_payload_digest=DIGEST_A,
        native_payload_digest=DIGEST_B,
    )


# --- journal states -----------------------------------------------------------------------------

EDGES = {
    ("prepared", "dispatched"),
    ("prepared", "rejected"),
    ("dispatched", "applied"),
    ("dispatched", "noop"),
    ("dispatched", "partial"),
    ("dispatched", "rejected"),
    ("dispatched", "uncertain"),
    ("uncertain", "dispatched"),
    ("uncertain", "applied"),
    ("uncertain", "noop"),
    ("uncertain", "partial"),
    ("uncertain", "rejected"),
}


@pytest.mark.parametrize(("current", "target"), list(product(JournalState, JournalState)))
def test_only_the_release_150_edges_are_legal(current: JournalState, target: JournalState) -> None:
    legal = (current.value, target.value) in EDGES
    assert is_legal_transition(current, target) is legal
    if legal:
        assert require_transition(current, target) is target
    else:
        with pytest.raises(IllegalJournalTransition):
            require_transition(current, target)


def test_terminal_states_have_no_exit_and_every_state_is_mapped() -> None:
    assert set(LEGAL_TRANSITIONS) == set(JournalState)
    assert all(not LEGAL_TRANSITIONS[state] for state in TERMINAL_STATES)
    assert JournalState.UNCERTAIN not in TERMINAL_STATES


# --- origin and effect identity -----------------------------------------------------------------


def test_an_origin_refuses_template_identity_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        origin(operation_id="manifest-template/executor")
    with pytest.raises(ValidationError):
        origin(credential="bytes")
    with pytest.raises(ValidationError):
        origin(attempt=0)


def test_origin_and_effect_digests_are_deterministic_and_attempt_sensitive() -> None:
    assert origin().digest() == origin().digest()
    assert origin(attempt=2).digest() != origin().digest()
    assert effect() == effect()
    assert effect().bound_effect_digest == effect().bound_effect_digest
    # A retry mints the same effect key but binds a different originating origin.
    retry = effect(attempt=2, generation=3)
    assert retry.effect_key == effect().effect_key
    assert retry.bound_effect_digest != effect().bound_effect_digest
    assert effect(tenant_id="tenant-2").effect_key != effect().effect_key
    assert effect(operation_id="goal-iteration/2/executor").effect_key != effect().effect_key
    # Family operation ids are run-relative: the same operation of another run is another effect.
    assert effect(run_id="run-other").effect_key != effect().effect_key


def test_digests_are_stable_across_processes() -> None:
    code = (
        "from tests.unit.domain.knowledge.test_knowledge_identities import effect;"
        "e = effect(); print(e.effect_key, e.bound_effect_digest, e.originating_origin.digest())"
    )
    runs = {
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout
        for seed in ("1", "2")
    }
    assert len(runs) == 1
    first = effect()
    assert runs.pop().split() == [
        first.effect_key,
        first.bound_effect_digest,
        first.originating_origin.digest(),
    ]


def test_same_key_different_bound_effect_conflicts() -> None:
    first = effect()
    edited = EffectIdentity.prepare(
        origin(),
        capability_pin="ai-engineer.research@1:report.publish",
        semantic_payload_digest=DIGEST_A,
        native_payload_digest=DIGEST_A,
    )
    assert edited.effect_key == first.effect_key
    assert first.conflicts_with(edited)
    with pytest.raises(EffectConflict, match="EFFECT_CONFLICT"):
        first.require_same_effect(edited)
    first.require_same_effect(effect())


def test_recovery_keeps_frozen_bytes_and_needs_authority() -> None:
    first = effect().dispatched("dispatch-1", DIGEST_A)
    recovered = first.recovered_by(origin(attempt=2))
    assert recovered.bound_effect_digest == first.bound_effect_digest
    assert recovered.originating_origin == first.originating_origin
    assert recovered.dispatch_id is None and recovered.requires_recovery_authority
    assert not effect().requires_recovery_authority
    with pytest.raises(ValidationError):
        first.recovered_by(origin(tenant_id="tenant-2"))
    with pytest.raises(ValidationError):
        EffectIdentity.model_validate({**effect().model_dump(), "dispatch_id": "only-the-id"})


# --- handles and lineage ------------------------------------------------------------------------


def test_qualified_handle_renders_and_digests_exactly() -> None:
    handle = QualifiedHandle(
        kind=HandleKind.REPORT,
        id="r1",
        version="v1",
        digest=DIGEST_A,
        tenant_id="tenant-1",
        binding="ai-engineer.research@1",
    )
    assert handle.render() == "kh:ai-engineer.research@1/report/r1@v1"
    assert handle.identity_digest() == handle.model_copy().identity_digest()
    assert (
        handle.identity_digest() != handle.model_copy(update={"digest": DIGEST_B}).identity_digest()
    )
    with pytest.raises(ValidationError):
        QualifiedHandle(
            kind=HandleKind.ASSERTION,
            id="a/1",
            version="v1",
            digest=DIGEST_A,
            tenant_id="t",
            binding="b",
        )


def test_seven_roles_and_their_actor_matrix() -> None:
    assert [role.value for role in ProvenanceRole] == [
        "producer",
        "caller",
        "receipt",
        "revision",
        "adopter",
        "assessor",
        "consumer",
    ]
    for role, kind in product(ProvenanceRole, ActorKind):
        values = {
            "subject_handle": "kh:b/report/r1@v1",
            "role": role,
            "actor_kind": kind,
            "actor_ref": "actor",
            "actor_origin": origin() if kind is ActorKind.ORIGIN else None,
        }
        if kind in ROLE_ACTORS[role]:
            assert LineageFact.model_validate(values).role is role
        else:
            with pytest.raises(ValidationError):
                LineageFact.model_validate(values)


def test_adoption_never_writes_producer() -> None:
    with pytest.raises(ValidationError, match="adopting"):
        LineageFact(
            subject_handle="kh:b/report/r1@v1",
            role=ProvenanceRole.PRODUCER,
            actor_kind=ActorKind.EXTERNAL,
            actor_ref="external",
            fact={"act": "adoption"},
        )
    adopter = LineageFact(
        subject_handle="kh:b/report/r1@v1",
        role=ProvenanceRole.ADOPTER,
        actor_kind=ActorKind.OBLIGATION,
        actor_ref="obligation:report",
        fact={"act": "adoption"},
    )
    assert adopter.role is ProvenanceRole.ADOPTER
