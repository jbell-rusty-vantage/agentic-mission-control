"""The authoritative Biotech SDL is located by configuration or the BellLabs layout, never
copied into Mission Control, and admitted only when it equals the published reference."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.fixtures.sibling_checkouts import authoritative_schema_path

from biotech_mission_adapters.bootstrap.schema_source import (
    SCHEMA_SOURCE_ENV,
    WORKSPACE_SCHEMA,
    AuthoritativeSchemaMismatch,
    AuthoritativeSchemaUnavailable,
    locate_authoritative_schema,
    published_source_reference,
    read_authoritative_schema,
)


def test_default_follows_the_belllabs_layout(tmp_path: Path) -> None:
    project_root = tmp_path / "platform" / "mission-control"
    project_root.mkdir(parents=True)
    expected = tmp_path.joinpath(*WORKSPACE_SCHEMA.parts)
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"type A { id: ID! }")

    assert locate_authoritative_schema(project_root=project_root, environ={}) == expected


def test_explicit_configuration_wins_and_never_falls_back(tmp_path: Path) -> None:
    project_root = tmp_path / "platform" / "mission-control"
    layout = tmp_path.joinpath(*WORKSPACE_SCHEMA.parts)
    layout.parent.mkdir(parents=True)
    layout.write_bytes(b"type A { id: ID! }")
    configured = tmp_path / "configured.graphql"
    configured.write_bytes(b"type B { id: ID! }")

    environ = {SCHEMA_SOURCE_ENV: str(configured)}
    assert locate_authoritative_schema(project_root=project_root, environ=environ) == configured
    missing = {SCHEMA_SOURCE_ENV: str(tmp_path / "absent.graphql")}
    with pytest.raises(AuthoritativeSchemaUnavailable, match=SCHEMA_SOURCE_ENV):
        locate_authoritative_schema(project_root=project_root, environ=missing)


def test_absent_layout_names_the_configuration(tmp_path: Path) -> None:
    with pytest.raises(AuthoritativeSchemaUnavailable, match=SCHEMA_SOURCE_ENV):
        locate_authoritative_schema(project_root=tmp_path / "platform" / "mc", environ={})


def test_bytes_other_than_the_published_reference_fail_closed(tmp_path: Path) -> None:
    edited = tmp_path / "current_biotech_schema.graphql"
    edited.write_bytes(b"type Edited { id: ID! }")
    reference = published_source_reference()

    with pytest.raises(AuthoritativeSchemaMismatch, match=str(reference["sha256"])):
        read_authoritative_schema(edited)


def test_the_published_reference_pins_the_source_sdl_release() -> None:
    reference = published_source_reference()
    assert reference["content_length"] == 389072
    assert reference["reference_version"] == "2"
    assert reference["source_kind"] == "neo4j-graphql-source-sdl"
    assert reference["git_blob"] == "ec16fda58ea0e1525c354aee6d4640d4c88a2bc9"


def test_current_source_is_exact_pinned_sdl_not_derived_api() -> None:
    path = authoritative_schema_path()
    payload = read_authoritative_schema(path)
    assert len(payload) == 389072
    # The derived consumer API beside it in a Biotech Knowledge Services checkout is other
    # bytes; an SDL configured outside a checkout has no such neighbour to compare.
    api = path.parents[4] / "apps/graphql-api/generated/schema.graphql"
    if api.is_file():
        with pytest.raises(AuthoritativeSchemaMismatch):
            read_authoritative_schema(api)


def test_overlay_drift_refuses_current_source(tmp_path, monkeypatch):
    from biotech_mission_adapters.bootstrap import schema_source

    changed = tmp_path / "semantic-overlay.v2.json"
    changed.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(schema_source, "DEFAULT_SEMANTIC_OVERLAY", changed)
    # The overlay is checked before the SDL digest, so any readable file reaches the refusal.
    source = tmp_path / "assembled.graphql"
    source.write_bytes(b"type A { id: ID! }")
    with pytest.raises(AuthoritativeSchemaMismatch, match="overlay"):
        read_authoritative_schema(source)
