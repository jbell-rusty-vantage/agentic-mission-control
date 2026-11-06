"""Application profile conformance (design §10): every `deployments/*/application.toml`.

Each profile loads through the bootstrap loader, registers (the output minimums, an
interpretation of annex section 5 using KS use classes,
hold), names a binding the Knowledge Services backend descriptor advertises with the same apply
contract, storage class and write atomicity, declares readback only where the backend serves
it, and names an apply payload layout the gateway builds. The descriptors are the checked-in
copy in `ks_backend_descriptors.json` (KS commit recorded there), so drift is caught offline;
W0 checks the same facts against the live `knowledge.describe`.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import pytest

from mission_control.application.knowledge.apply_payload import APPLY_PAYLOAD_LAYOUTS
from mission_control.application.resolution.registries import ApplicationRegistry
from mission_control.bootstrap.application_profiles import (
    ApplicationProfileError,
    compose_application_registry,
    load_application_file,
)
from mission_control.bootstrap.workspace_closures import workspace_closure_profile
from mission_control.domain.resolution.profiles import (
    ANNEX_CONSEQUENTIAL_SIGNOFF_CLASSES,
    ANNEX_REQUIRED_REVIEW_CLASSES,
    below_annex_minimums,
)

DEPLOYMENTS = Path(__file__).resolve().parents[3] / "deployments"
PROFILE_FILES = sorted(DEPLOYMENTS.glob("*/application.toml"))
IDS = [path.parent.name for path in PROFILE_FILES]
DESCRIPTORS: dict[str, dict[str, Any]] = {
    backend["id"]: backend
    for backend in json.loads(
        (Path(__file__).with_name("ks_backend_descriptors.json")).read_text(encoding="utf-8")
    )["backends"]
}


@pytest.mark.parametrize("path", PROFILE_FILES, ids=IDS)
def test_workspace_closure_keys_are_read_by_composition(path: Path) -> None:
    """OVE-204 slice 5: every `[workspace]` key is a profile field and is what the worker
    composition hands the Deep Agents adapter (declared and consumed, unlike
    `hosted_session_retention_days`)."""

    declared = tomllib.loads(path.read_text(encoding="utf-8"))["workspace"]
    assert set(declared) == {
        "closure_enabled",
        "closure_max_files",
        "closure_max_bytes",
        "closure_retention",
    }
    composed = workspace_closure_profile(DEPLOYMENTS, path.parent.name)
    assert composed.model_dump() == declared
    assert composed == load_application_file(path).profile.workspace


def test_both_applications_have_a_profile() -> None:
    assert IDS == ["ai-engineer", "biotech"]


@pytest.mark.parametrize("path", PROFILE_FILES, ids=IDS)
def test_application_profile_loads_and_names_its_directory(path: Path) -> None:
    loaded = load_application_file(path)

    assert loaded.profile.application_id == path.parent.name
    assert loaded.profile.outputs.assessment_pin
    assert (path.parent / "target.toml").is_file()


@pytest.mark.parametrize("path", PROFILE_FILES, ids=IDS)
def test_minimums_are_not_below_the_annex_required_classes(path: Path) -> None:
    profile = load_application_file(path).profile
    outputs = profile.outputs

    assert below_annex_minimums(profile) == ()
    assert set(outputs.required_review_classes) >= ANNEX_REQUIRED_REVIEW_CLASSES
    assert set(outputs.consequential_signoff_classes) >= ANNEX_CONSEQUENTIAL_SIGNOFF_CLASSES
    ApplicationRegistry((profile,))


@pytest.mark.parametrize("path", PROFILE_FILES, ids=IDS)
def test_the_binding_is_advertised_with_the_same_apply_contract(path: Path) -> None:
    knowledge = load_application_file(path).profile.knowledge
    descriptor = DESCRIPTORS.get(knowledge.binding_id)

    assert descriptor is not None, f"KS advertises no backend {knowledge.binding_id}"
    assert descriptor["nativeContract"] == {
        "name": knowledge.apply_contract_name,
        "version": knowledge.apply_contract_version,
    }
    assert descriptor["storageClass"] == knowledge.storage_class
    assert descriptor["writeAtomicity"] == knowledge.write_atomicity
    served = set(descriptor["capabilities"]) | {
        row["capability"] for row in descriptor["conditionalCapabilities"]
    }
    assert "apply" in served
    readback = "readback" in descriptor["capabilities"]
    assert knowledge.readback_capability == ("native" if readback else "unsupported")


@pytest.mark.parametrize("path", PROFILE_FILES, ids=IDS)
def test_the_gateway_builds_the_declared_payload_layout(path: Path) -> None:
    assert load_application_file(path).profile.knowledge.intent_schema_ref in (
        APPLY_PAYLOAD_LAYOUTS
    )


@pytest.mark.parametrize("path", PROFILE_FILES, ids=IDS)
def test_installation_defaults_name_the_operator_settings(path: Path) -> None:
    defaults = load_application_file(path).installation

    assert defaults.temporal_task_queue and defaults.langsmith_project
    assert defaults.agent_server_langsmith_project and defaults.capability_workspace_root


def test_a_weakened_profile_is_refused_at_registration() -> None:
    profile = load_application_file(PROFILE_FILES[0]).profile
    weakened = profile.model_copy(
        update={
            "outputs": profile.outputs.model_copy(update={"required_review_classes": ("official",)})
        }
    )
    with pytest.raises(ValueError, match=r"required_review_classes omits \['consequential'\]"):
        ApplicationRegistry((weakened,))


def test_composition_loads_exactly_the_named_applications(tmp_path: Path) -> None:
    registry = compose_application_registry(DEPLOYMENTS, ("biotech",))

    assert registry.applications() == ("biotech",)
    with pytest.raises(ApplicationProfileError, match="no Application Profile at"):
        compose_application_registry(tmp_path, ("biotech",))
    misplaced = tmp_path / "other" / "application.toml"
    misplaced.parent.mkdir()
    misplaced.write_text(PROFILE_FILES[1].read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ApplicationProfileError, match="declares application biotech, not other"):
        compose_application_registry(tmp_path, ("other",))


def test_profile_files_are_unique_per_application() -> None:
    assert len(IDS) == len(set(IDS))
