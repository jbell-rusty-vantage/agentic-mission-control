from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from mission_control.application.installations.registry import (
    ApplicationBinding,
    ApplicationRegistry,
    ApplicationScopeDenied,
    HostedAgentApiTerms,
    InstallationObservation,
    InstallationUnavailable,
    VerifiedApplicationIdentity,
    request_scope,
)
from mission_control.contracts.canonical import canonical_digest
from mission_control.domain.execution.data_class import DEFAULT_DATA_CLASS_POLICY
from mission_control.domain.execution.session_retention import DEFAULT_SESSION_RETENTION_POLICY

INSTALLATION = UUID("00000000-0000-0000-0000-000000000001")
TENANT = UUID("00000000-0000-0000-0000-000000000002")


def setup_registry():
    binding = ApplicationBinding.seal(
        application_id="biotech",
        installation_id=INSTALLATION,
        binding_version="1",
        supabase_project_ref="biotech-project",
        database_secret_ref="BIOTECH_DATABASE_URL",
        accepted_issuers=frozenset({"https://biotech.invalid/auth/v1"}),
        accepted_audiences=frozenset({"authenticated"}),
        required_component_version="1.0.0",
    )
    identity = VerifiedApplicationIdentity(
        issuer="https://biotech.invalid/auth/v1",
        audiences=frozenset({"authenticated"}),
        application_id="biotech",
        installation_id=INSTALLATION,
        tenant_id=TENANT,
    )
    return ApplicationRegistry((binding,)), identity


def test_verified_installation_required_and_revocation_is_immediate():
    registry, identity = setup_registry()
    with pytest.raises(InstallationUnavailable):
        registry.resolve("biotech", identity)
    registry.observe(
        "biotech",
        InstallationObservation(
            INSTALLATION,
            "biotech",
            "biotech-project",
            frozenset({"1.0.0"}),
        ),
    )
    assert registry.resolve("biotech", identity).database_secret_ref == "BIOTECH_DATABASE_URL"
    assert request_scope(identity) == (
        "mc/00000000-0000-0000-0000-000000000001/biotech/00000000-0000-0000-0000-000000000002"
    )
    registry.disable("biotech")
    with pytest.raises(InstallationUnavailable):
        registry.resolve("biotech", identity)


def test_application_switch_cannot_select_other_database():
    registry, identity = setup_registry()
    with pytest.raises(ApplicationScopeDenied):
        registry.resolve("ai-engineer", identity)


def test_mismatched_project_never_marks_application_ready():
    registry, identity = setup_registry()
    with pytest.raises(InstallationUnavailable):
        registry.observe(
            "biotech",
            InstallationObservation(
                INSTALLATION,
                "biotech",
                "other-project",
                frozenset({"1.0.0"}),
            ),
        )
    with pytest.raises(InstallationUnavailable):
        registry.resolve("biotech", identity)


def test_immutable_pin_cannot_silently_rotate_to_another_binding():
    registry, identity = setup_registry()
    registry.observe(
        "biotech",
        InstallationObservation(
            INSTALLATION,
            "biotech",
            "biotech-project",
            frozenset({"1.0.0"}),
        ),
    )
    with pytest.raises(InstallationUnavailable):
        registry.resolve("biotech", identity, pinned_binding_digest="sha256:" + "b" * 64)


def test_binding_digest_detects_project_and_authority_drift():
    registry, _ = setup_registry()
    binding = registry.bindings["biotech"]
    for field, value in (
        ("supabase_project_ref", "other-project"),
        ("database_secret_ref", "OTHER_DATABASE_URL"),
        ("accepted_issuers", frozenset({"https://other.invalid/auth/v1"})),
    ):
        payload = binding.model_dump(mode="python")
        payload[field] = value
        with pytest.raises(ValueError, match="digest does not match"):
            ApplicationBinding.model_validate(payload)


# --- HL-18: an Application's terms on the hosted agent APIs (SPEC-06 section 8) ----

BIOTECH: dict[str, Any] = {
    "application_id": "biotech",
    "installation_id": INSTALLATION,
    "binding_version": "1",
    "supabase_project_ref": "biotech-project",
    "database_secret_ref": "BIOTECH_DATABASE_URL",
    "accepted_issuers": frozenset({"https://biotech.invalid/auth/v1"}),
    "accepted_audiences": frozenset({"authenticated"}),
    "required_component_version": "1.0.0",
}


def test_a_binding_without_hosted_terms_keeps_its_pre_hl18_digest_and_the_defaults():
    binding = ApplicationBinding.seal(**BIOTECH)
    # The digest of exactly the eight fields a binding had before HL-18: existing operator
    # pins (worker binding digests, execution binding pins) stay valid.
    assert binding.binding_digest == canonical_digest(BIOTECH)
    assert binding.hosted_agent_apis is None
    assert binding.data_class_policy == DEFAULT_DATA_CLASS_POLICY
    assert binding.session_retention == DEFAULT_SESSION_RETENTION_POLICY


def test_hosted_terms_are_pinned_by_the_binding_digest():
    terms = HostedAgentApiTerms(
        widened_data_classes={"claude_managed": frozenset({"confidential"})},
        session_retention_seconds=3_600,
    )
    binding = ApplicationBinding.seal(**BIOTECH, hosted_agent_apis=terms)
    assert binding.binding_digest != ApplicationBinding.seal(**BIOTECH).binding_digest
    assert binding.data_class_policy.admits("claude_managed", "confidential")
    assert not binding.data_class_policy.admits("codex_agents", "confidential")
    assert binding.session_retention.retention == timedelta(hours=1)
    # Widening after sealing (or dropping the terms) no longer matches the pin.
    for tampered in (
        {"widened_data_classes": {"codex_agents": ["confidential"]}},
        None,
    ):
        payload = binding.model_dump(mode="python")
        payload["hosted_agent_apis"] = tampered
        with pytest.raises(ValueError, match="digest does not match"):
            ApplicationBinding.model_validate(payload)
    reloaded = ApplicationBinding.model_validate_json(binding.model_dump_json())
    assert reloaded == binding


@pytest.mark.parametrize("data_class", ["phi", "secret"])
@pytest.mark.parametrize("profile", ["claude_managed", "codex_agents"])
def test_no_binding_can_widen_a_hosted_agent_api_to_phi_or_secret(profile, data_class):
    with pytest.raises(ValidationError, match="ceiling is confidential"):
        ApplicationBinding.seal(
            **BIOTECH,
            hosted_agent_apis={"widened_data_classes": {profile: [data_class]}},
        )


def test_hosted_terms_name_only_restricted_profiles_and_a_non_negative_retention():
    with pytest.raises(ValidationError, match="no data class policy to widen"):
        HostedAgentApiTerms(widened_data_classes={"codex": frozenset({"confidential"})})
    with pytest.raises(ValidationError):
        HostedAgentApiTerms(session_retention_seconds=-1)
