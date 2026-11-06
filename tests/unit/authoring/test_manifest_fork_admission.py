import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from mission_control.application.authoring.manifest_fork_admission import (
    ManifestForkAdmissionProvenance,
    SubmittedManifestConfiguration,
)
from mission_control.application.authoring.manifest_submit import SUBMIT_ISSUER, _manifest_input
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.manifest_lowering import MANIFEST_INPUT_CONTRACT
from mission_control.domain.policies.forks import ForkRejected
from tests.unit.run_control.test_run_control import request, service


async def fixture(corruption=None, *, contract=MANIFEST_INPUT_CONTRACT):
    control, _ = service()
    digest = "sha256:" + "a" * 64
    original = request().model_copy(
        update={
            "idempotency_issuer": json.dumps([SUBMIT_ISSUER, "operator"], separators=(",", ":")),
            "admission_evidence_refs": (f"manifest:{digest}",),
        }
    )
    decision = await control.admit(original)
    assert decision.run_id
    origin = await control.get_run(original.request_scope, decision.run_id)
    transitions = list(await control.list_transitions(original.request_scope, decision.run_id))
    target = request(request_id="derived-fork")
    program = {
        "contract": "mc.manifest-compiled-program/1",
        "effective_configuration_digest": target.effective_configuration_digest,
        "workflow_type_ref": target.workflow_type_ref.model_dump(mode="json"),
    }
    row = SubmittedManifestConfiguration(
        origin.run_id, "operator", "operator", digest, program, sha256_digest(program)
    )
    if corruption == "actor":
        row = replace(row, actor_id="foreign")
    elif corruption == "program_actor":
        row = replace(row, program_actor_id="foreign")
    elif corruption == "digest":
        row = replace(row, program_digest="sha256:" + "b" * 64)
    elif corruption == "configuration":
        program["effective_configuration_digest"] = "sha256:" + "b" * 64
        row = replace(row, program_digest=sha256_digest(program))
    elif corruption == "workflow":
        program["workflow_type_ref"] = target.workflow_type_ref.model_copy(
            update={"logical_id": "other"}
        ).model_dump(mode="json")
        row = replace(row, program_digest=sha256_digest(program))
    elif corruption == "malformed_ref":
        program["workflow_type_ref"] = {}
        row = replace(row, program_digest=sha256_digest(program))
    elif corruption == "input_manifest":
        origin = origin.model_copy(
            update={"input_manifest": target.input_manifest.model_copy(update={"revision": 2})}
        )
    elif corruption == "issuer":
        origin = origin.model_copy(update={"idempotency_issuer": "operator"})
    elif corruption == "scope":
        origin = origin.model_copy(update={"request_scope": "foreign"})
    elif corruption == "transition":
        transitions = []
    elif corruption == "marker":
        transitions[0] = transitions[0].model_copy(update={"evidence_refs": ()})
    elif corruption == "transition_actor":
        transitions[0] = transitions[0].model_copy(
            update={"actor": target.actor.model_copy(update={"actor_id": "foreign"})}
        )
    rows = () if corruption == "missing" else (row, row) if corruption == "ambiguous" else (row,)

    class Submissions:
        async def submitted_configurations(self, scope, configuration):
            assert (
                scope == target.request_scope
                and configuration == target.effective_configuration_digest
            )
            return rows

    class Control:
        async def get_run(self, scope, run):
            return origin

        async def list_transitions(self, scope, run):
            return transitions

    class Catalog:
        async def retrieve_for_admission(self, digest):
            return SimpleNamespace(workflow_type=SimpleNamespace(input_admission_contract=contract))

    return ManifestForkAdmissionProvenance(Submissions(), Control(), Catalog()), target


async def test_only_trusted_origin_adds_real_manifest_admission_evidence():
    proof, target = await fixture()
    assert _manifest_input(target, None) is not None
    refs = await proof.evidence(target)
    assert len(refs) == 3 and refs[0] == "manifest:sha256:" + "a" * 64
    derived = target.model_copy(
        update={"admission_evidence_refs": (*target.admission_evidence_refs, *refs)}
    )
    assert _manifest_input(derived, None) is None
    assert await proof.evidence(target) == refs


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "ambiguous",
        "actor",
        "program_actor",
        "digest",
        "configuration",
        "workflow",
        "malformed_ref",
        "input_manifest",
        "issuer",
        "scope",
        "transition",
        "marker",
        "transition_actor",
    ],
)
async def test_fork_manifest_origin_fails_closed(corruption):
    proof, target = await fixture(corruption)
    with pytest.raises(ForkRejected, match="manifest fork provenance"):
        await proof.evidence(target)


async def test_nonmanifest_contract_never_receives_manifest_evidence():
    proof, target = await fixture("missing", contract="generic-input-contract")
    assert await proof.evidence(target) == ()


async def test_neutral_fork_seals_server_provenance_without_changing_admission_identity():
    from mission_control.application.recovery.run_forks import (
        InMemoryRunSnapshotRepository,
        SemanticForkService,
    )
    from mission_control.domain.policies.forks import admission_request_ref
    from tests.fixtures.run_forks import fork_command, technical_snapshot

    snapshot = technical_snapshot("source")
    snapshots = InMemoryRunSnapshotRepository()
    await snapshots.put(snapshot)

    class Saga:
        async def source_baseline(self, scope, run):
            return None

        async def persisted_request(self, scope, request):
            return None

    class Provenance:
        async def evidence(self, target):
            assert target.request_scope == snapshot.request_scope
            return ("manifest:sha256:" + "a" * 64,)

    service = SemanticForkService(
        snapshots=snapshots, saga=Saga(), admission_provenance=Provenance()
    )
    prepared = await service.prepare(fork_command(snapshot))
    assert "manifest:sha256:" + "a" * 64 in prepared.target.admission_evidence_refs
    assert admission_request_ref(prepared.target) == prepared.patch.target_admission_request_ref
