"""Bootstrap composition of the knowledge binding (SV-16 deliverable 3).

Settings name the binding URL, audience, issuer and key files; nothing configured composes
nothing, a partial or required-but-absent configuration fails closed naming the missing
variables (never values), and a complete one loads the Ed25519 keys, runs the ``describe``
preflight under a standalone service credential, checks the descriptor against the
deployment and records its digest in a sanitized startup receipt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from mission_control.adapters.knowledge.credentials import (
    CredentialVerifier,
    generate_signing_key,
    publish_jwks,
    write_private_jwk,
)
from mission_control.application.knowledge.toolset import TOOL_NAMES
from mission_control.bootstrap.composition import (
    KnowledgeConfigurationError,
    compose_knowledge_lane,
    knowledge_configuration,
)
from mission_control.contracts.knowledge_protocol import digest_canonical
from tests.fixtures.isolated_settings import isolated_settings
from tests.fixtures.knowledge_binding import (
    FakeKnowledgeBinding,
    SteppingClock,
    describe_document,
)

INSTALLATION = "00000000-0000-7000-8000-000000000001"


def configured(tmp_path: Path, **overrides: Any):
    active = generate_signing_key("mc-k2")
    retiring = generate_signing_key("mc-k1")
    write_private_jwk(active, tmp_path / "active.jwk.json")
    write_private_jwk(retiring, tmp_path / "retiring.jwk.json")
    settings = isolated_settings(
        knowledge_binding_url="http://127.0.0.1:4310",
        knowledge_binding_audience="ks-executor",
        knowledge_issuer="mission-control",
        knowledge_issuer_key_file=tmp_path / "active.jwk.json",
        knowledge_issuer_retiring_key_file=tmp_path / "retiring.jwk.json",
        **overrides,
    )
    return settings, active, retiring


def test_nothing_configured_composes_nothing_and_partial_fails_closed(tmp_path: Path) -> None:
    assert knowledge_configuration(isolated_settings(), application_id="biotech") is None
    with pytest.raises(KnowledgeConfigurationError) as missing:
        knowledge_configuration(
            isolated_settings(knowledge_binding_url="http://127.0.0.1:4310"),
            application_id="biotech",
        )
    message = str(missing.value)
    assert "KNOWLEDGE_ISSUER_KEY_FILE" in message and "KNOWLEDGE_BINDING_AUDIENCE" in message
    assert "127.0.0.1" not in message  # names, never values
    with pytest.raises(KnowledgeConfigurationError, match="KNOWLEDGE_BINDING_URL"):
        knowledge_configuration(
            isolated_settings(knowledge_gateway_required=True), application_id="biotech"
        )
    settings, _active, _retiring = configured(tmp_path)
    # OC-R4: an application without a profile file has no binding (fail closed); the binding
    # and apply contract are its `deployments/<app>/application.toml`, never a settings map.
    with pytest.raises(KnowledgeConfigurationError, match="no Application Profile at"):
        knowledge_configuration(settings, application_id="unknown-app")
    ai = knowledge_configuration(settings, application_id="ai-engineer")
    biotech = knowledge_configuration(settings, application_id="biotech")
    assert ai is not None and ai.binding_id == "aiengineer-postgres"
    assert ai.knowledge.apply_contract_name == "knowledge-ingestion-intent"
    assert biotech is not None and biotech.binding_id == "biotech-graph"
    assert biotech.knowledge.apply_contract_name == "biotech-knowledge-apply"


async def test_describe_preflight_records_the_descriptor_digest(tmp_path: Path) -> None:
    settings, active, retiring = configured(tmp_path)
    clock = SteppingClock()
    fake = FakeKnowledgeBinding(
        verifier=CredentialVerifier(
            issuer="mission-control",
            audience="ks-executor",
            jwks=publish_jwks(active, retiring),
            clock=clock,
        ),
        clock=clock,
        binding="biotech-graph",
        application="biotech",
    )
    lane = await compose_knowledge_lane(
        settings,
        cast(Any, object()),
        application_id="biotech",
        installation_id=INSTALLATION,
        client=fake,
        clock=clock,
    )
    assert lane is not None
    receipt = lane.startup_receipt
    assert receipt["descriptor_digest"] == digest_canonical(
        describe_document("biotech-graph", "biotech")
    )
    assert (receipt["binding"], receipt["active_kid"], receipt["retiring_kid"]) == (
        "biotech-graph",
        "mc-k2",
        "mc-k1",
    )
    assert receipt["endpoint"] == "http://127.0.0.1:4310"
    rendered = json.dumps(receipt)
    for key in (active, retiring):
        assert str(key.key.as_dict(private=True)["d"]) not in rendered
    (describe,) = fake.calls_of("knowledge.describe")
    assert describe.claims.origin.kind == "standalone"
    assert describe.claims.operations == ["knowledge.describe"]
    assert set(lane.support.tools) == set(TOOL_NAMES)
    assert {component.tool_name for component in lane.components} == set(TOOL_NAMES)
    # Six semantic tools also serve the retained v1 submit schema for admitted old pins.
    current = {component.ref.digest for component in lane.components}
    legacy_submit_digest = "sha256:16d044dda28c3bb0e82a703e55cbc151cfd8cd70c986e283208c6c42e2823bc0"
    assert len(TOOL_NAMES) == 7  # + knowledge_read_intent (OVE-204 slice 4)
    assert set(lane.registry_tools) == current | {legacy_submit_digest}
    legacy = lane.registry_tools[legacy_submit_digest]
    assert legacy.name == "submit_output"
    schema = legacy.tool_call_schema.model_json_schema()
    assert set(schema["properties"]) == {"obligation", "deliverable", "items"}
    assert set(schema["required"]) == {"obligation", "items"}


async def test_a_descriptor_for_another_binding_or_issuer_fails_closed(tmp_path: Path) -> None:
    settings, active, retiring = configured(tmp_path)
    clock = SteppingClock()
    fake = FakeKnowledgeBinding(
        verifier=CredentialVerifier(
            issuer="mission-control",
            audience="ks-executor",
            jwks=publish_jwks(active, retiring),
            clock=clock,
        ),
        clock=clock,
        binding="biotech-graph",
        application="ai-engineer",
    )
    with pytest.raises(KnowledgeConfigurationError, match="application"):
        await compose_knowledge_lane(
            settings,
            cast(Any, object()),
            application_id="biotech",
            installation_id=INSTALLATION,
            client=fake,
            clock=clock,
        )
    stranger = FakeKnowledgeBinding(
        verifier=CredentialVerifier(
            issuer="mission-control",
            audience="ks-executor",
            jwks=publish_jwks(generate_signing_key("other")),
            clock=clock,
        ),
        clock=clock,
        binding="biotech-graph",
        application="biotech",
    )
    with pytest.raises(KnowledgeConfigurationError, match="SCOPE_DENIED"):
        await compose_knowledge_lane(
            settings,
            cast(Any, object()),
            application_id="biotech",
            installation_id=INSTALLATION,
            client=stranger,
            clock=clock,
        )


async def test_a_scripted_census_auditor_is_refused_outside_a_disposable_installation(
    tmp_path: Path,
) -> None:
    """WI-03 S7: the producer-started report.assess path never runs on a scripted double in an
    installation that is not an identified disposable proof target."""

    for disposable in (False, True):
        settings, active, retiring = configured(
            tmp_path, knowledge_disposable_installation=disposable
        )
        clock = SteppingClock()
        fake = FakeKnowledgeBinding(
            verifier=CredentialVerifier(
                issuer="mission-control",
                audience="ks-executor",
                jwks=publish_jwks(active, retiring),
                clock=clock,
            ),
            clock=clock,
            binding="biotech-graph",
            application="biotech",
        )
        fake.auditor_kind = "scripted"
        compose = compose_knowledge_lane(
            settings,
            cast(Any, object()),
            application_id="biotech",
            installation_id=INSTALLATION,
            client=fake,
            clock=clock,
        )
        if not disposable:
            with pytest.raises(KnowledgeConfigurationError, match="scripted census auditor"):
                await compose
        else:
            lane = await compose
            assert lane is not None and lane.startup_receipt["auditor_kind"] == "scripted"


# ------------------------------------------------------------------ W1 D5 / D6

COMPONENT = "00000000-0000-7000-8000-00000000c0de"


def _component_fake(active: Any, retiring: Any, clock: SteppingClock) -> FakeKnowledgeBinding:
    """A binding that, like the KS executor, installs the component installation only."""

    return FakeKnowledgeBinding(
        verifier=CredentialVerifier(
            issuer="mission-control",
            audience="ks-executor",
            jwks=publish_jwks(active, retiring),
            clock=clock,
        ),
        clock=clock,
        binding="biotech-graph",
        application="biotech",
        installation_id=COMPONENT,
    )


async def test_origins_name_the_component_installation_while_the_scope_keeps_mc(
    tmp_path: Path,
) -> None:
    """W1 D6: MC sends the KS component installation id (not its own) in every K01 origin;
    the startup describe under it is the executor's own check, and the MC request scope keeps
    the Mission Control installation."""

    settings, active, retiring = configured(tmp_path, knowledge_component_installation_id=COMPONENT)
    clock = SteppingClock()
    fake = _component_fake(active, retiring, clock)
    lane = await compose_knowledge_lane(
        settings,
        cast(Any, object()),
        application_id="biotech",
        installation_id=INSTALLATION,
        client=fake,
        clock=clock,
    )
    assert lane is not None
    (describe,) = fake.calls_of("knowledge.describe")
    assert describe.claims.origin.installationId == COMPONENT
    assert lane.startup_receipt["component_installation_id"] == COMPONENT
    from mission_control.application.knowledge.toolset import LiveInvocation

    live = LiveInvocation(
        request_scope=f"mc/{INSTALLATION}/biotech/00000000-0000-7000-8000-0000000000aa",
        run_id="run-1",
        operation_id="op-1",
        operation_attempt=1,
        execution_generation=1,
        lane="deep_agents",
        mission_id="mission-1",
    )
    # Provenance slice 1: the composed toolset locates ledger ids on the runtime pool.
    from mission_control.adapters.postgres.knowledge.invocation_locator import (
        PostgresInvocationLocator,
    )

    assert isinstance(lane.toolset.locator, PostgresInvocationLocator)
    access = lane.toolset.access(live)
    assert access.wire_origin().installationId == COMPONENT
    assert access.origin.installation_id == INSTALLATION
    assert access.scope.startswith(f"mc/{INSTALLATION}/")
    recovery = lane.toolset._recovery(live)
    assert recovery.wire_origin().installationId == COMPONENT
    assert recovery.in_scope_of(access.wire_origin())
    assert recovery.scope == access.scope


async def test_an_origin_naming_another_installation_is_refused_at_startup(
    tmp_path: Path,
) -> None:
    """W1 D6 negative: MC's own id (the W1 failure) or another component id fails closed."""

    for component in (None, "00000000-0000-7000-8000-0000000000ff"):
        overrides = {} if component is None else {"knowledge_component_installation_id": component}
        settings, active, retiring = configured(tmp_path, **overrides)
        clock = SteppingClock()
        with pytest.raises(
            KnowledgeConfigurationError, match="SCOPE_DENIED.*COMPONENT_INSTALLATION"
        ):
            await compose_knowledge_lane(
                settings,
                cast(Any, object()),
                application_id="biotech",
                installation_id=INSTALLATION,
                client=_component_fake(active, retiring, clock),
                clock=clock,
            )


def test_a_required_binding_names_its_component_installation(tmp_path: Path) -> None:
    settings, _active, _retiring = configured(tmp_path, knowledge_gateway_required=True)
    with pytest.raises(KnowledgeConfigurationError, match="KNOWLEDGE_COMPONENT_INSTALLATION_ID"):
        knowledge_configuration(settings, application_id="biotech")
    settings, _active, _retiring = configured(
        tmp_path,
        knowledge_gateway_required=True,
        knowledge_component_installation_id=COMPONENT,
    )
    configuration = knowledge_configuration(settings, application_id="biotech")
    assert configuration is not None
    assert configuration.knowledge_installation(INSTALLATION) == COMPONENT


@pytest.mark.parametrize(
    ("override", "variable"),
    [
        ({"knowledge_issuer": "mission-control/biotech"}, "KNOWLEDGE_ISSUER"),
        (
            {"knowledge_binding_audience": "knowledge-services-executor/biotech"},
            "KNOWLEDGE_BINDING_AUDIENCE",
        ),
    ],
)
def test_issuer_and_audience_must_be_k01_names(
    tmp_path: Path, override: dict[str, str], variable: str
) -> None:
    """W1 D5: a slash-joined value (the W0 generator's) is refused at configuration, by name."""

    settings, _active, _retiring = configured(tmp_path)
    settings = settings.model_copy(update=override)
    with pytest.raises(KnowledgeConfigurationError, match=variable) as refused:
        knowledge_configuration(settings, application_id="biotech")
    assert "/biotech" not in str(refused.value)  # names, never values
    accepted = settings.model_copy(
        update={
            "knowledge_issuer": "mission-control.biotech",
            "knowledge_binding_audience": "knowledge-services-executor.biotech",
        }
    )
    assert knowledge_configuration(accepted, application_id="biotech") is not None


@pytest.mark.parametrize("value", ["component-1", COMPONENT.upper(), "{" + COMPONENT + "}"])
def test_the_component_installation_id_is_a_canonical_uuid(tmp_path: Path, value: str) -> None:
    """Review N1: the KS component database pins `installation_id uuid`."""

    settings, _active, _retiring = configured(tmp_path, knowledge_component_installation_id=value)
    with pytest.raises(KnowledgeConfigurationError, match="KNOWLEDGE_COMPONENT_INSTALLATION_ID"):
        knowledge_configuration(settings, application_id="biotech")


async def test_the_uncomposed_guard_is_wired_only_without_a_trusted_settlement(
    tmp_path: Path,
) -> None:
    """W1 D30 review item 3b: without evaluator credentials the lane composes no trusted
    settlement and the uncomposed guard (the application's pin); with both credentials it
    composes the trusted settlement and no guard."""

    from pydantic import SecretStr

    from mission_control.application.knowledge.trusted_settlement import (
        TrustedSettlement,
        UncomposedTrustedSettlement,
    )

    def lane_for(**keys: Any) -> Any:
        settings, active, retiring = configured(tmp_path, **keys)
        clock = SteppingClock()
        fake = FakeKnowledgeBinding(
            verifier=CredentialVerifier(
                issuer="mission-control",
                audience="ks-executor",
                jwks=publish_jwks(active, retiring),
                clock=clock,
            ),
            clock=clock,
            binding="biotech-graph",
            application="biotech",
        )
        return compose_knowledge_lane(
            settings,
            cast(Any, object()),
            application_id="biotech",
            installation_id=INSTALLATION,
            client=fake,
            clock=clock,
        )

    bare = await lane_for()
    assert bare is not None and bare.toolset.trusted is None
    guard = bare.toolset.uncomposed_trusted
    assert isinstance(guard, UncomposedTrustedSettlement)
    assert guard._pin == "knowledge.report.assess@1"  # the biotech profile's assessment pin
    keyed = await lane_for(
        mc_judge_openai_api_key=SecretStr("judge-key"),
        mc_auditor_anthropic_api_key=SecretStr("auditor-key"),
        anthropic_api_key=SecretStr("producer-key"),
    )
    assert keyed is not None and isinstance(keyed.toolset.trusted, TrustedSettlement)
    assert keyed.toolset.uncomposed_trusted is None
