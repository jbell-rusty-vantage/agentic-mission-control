"""Verify noncognitive stages against the run's committed manifest and binding."""

from __future__ import annotations

from typing import Any, Protocol

from mission_control.application.authoring.service import ControlPlaneService
from mission_control.application.execution.service import RunControlService
from mission_control.application.programs.human_gates import stagegraph_human_gates
from mission_control.application.programs.service import StageGraphOperationTemplateProvider
from mission_control.domain.authoring.canonical import sha256_digest
from mission_control.domain.authoring.contracts import StageGraphBlueprint
from mission_control.domain.authoring.mission_definition import MissionDefinition
from mission_control.domain.programs.contracts import StageGraphAdmissionActivityRequest
from mission_control.domain.programs.human_gate import HumanGateSpec


class CommittedManifestReader(Protocol):
    async def run_subscriptions(
        self, request_scope: str, run_key: str
    ) -> dict[str, Any] | None: ...


class ManifestStageGraphHumanGateProvider:
    def __init__(
        self,
        definitions: CommittedManifestReader,
        configurations: ControlPlaneService,
        runs: RunControlService,
        templates: StageGraphOperationTemplateProvider,
    ) -> None:
        self._definitions = definitions
        self._configurations = configurations
        self._runs = runs
        self._templates = templates

    async def verify(
        self, request: StageGraphAdmissionActivityRequest
    ) -> tuple[HumanGateSpec, ...]:
        run = await self._runs.get_run(request.request_scope, request.run_id)
        configuration = await self._configurations.retrieve_for_admission(
            run.effective_configuration_digest
        )
        if (
            request.semantic_input_binding_ref != f"semantic-input:manifest:{request.run_id}"
            or request.effective_configuration_digest != run.effective_configuration_digest
            or configuration.digest != run.effective_configuration_digest
            or sha256_digest(configuration.selected_blueprint)
            != sha256_digest(StageGraphBlueprint.model_validate(request.blueprint))
        ):
            raise ValueError(
                "Human Gate admission differs from the admitted semantic configuration"
            )
        template = await self._templates.get_template(
            semantic_input_binding_ref=request.semantic_input_binding_ref,
            operation_request_key=request.proposal.operation_request_key,
            request_scope=request.request_scope,
            run_id=request.run_id,
        )
        if (
            template.request_scope != request.request_scope
            or template.effective_configuration_digest != run.effective_configuration_digest
        ):
            raise ValueError("Human Gate semantic template differs from the admitted run")
        info = await self._definitions.run_subscriptions(request.request_scope, request.run_id)
        if info is None:
            raise ValueError("Human Gate admission requires the committed run definition")
        gates = stagegraph_human_gates(MissionDefinition.model_validate(info["definition"]))
        if set(request.control_gate_keys) != {gate.gate_key for gate in gates}:
            raise ValueError("Human Gate stage set differs from the committed run definition")
        if request.human_gate is not None and request.human_gate not in gates:
            raise ValueError("Human Gate policy differs from the committed run definition")
        return gates
