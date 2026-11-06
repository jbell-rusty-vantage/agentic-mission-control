"""The resolution seam: `RuntimeResolver.resolve(selection)` (ADR-0063, design §4).

Six steps and nothing else: look up the lane, application and model; admit the pairing against
their declarations; build the neutral agent configuration with the catalog's model pin; call the
lane adapter's pure `compile`; compose the application side from its profile; seal the result.
Every refusal is a typed `ResolutionRefused` pointed into the manifest. There is no silent
fallback and no retry on another lane: lane choice is the author's.

Pure over its registries: no I/O, no clock. Bootstrap composes the registries; callers never
branch on a lane, a model vendor or an application.
"""

from __future__ import annotations

from collections.abc import Mapping

from mission_control.application.resolution.ports import (
    ApplicationRegistry,
    LaneRegistration,
    LaneRegistry,
    ModelCatalog,
)
from mission_control.domain.execution.data_class import (
    DATA_CLASSES,
    DEFAULT_DATA_CLASS_POLICY,
    DataClass,
    DataClassPolicy,
    admit_data_class,
)
from mission_control.domain.resolution.configuration import AgentConfiguration, Family, Vendor
from mission_control.domain.resolution.profiles import ApplicationProfile, ModelProfile
from mission_control.domain.resolution.resolved import (
    LaneCompileRefused,
    RefusalCode,
    ResolutionRefused,
    ResolvedRuntime,
)
from mission_control.domain.resolution.selection import LaneAdmission, RuntimeSelection

# Manifest pointers the resolver's own refusals name (lane-decided refusals carry their own).
LANE_POINTER = "/lane"
APPLICATION_POINTER = "/application"
MODEL_POINTER = "/model/profile"
DATA_CLASS_POINTER = "/data_class"
FAMILY_POINTER = "/behavior"
KNOWLEDGE_POINTER = "/application/knowledge"


def _refused(
    code: RefusalCode, pointer: str, reason: str, remedy: str, lane_profile: str | None = None
) -> ResolutionRefused:
    return ResolutionRefused(
        code=code, pointer=pointer, lane_profile=lane_profile, reason=reason, remedy=remedy
    )


def _within(data_class: DataClass, ceiling: DataClass) -> bool:
    return DATA_CLASSES.index(data_class) <= DATA_CLASSES.index(ceiling)


class RuntimeResolver:
    def __init__(
        self,
        lanes: LaneRegistry,
        applications: ApplicationRegistry,
        models: ModelCatalog,
        *,
        allow_unqualified_lanes: bool,
        data_class_policy: DataClassPolicy = DEFAULT_DATA_CLASS_POLICY,
        backend_contracts: Mapping[str, tuple[str, str]] | None = None,
    ) -> None:
        self._lanes = lanes
        self._applications = applications
        self._models = models
        self._allow_unqualified = allow_unqualified_lanes
        self._data_class_policy = data_class_policy
        # binding id -> (apply contract name, version) the Knowledge Services describe
        # advertises; `None` when this process has not read a describe (checked again at W0).
        self._backend_contracts = backend_contracts

    def resolve(self, selection: RuntimeSelection) -> ResolvedRuntime | ResolutionRefused:
        looked_up = self._look_up(selection)
        if isinstance(looked_up, ResolutionRefused):
            return looked_up
        lane, application, model = looked_up
        refusal = self._admit(selection, lane, application, model)
        if refusal is not None:
            return refusal
        agent = AgentConfiguration.create(
            lane_profile=selection.lane_profile,
            node_ref=selection.agent.node_ref,
            instructions_ref=selection.agent.instructions_ref,
            model=model.pin(selection.agent.model.settings),
            items=selection.agent.items,
            budgets=selection.agent.budgets,
            data_class=selection.agent.data_class,
            data_class_source=selection.agent.data_class_source,
        )
        try:
            binding, receipt = lane.adapter.compile(agent, selection.lane_options)
        except LaneCompileRefused as error:
            return error.refusal
        if binding.lane_profile != lane.profile or receipt.lane_profile != lane.profile:
            raise ValueError(f"lane {lane.profile} returned another lane's binding or receipt")
        return ResolvedRuntime.create(
            selection_digest=selection.digest(),
            agent=agent,
            lane_binding=binding,
            knowledge=application.knowledge,
            outputs=application.outputs,
            transfer=application.transfer,
            receipt=receipt,
            application_revision=application.revision,
        )

    # -- step 1 -------------------------------------------------------------------------------

    def _look_up(
        self, selection: RuntimeSelection
    ) -> tuple[LaneRegistration, ApplicationProfile, ModelProfile] | ResolutionRefused:
        try:
            lane = self._lanes.get(selection.lane_profile)
        except KeyError:
            return _refused(
                "LANE_UNKNOWN",
                LANE_POINTER,
                f"lane profile {selection.lane_profile} is not registered in this installation",
                f"choose one of {', '.join(self._lanes.profiles()) or 'no registered lane'}",
            )
        try:
            application = self._applications.get(selection.application_id)
        except KeyError:
            return _refused(
                "APPLICATION_UNKNOWN",
                APPLICATION_POINTER,
                f"application {selection.application_id} is not registered",
                f"choose one of {', '.join(self._applications.applications()) or 'none'}",
            )
        try:
            model = self._models.get(selection.model_profile)
        except KeyError:
            return _refused(
                "MODEL_UNKNOWN",
                MODEL_POINTER,
                f"model profile {selection.model_profile} is not in the model catalog",
                f"choose one of {', '.join(self._models.profiles()) or 'no model profile'}",
            )
        return lane, application, model

    # -- step 2 -------------------------------------------------------------------------------

    def _admit(
        self,
        selection: RuntimeSelection,
        lane: LaneRegistration,
        application: ApplicationProfile,
        model: ModelProfile,
    ) -> ResolutionRefused | None:
        profile = lane.profile
        if not lane.declaration.describe.qualified and not self._allow_unqualified:
            return _refused(
                "LANE_UNQUALIFIED",
                LANE_POINTER,
                f"lane profile {profile} has no recorded qualification",
                "record a lane qualification, or enable unqualified lanes for a local proof",
                profile,
            )
        return (
            self._route(lane, model.vendor, f"{model.vendor} model {model.model_id}")
            or self._data_class(
                lane,
                selection.agent.data_class,
                (
                    (f"application {application.application_id}", application.data_class_ceiling),
                    (f"model profile {model.profile}", model.data_class_ceiling),
                ),
            )
            or self._family(lane, selection.family)
            or self._knowledge(lane, application)
        )

    def admit(self, admission: LaneAdmission) -> ResolutionRefused | None:
        """Steps 1 and 2 alone, for a node whose lane cannot compile the whole node yet
        (OC-R3; the describe-only lanes until the provider sweep): the lane and application
        lookups, the model route of the declared vendor (when one is declared), the Data Class
        against the lane's policy and the application's ceiling, and the family. Lane
        qualification stays the executing worker's (`LaneRegistry.admit`); item support stays
        the lane's launch resolver's until its compile takes the node."""

        try:
            lane = self._lanes.get(admission.lane_profile)
        except KeyError:
            return _refused(
                "LANE_UNKNOWN",
                LANE_POINTER,
                f"lane profile {admission.lane_profile} is not registered in this installation",
                f"choose one of {', '.join(self._lanes.profiles()) or 'no registered lane'}",
            )
        try:
            application = self._applications.get(admission.application_id)
        except KeyError:
            return _refused(
                "APPLICATION_UNKNOWN",
                APPLICATION_POINTER,
                f"application {admission.application_id} is not registered",
                f"choose one of {', '.join(self._applications.applications()) or 'none'}",
            )
        route = (
            self._route(lane, admission.vendor, f"{admission.vendor} models")
            if admission.vendor is not None
            else None
        )
        return (
            route
            or self._data_class(
                lane,
                admission.data_class,
                ((f"application {application.application_id}", application.data_class_ceiling),),
            )
            or self._family(lane, admission.family)
        )

    def _route(
        self, lane: LaneRegistration, vendor: Vendor, model: str
    ) -> ResolutionRefused | None:
        route = lane.declaration.route(vendor)
        if route is None or route.verdict == "unsupported":
            return _refused(
                "MODEL_ROUTE_UNSUPPORTED",
                MODEL_POINTER,
                f"lane {lane.profile} has no route for {model}",
                f"choose a model profile whose vendor {lane.profile} routes",
                lane.profile,
            )
        return None

    def _data_class(
        self,
        lane: LaneRegistration,
        data_class: DataClass,
        ceilings: tuple[tuple[str, DataClass], ...],
    ) -> ResolutionRefused | None:
        profile = lane.profile
        issue = admit_data_class(
            profile, data_class, policy=self._data_class_policy, pointer=DATA_CLASS_POINTER
        )
        if issue is not None:
            return _refused(
                "DATA_CLASS_NOT_ADMITTED",
                DATA_CLASS_POINTER,
                issue.message,
                "lower the mission's data class or choose a lane that admits it",
                profile,
            )
        for name, ceiling in ceilings:
            if not _within(data_class, ceiling):
                return _refused(
                    "DATA_CLASS_NOT_ADMITTED",
                    DATA_CLASS_POINTER,
                    f"{name} admits data up to {ceiling}; the mission's data class is "
                    f"{data_class} (an undeclared mission is its application's ceiling)",
                    "declare or lower the mission's data class, or choose another model or "
                    "application",
                    profile,
                )
        return None

    def _family(self, lane: LaneRegistration, family: Family) -> ResolutionRefused | None:
        support = lane.declaration.families[family]
        if support == "unsupported" or (support == "unqualified" and not self._allow_unqualified):
            return _refused(
                "BLUEPRINT_FAMILY_UNSUPPORTED",
                FAMILY_POINTER,
                f"lane {lane.profile} declares {family} {support}",
                f"run {family} on a lane that supports it, or change the behavior",
                lane.profile,
            )
        return None

    def _knowledge(
        self, lane: LaneRegistration, application: ApplicationProfile
    ) -> ResolutionRefused | None:
        if self._backend_contracts is None:
            return None
        knowledge = application.knowledge
        advertised = self._backend_contracts.get(knowledge.binding_id)
        expected = (knowledge.apply_contract_name, knowledge.apply_contract_version)
        if advertised == expected:
            return None
        return _refused(
            "APPLY_CONTRACT_MISMATCH",
            KNOWLEDGE_POINTER,
            f"application {application.application_id} expects {expected[0]}@"
            f"{expected[1]} on {knowledge.binding_id}; Knowledge Services advertises "
            f"{advertised[0] + '@' + advertised[1] if advertised else 'no such binding'}",
            "align deployments/<app>/application.toml with the installed KS binding",
            lane.profile,
        )


__all__ = ["RuntimeResolver"]
