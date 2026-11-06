from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from scripts.temporal_cloud import configure_search_attributes as configure
from scripts.temporal_cloud.configure_search_attributes import NAMESPACE, plan, updated_spec
from temporalio.api.cloud.namespace.v1 import Namespace, NamespaceSpec
from temporalio.api.enums.v1 import IndexedValueType

from mission_control.adapters.temporal import cloud_namespace, search_attributes


def namespace() -> Namespace:
    return Namespace(
        namespace=NAMESPACE,
        active_region="aws-us-east-1",
        resource_version="reviewed-version",
        state=3,
        spec=NamespaceSpec(name="mission-control-dev", retention_days=7, regions=["aws-us-east-1"]),
    )


def test_cloud_fields_decode_without_dropping_unknown_or_conflicting_types() -> None:
    spec = NamespaceSpec(
        custom_search_attributes={"legacy": "KeywordList"}, search_attributes={"new": 3}
    )
    assert cloud_namespace.cloud_search_attributes(spec) == {"legacy": 7, "new": 3}
    spec.search_attributes["legacy"] = 2
    with pytest.raises(ValueError, match="disagree"):
        cloud_namespace.cloud_search_attributes(spec)
    spec.search_attributes.clear()
    spec.custom_search_attributes["legacy"] = "future-type"
    with pytest.raises(ValueError, match="unknown"):
        cloud_namespace.cloud_search_attributes(spec)


def test_plan_adds_exact_attributes_and_preserves_every_other_spec_field() -> None:
    current = namespace()
    current.spec.search_attributes["owner_attribute"] = 1
    current.spec.search_attributes["mc_lane"] = 2
    proposal = plan(current)
    assert len(proposal["additions"]) == 13 and "mc_lane" not in proposal["additions"]
    changed = updated_spec(current, proposal)
    for name in proposal["additions"]:
        del changed.search_attributes[name]
    assert changed.SerializeToString(deterministic=True) == current.spec.SerializeToString(
        deterministic=True
    )


@pytest.mark.parametrize(
    "mutation", ["namespace", "region", "version", "spec", "conflict", "state"]
)
def test_reviewed_plan_refuses_target_or_configuration_drift(mutation: str) -> None:
    current = namespace()
    reviewed = plan(current)
    if mutation == "namespace":
        current.namespace = "other.account"
    elif mutation == "region":
        current.active_region = "aws-eu-west-1"
    elif mutation == "version":
        current.resource_version = "changed"
    elif mutation == "spec":
        current.spec.retention_days = 14
    elif mutation == "conflict":
        current.spec.search_attributes["mc_lane"] = 3
    else:
        current.state = 4
    with pytest.raises(ValueError):
        updated_spec(current, reviewed)


async def test_cloud_readiness_uses_cloud_ops_and_never_server_operator(monkeypatch) -> None:
    async def read(key: str, namespace: str) -> dict[str, int]:
        assert key == "fixture-key" and namespace == NAMESPACE
        return {
            name: {"keyword": 2, "int": 3, "keyword_list": 7}[kind]
            for name, kind in search_attributes.BELLLABS_SEARCH_ATTRIBUTES.items()
        }

    monkeypatch.setattr(cloud_namespace, "registered_cloud_search_attributes", read)
    await search_attributes.verify_belllabs_search_attributes(
        SimpleNamespace(), NAMESPACE, cloud_api_key="fixture-key"
    )


async def test_local_readiness_preserves_operator_api(monkeypatch) -> None:
    async def read(client, namespace):
        return {"mc_lane": IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD}

    monkeypatch.setattr(search_attributes, "_registered", read)
    with pytest.raises(search_attributes.SearchAttributeRegistrationError):
        await search_attributes.verify_belllabs_search_attributes(SimpleNamespace(), "default")


async def test_plan_is_read_only_and_apply_preserves_request_shape(monkeypatch, tmp_path) -> None:
    current = namespace()
    calls = []

    async def get_namespace(request):
        assert request.namespace == NAMESPACE
        return SimpleNamespace(namespace=current)

    async def update_namespace(request):
        calls.append(request)
        return SimpleNamespace(async_operation=SimpleNamespace(id="fixture-operation"))

    async def connect(**kwargs):
        assert kwargs == {"api_key": "fixture-key", "version": cloud_namespace.CLOUD_API_VERSION}
        return SimpleNamespace(
            cloud_service=SimpleNamespace(
                get_namespace=get_namespace, update_namespace=update_namespace
            )
        )

    monkeypatch.setenv("TEMPORAL_CLOUD_API_KEY", "fixture-key")
    monkeypatch.setattr(configure.CloudOperationsClient, "connect", connect)
    path = tmp_path / "plan.json"
    proposal = await configure.run(path, apply=False)
    assert calls == [] and json.loads(path.read_text()) == proposal
    with pytest.raises(FileExistsError):
        await configure.run(path, apply=False)
    result = await configure.run(path, apply=True)
    assert result["state"] == "submitted_readback_required"
    assert len(calls) == 1
    assert calls[0].namespace == NAMESPACE
    assert calls[0].resource_version == current.resource_version
    assert calls[0].spec == updated_spec(current, proposal)
    current.resource_version = "changed"
    with pytest.raises(ValueError, match="changed"):
        await configure.run(path, apply=True)
    assert len(calls) == 1


@pytest.mark.parametrize("invalid", ["identity", "state"])
async def test_cloud_reader_refuses_wrong_identity_or_inactive_namespace(monkeypatch, invalid):
    current = namespace()
    if invalid == "identity":
        current.namespace = "other.account"
    else:
        current.state = 4

    async def get_namespace(request):
        return SimpleNamespace(namespace=current)

    async def connect(**kwargs):
        return SimpleNamespace(cloud_service=SimpleNamespace(get_namespace=get_namespace))

    monkeypatch.setattr(cloud_namespace.CloudOperationsClient, "connect", connect)
    with pytest.raises(ValueError, match="identity or active state"):
        await cloud_namespace.registered_cloud_search_attributes("fixture-key", NAMESPACE)
