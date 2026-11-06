"""Artifact schemas use ordinary publication and reject unsupported validation authority."""

from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import TypeAdapter, ValidationError

from mission_control.application.authoring.service import ControlPlaneService
from mission_control.domain.authoring.canonical import stable_json_dump
from mission_control.domain.authoring.contracts import ArtifactSchemaDefinition, Definition
from mission_control.domain.authoring.errors import CompilationRejected
from tests.unit.capability.test_artifact_schema_seeds import production_record


def test_definition_union_roundtrip_and_non_executable_kind():
    definition = production_record().definition
    raw = stable_json_dump(definition)
    restored = TypeAdapter(Definition).validate_python(raw)
    assert restored == definition
    assert stable_json_dump(restored) == raw
    with pytest.raises(ValidationError):
        ArtifactSchemaDefinition.model_validate(
            {**definition.model_dump(), "schema_dialect": "other"}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "https://example.com/untrusted"},
        {"type": "string", "pattern": ".*"},
        {"$schema": "https://json-schema.org/draft-07/schema"},
    ],
)
async def test_publication_refuses_unsupported_schema_before_repository_write(schema):
    repository = AsyncMock()
    service = ControlPlaneService(repository, Mock(), Mock())
    definition = production_record().definition.model_copy(update={"json_schema": schema})
    with pytest.raises(CompilationRejected):
        await service._validate_publication(definition)
    repository.publish.assert_not_called()


@pytest.mark.asyncio
async def test_published_schema_uses_existing_publication_boundary():
    service = ControlPlaneService(AsyncMock(), Mock(), Mock())
    await service._validate_publication(production_record().definition)


def test_existing_provider_binding_canonical_digest_and_seal_roundtrip_unchanged():
    from mission_control.domain.authoring.canonical import sha256_digest
    from mission_control.domain.execution.bindings import ProviderExecutionBinding
    from tests.unit.codex.support import codex_binding

    binding = codex_binding()
    encoded = stable_json_dump(binding)
    restored = ProviderExecutionBinding.model_validate(encoded)
    assert stable_json_dump(restored) == encoded
    assert restored.binding_digest == binding.binding_digest
    assert sha256_digest(restored) == sha256_digest(binding)
    with pytest.raises(ValidationError):
        ProviderExecutionBinding.model_validate(
            {**binding.model_dump(), "artifact_schema": "unadmitted-authority"}
        )
