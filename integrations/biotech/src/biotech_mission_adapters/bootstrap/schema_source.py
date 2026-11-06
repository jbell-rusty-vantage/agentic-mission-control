"""Locate and verify the authoritative Biotech graph schema (SDL) without copying it.

Biotech owns its graph/domain contract; Mission Control only reads it. The authoritative
bytes are identified by `resources/schema-catalog/source-reference.v2.json`: the exact
BKS pinned release source SDL, separately identified from the derived consumer API.
The v1 S3 reference and semantic overlay remain immutable historical evidence.

Resolution (`locate_authoritative_schema`):

1. `BIOTECH_SCHEMA_SDL_PATH`, when set: that file and nothing else (explicit configuration
   never falls back).
2. Otherwise the BellLabs layout: `<BellLabs>/biotech/biotech-knowledge-services/
   schema/pinned/release/sdl/assembled.graphql`, where `<BellLabs>` is the parent of `platform`
   directory holding this checkout (`PROJECT_ROOT.parent.parent`).

`read_authoritative_schema` returns the bytes only when they equal the published reference,
so a stale or edited local copy fails closed instead of grounding against another schema.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path, PurePosixPath

from biotech_mission_adapters.application.schema.schema_catalog import DEFAULT_SEMANTIC_OVERLAY
from mission_control.bootstrap.settings import PROJECT_ROOT

SCHEMA_SOURCE_ENV = "BIOTECH_SCHEMA_SDL_PATH"
SOURCE_REFERENCE = DEFAULT_SEMANTIC_OVERLAY.parent / "source-reference.v2.json"
WORKSPACE_SCHEMA = PurePosixPath(
    "biotech/biotech-knowledge-services/schema/pinned/release/sdl/assembled.graphql"
)


class AuthoritativeSchemaUnavailable(FileNotFoundError):
    """The authoritative Biotech SDL is not present where configuration says it is."""


class AuthoritativeSchemaMismatch(ValueError):
    """The located SDL differs from the published source reference."""


def locate_authoritative_schema(
    *,
    project_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """The configured or BellLabs-layout path of the authoritative SDL; never a copy."""

    environment = os.environ if environ is None else environ
    configured = environment.get(SCHEMA_SOURCE_ENV, "").strip()
    if configured:
        candidate = Path(configured)
        origin = f"{SCHEMA_SOURCE_ENV}={configured}"
    else:
        root = PROJECT_ROOT if project_root is None else project_root
        candidate = root.parent.parent.joinpath(*WORKSPACE_SCHEMA.parts)
        origin = f"the BellLabs workspace layout ({WORKSPACE_SCHEMA})"
    if not candidate.is_file():
        raise AuthoritativeSchemaUnavailable(
            f"authoritative Biotech schema is absent at {candidate} (from {origin}); set "
            f"{SCHEMA_SOURCE_ENV} to the Biotech-owned SDL whose digest matches "
            f"{SOURCE_REFERENCE.name}"
        )
    return candidate


def published_source_reference() -> dict[str, object]:
    return dict(json.loads(SOURCE_REFERENCE.read_text(encoding="utf-8")))


def read_authoritative_schema(path: Path | None = None) -> bytes:
    """The SDL bytes, verified against the published SHA-256 and length."""

    source_path = locate_authoritative_schema() if path is None else path
    payload = source_path.read_bytes()
    reference = published_source_reference()
    overlay = reference["semantic_overlay"]
    if (
        not isinstance(overlay, dict)
        or overlay.get("path") != DEFAULT_SEMANTIC_OVERLAY.name
        or sha256(DEFAULT_SEMANTIC_OVERLAY.read_bytes()).hexdigest() != overlay.get("sha256")
    ):
        raise AuthoritativeSchemaMismatch("current semantic overlay differs from source reference")
    if (sha256(payload).hexdigest(), len(payload)) != (
        reference["sha256"],
        reference["content_length"],
    ):
        raise AuthoritativeSchemaMismatch(
            f"{source_path} differs from the published Biotech schema "
            f"sha256:{reference['sha256']} ({reference['content_length']} bytes)"
        )
    return payload
