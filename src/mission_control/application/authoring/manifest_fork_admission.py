"""Trusted submitted-manifest origin for a derived run's ordinary fork admission."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from mission_control.application.authoring.manifest_submit import SUBMIT_ISSUER
from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.execution.service import RunControlService
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import ExactDefinitionRef
from mission_control.domain.authoring.errors import ControlPlaneError
from mission_control.domain.authoring.manifest_lowering import MANIFEST_INPUT_CONTRACT
from mission_control.domain.policies.contracts import RunPhase, RunRequest
from mission_control.domain.policies.errors import RunControlNotFound
from mission_control.domain.policies.forks import ForkRejected


@dataclass(frozen=True)
class SubmittedManifestConfiguration:
    run_id: str
    actor_id: str
    program_actor_id: str
    manifest_digest: str
    program: dict[str, Any]
    program_digest: str


class SubmittedManifestConfigurations(Protocol):
    async def submitted_configurations(
        self,
        request_scope: str,
        configuration_digest: str,
    ) -> tuple[SubmittedManifestConfiguration, ...]: ...


class ManifestForkAdmissionProvenance:
    def __init__(
        self,
        submissions: SubmittedManifestConfigurations,
        run_control: RunControlService,
        control_plane: ControlPlaneService,
    ) -> None:
        self._submissions, self._control, self._catalog = submissions, run_control, control_plane

    async def evidence(self, target: RunRequest) -> tuple[str, ...]:
        try:
            configuration = await self._catalog.retrieve_for_admission(
                target.effective_configuration_digest
            )
        except (ControlPlaneError, LookupError, ValueError) as error:
            raise self._refused("target configuration unavailable") from error
        if configuration.workflow_type.input_admission_contract != MANIFEST_INPUT_CONTRACT:
            return ()
        rows = await self._submissions.submitted_configurations(
            target.request_scope, target.effective_configuration_digest
        )
        if len(rows) != 1:
            raise self._refused("missing or ambiguous submitted configuration")
        row = rows[0]
        try:
            workflow_ref = ExactDefinitionRef.model_validate(row.program.get("workflow_type_ref"))
        except ValueError as error:
            raise self._refused("submitted program reference invalid") from error
        if (
            row.actor_id != target.actor.actor_id
            or row.program_actor_id != row.actor_id
            or sha256_digest(row.program) != row.program_digest
            or row.program.get("contract") != "mc.manifest-compiled-program/1"
            or row.program.get("effective_configuration_digest")
            != target.effective_configuration_digest
            or workflow_ref != target.workflow_type_ref
        ):
            raise self._refused("submitted program authority or exact configuration mismatch")
        try:
            origin = await self._control.get_run(target.request_scope, row.run_id)
        except RunControlNotFound as error:
            raise self._refused("submitted run unavailable") from error
        if (
            origin.request_scope != target.request_scope
            or origin.idempotency_issuer
            != json.dumps([SUBMIT_ISSUER, row.actor_id], separators=(",", ":"))
            or origin.effective_configuration_digest != target.effective_configuration_digest
            or origin.workflow_type_ref != target.workflow_type_ref
            or origin.input_manifest != target.input_manifest
        ):
            raise self._refused("submitted run does not bind this exact target")
        transitions = await self._control.list_transitions(target.request_scope, row.run_id)
        admitted = transitions[0] if transitions else None
        marker = f"manifest:{row.manifest_digest}"
        if (
            not re.fullmatch(r"sha256:[0-9a-f]{64}", row.manifest_digest)
            or admitted is None
            or admitted.run_id != origin.run_id
            or admitted.prior_phase is not None
            or admitted.prior_projection is not None
            or admitted.resulting_phase != RunPhase.PENDING
            or admitted.resulting_projection.run_id != origin.run_id
            or admitted.resulting_projection.request_scope != target.request_scope
            or admitted.resulting_projection.idempotency_issuer != origin.idempotency_issuer
            or admitted.resulting_projection.request_id != origin.request_id
            or admitted.prior_version != 0
            or admitted.resulting_version != 1
            or admitted.command_id != f"admission:{origin.request_id}"
            or admitted.actor.actor_id != row.actor_id
            or marker not in admitted.evidence_refs
            or admitted.resulting_projection.effective_configuration_digest
            != target.effective_configuration_digest
            or admitted.resulting_projection.workflow_type_ref != target.workflow_type_ref
            or admitted.resulting_projection.input_manifest != target.input_manifest
        ):
            raise self._refused("no exact immutable manifest admission transition")
        return (
            marker,
            f"submitted-manifest-run:{row.run_id}:admission:1",
            f"submitted-manifest-program:{row.program_digest}",
        )

    @staticmethod
    def _refused(reason: str) -> ForkRejected:
        return ForkRejected(
            "fork_admission_rejected",
            f"manifest fork provenance: {reason}",
            reasons=("manifest_provenance_unavailable",),
        )
