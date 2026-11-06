"""Read Cloud namespace configuration through Cloud Ops, never the server operator API."""

from __future__ import annotations

from temporalio.api.cloud.cloudservice.v1 import GetNamespaceRequest
from temporalio.api.cloud.namespace.v1 import NamespaceSpec
from temporalio.api.cloud.resource.v1 import ResourceState
from temporalio.api.enums.v1 import IndexedValueType
from temporalio.client import CloudOperationsClient

CLOUD_API_VERSION = "v0.23.0"
_KINDS = {
    "TEXT": IndexedValueType.INDEXED_VALUE_TYPE_TEXT,
    "KEYWORD": IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD,
    "INT": IndexedValueType.INDEXED_VALUE_TYPE_INT,
    "DOUBLE": IndexedValueType.INDEXED_VALUE_TYPE_DOUBLE,
    "BOOL": IndexedValueType.INDEXED_VALUE_TYPE_BOOL,
    "DATETIME": IndexedValueType.INDEXED_VALUE_TYPE_DATETIME,
    "KEYWORD_LIST": IndexedValueType.INDEXED_VALUE_TYPE_KEYWORD_LIST,
}


def cloud_search_attributes(spec: NamespaceSpec) -> dict[str, int]:
    """Decode current and deprecated fields without treating unknown types as absent."""
    result: dict[str, int] = {}
    for name, kind in spec.custom_search_attributes.items():
        normalized = kind.upper().replace("KEYWORDLIST", "KEYWORD_LIST")
        if normalized not in _KINDS:
            raise ValueError("Cloud namespace contains an unknown search attribute type")
        result[name] = _KINDS[normalized]
    for name, enum_kind in spec.search_attributes.items():
        label = NamespaceSpec.SearchAttributeType.Name(enum_kind).removeprefix(
            "SEARCH_ATTRIBUTE_TYPE_"
        )
        if label not in _KINDS:
            raise ValueError("Cloud namespace contains an unknown search attribute type")
        value = _KINDS[label]
        if name in result and result[name] != value:
            raise ValueError("Cloud namespace search attribute fields disagree")
        result[name] = value
    return result


async def registered_cloud_search_attributes(api_key: str, namespace: str) -> dict[str, int]:
    client = await CloudOperationsClient.connect(api_key=api_key, version=CLOUD_API_VERSION)
    response = await client.cloud_service.get_namespace(GetNamespaceRequest(namespace=namespace))
    if (
        response.namespace.namespace != namespace
        or response.namespace.state != ResourceState.RESOURCE_STATE_ACTIVE
    ):
        raise ValueError("Cloud namespace identity or active state differs")
    return cloud_search_attributes(response.namespace.spec)
