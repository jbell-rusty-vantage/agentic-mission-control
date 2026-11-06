"""Application-sensitive Biotech report-only preparation; no live-service qualification."""

from copy import deepcopy
from typing import Any

import pytest

from mission_control.contracts.knowledge_protocol import RevisionSelection, SelectedReportRead
from mission_control.domain.authoring.manifest import (
    load_manifest_yaml,
    parse_manifest,
    resolve_environments,
)
from mission_control.domain.composition.chain import compile_chain
from tests.fixtures.knowledge_binding import report_package
from tests.fixtures.overnight_linked_biotech import (
    BINDING,
    biotech_linked_manifest,
    biotech_model_profile,
    biotech_summary_from_read,
    validate_biotech_ready,
)


def ready_payload() -> dict[str, Any]:
    scoped = {"tenant": "tenant", "binding": BINDING}
    return {
        "binding": BINDING,
        "reports": [
            {
                "task": {
                    **scoped,
                    "domain": "scientific",
                    "use": "label_reference.ingredients",
                    "rubric": {"id": "rubric-scientific"},
                },
                "assertions": [
                    {**scoped, "qualifiers": {"profile": "scientific.v2", "entity": "product-a"}}
                ],
                "fragments": [scoped.copy()],
                "supportSets": [scoped.copy()],
                "report": {"kind": "evidence_report", "reportId": "fixture"},
            }
        ],
    }


def observed_read() -> tuple[dict[str, Any], str, str]:
    package = report_package(
        "label",
        "1",
        tenant="tenant",
        binding=BINDING,
        body=b"# Label\n\nProduct A label lists cellulose.\n",
    )
    package.assertions = tuple(
        {**row, "qualifiers": {"profile": "scientific.v2", "entity": "product-a"}}
        for row in package.assertions
    )
    selection = SelectedReportRead(
        report=package.report, exact=True, purpose="dependent_input", selection=RevisionSelection()
    )
    return (
        {
            "ok": True,
            "result": {
                "content": {
                    "manifest": package.answer(selection),
                    "body": package.body.decode(),
                    "ledger": package.ledger.decode(),
                }
            },
        },
        f"kh:{BINDING}/report/label@research-report.v2",
        package.report.digest,
    )


def test_actual_biotech_profile_and_scientific_manifest_are_selected() -> None:
    from tests.acceptance.mission_control.test_overnight_linked import linked_manifest

    ready = ready_payload()
    original = deepcopy(ready)
    text = biotech_linked_manifest(
        linked_manifest({"reportId": "fixture", "fragments": []}), ready, tenant="tenant"
    )
    document = load_manifest_yaml(text)
    manifest = parse_manifest(document)
    assert resolve_environments(manifest, document).blockers == ()
    assert compile_chain(manifest).ok
    assert all(
        m["application"] == "biotech" and m["environment"]["model"]["profile"] == "producer.default"
        for m in document["missions"]
    )
    assert ready == original
    row = biotech_model_profile()
    assert row.profile == "producer.default"
    assert row.pin().vendor == row.vendor and row.pin().model_id == row.model_id
    assert "no graph apply" in document["missions"][1]["program"]["nodes"][0]["instruction"]


@pytest.mark.parametrize("tamper", ["binding", "tenant", "qualifiers", "task"])
def test_engineering_or_wrong_scope_ready_payload_is_refused(tamper: str) -> None:
    ready = ready_payload()
    if tamper == "binding":
        ready["binding"] = "aiengineer-postgres"
    elif tamper == "tenant":
        ready["reports"][0]["fragments"][0]["tenant"] = "other"
    elif tamper == "qualifiers":
        ready["reports"][0]["assertions"][0]["qualifiers"]["profile"] = "engineering.v1"
    else:
        ready["reports"][0]["task"]["use"] = "engineering_reference.model_facts"
    with pytest.raises(ValueError):
        validate_biotech_ready(ready, tenant="tenant")


def test_summary_uses_actual_exact_body_and_scientific_member_records() -> None:
    read, handle, digest = observed_read()
    summary = biotech_summary_from_read(
        read, report_handle=handle, report_digest=digest, tenant="tenant"
    )
    assert "Product A label lists cellulose." in summary
    assert handle in summary and digest in summary
    assert "caffeine" not in summary


@pytest.mark.parametrize("tamper", ["digest", "body", "tenant", "qualifiers"])
def test_changed_identity_bytes_or_qualifier_record_cannot_be_summarized(tamper: str) -> None:
    read, handle, digest = observed_read()
    tenant = "tenant"
    if tamper == "digest":
        digest = "sha256:" + "b" * 64
    elif tamper == "body":
        read["result"]["content"]["body"] += "invented\n"
    elif tamper == "tenant":
        tenant = "other"
    else:
        read["result"]["content"]["manifest"]["assertions"][0]["record"]["qualifiers"][
            "profile"
        ] = "engineering.v1"
    with pytest.raises(ValueError):
        biotech_summary_from_read(read, report_handle=handle, report_digest=digest, tenant=tenant)


def test_served_binding_uses_actual_biotech_catalog_vendor_and_model() -> None:
    from mission_control.domain.execution.contracts import DeepAgentExecutionBinding
    from tests.fixtures.models import model_binding
    from tests.fixtures.overnight_linked_biotech import biotech_technical_binding
    from tests.fixtures.rrm009_production_stack import technical_binding

    original = technical_binding()
    row = biotech_model_profile()
    served = biotech_technical_binding(original, row)
    assert served.binding.model.provider == row.vendor
    assert served.binding.model.model_name == row.model_id
    assert served.binding.binding_digest != original.binding.binding_digest
    assert served.binding.model.ref != original.binding.model.ref
    assert model_binding(served.binding.model).ref == served.binding.model.ref
    assert (
        DeepAgentExecutionBinding.model_validate(served.binding.model_dump(mode="python"))
        == served.binding
    )


def test_biotech_consumer_uses_scientific_exact_read_and_submits_actual_summary() -> None:
    import json
    from types import SimpleNamespace

    from langchain_core.messages import ToolMessage

    from tests.fixtures.overnight_goal_model import GoalScript
    from tests.fixtures.overnight_linked_biotech import (
        biotech_components,
        biotech_technical_binding,
    )
    from tests.fixtures.overnight_linked_model import LinkedScript
    from tests.fixtures.rrm009_production_stack import technical_binding

    read, handle, digest = observed_read()
    first: dict[str, Any] = {
        "report": {"reportId": "fixture", "revision": 1},
        "assertions": [],
        "supportSets": [],
    }
    second = {**first, "report": {"reportId": "fixture", "revision": 2}}
    script = LinkedScript(
        source=GoalScript(candidates=(first, second), feedback="Unused in consumer-only test")
    )
    script.source_run, script.consumer_run = "source", "consumer"
    script.source.registered[1] = {"handle": handle, "digest": digest}
    technical = biotech_technical_binding(technical_binding(), biotech_model_profile())
    components = biotech_components(technical, script, [], "tenant")
    model = components.model_factories[technical.binding.model.ref.digest](
        SimpleNamespace(run_id="consumer", operation_id="run:stage:consume:1"), None
    )
    index = {
        "inputs": [
            {
                "access_ref": handle + "#digest=" + digest,
                "admission": "accepted",
                "purpose": "dependent_input",
            }
        ]
    }
    messages = [
        ToolMessage(content=json.dumps(index), tool_call_id="index"),
        ToolMessage(content=json.dumps(read), tool_call_id="read"),
    ]
    result = model._consumer(messages)
    call = result.generations[0].message.tool_calls[0]
    assert call["name"] == "submit_output"
    assert "Product A label lists cellulose." in call["args"]["items"][0]["text"]
    assert call["args"]["items"][0]["text"] == script.summaries[0]


def test_actual_served_catalog_preflight_and_wrong_vendor_refusal(
    tmp_path: Any, monkeypatch: Any
) -> None:
    from mission_control.adapters.capabilities.capability_pins import CapabilityPins
    from mission_control.adapters.deep_agents.compile import (
        ModelPinMismatch,
        catalog_model_components,
    )
    from mission_control.application.resolution.registries import ModelCatalog
    from mission_control.bootstrap.manifests import served_components
    from mission_control.bootstrap.settings import get_settings
    from tests.fixtures.models import model_binding
    from tests.fixtures.overnight_linked_biotech import (
        biotech_host_pins,
        biotech_served_model,
        biotech_technical_binding,
    )
    from tests.fixtures.rrm009_production_stack import technical_binding
    from tests.integration.temporal.test_manifest_launch_production import host_pins

    monkeypatch.setenv("MISSION_CONTROL_APPLICATION", "biotech")
    get_settings.cache_clear()
    profile = biotech_model_profile()
    technical = biotech_technical_binding(technical_binding(), profile)
    path = biotech_host_pins(host_pins(tmp_path / "pins.json"), profile)
    pins = CapabilityPins.load(path)
    declared = biotech_served_model(profile)
    assert declared in pins.models
    served = served_components(pins, get_settings(), technical.components([]))
    binding = model_binding(technical.binding.model)
    result = catalog_model_components({profile.profile: binding}, ModelCatalog((profile,)), served)
    assert result[profile.profile].ref == declared.ref.as_ref()
    assert result[profile.profile].provider == profile.vendor
    assert result[profile.profile].model_name == profile.model_id
    bad = pins.model_copy(
        update={
            "models": tuple(
                item.model_copy(update={"provider": "openai"}) if item.ref == declared.ref else item
                for item in pins.models
            )
        }
    )
    with pytest.raises(ModelPinMismatch, match="MODEL_PIN_VENDOR_MISMATCH"):
        catalog_model_components(
            {profile.profile: binding},
            ModelCatalog((profile,)),
            served_components(bad, get_settings(), technical.components([])),
        )


@pytest.mark.asyncio
async def test_native_decision_capture_preserves_exact_call_and_result(
    tmp_path: Any, monkeypatch: Any
) -> None:
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from tests.fixtures.overnight_linked_biotech import BiotechDecisionCapture

    answer = {"current": {"id": "actual-decision"}, "eligibility": "held", "reason": "actual-cause"}
    original = AsyncMock(return_value=answer)
    bridge = SimpleNamespace(_call=original)
    capture = BiotechDecisionCapture(tmp_path / "native.json")
    capture.install(SimpleNamespace(trusted=SimpleNamespace(_bridge=bridge)), monkeypatch)
    access = SimpleNamespace(scope="scope", origin=SimpleNamespace(run_id="run", operation_id="op"))
    request = SimpleNamespace(model_dump=lambda **kwargs: {"decision": "actual-decision"})
    result = await bridge._call(
        "decision.resolve", request, access, key="original-key", evaluation=None
    )
    assert result is answer
    original.assert_awaited_once_with(
        "decision.resolve", request, access, key="original-key", evaluation=None
    )
    record = json.loads((tmp_path / "native.json").read_text())[0]
    assert record["request_key"] == "original-key" and record["response"] == answer
    assert "access" not in record
