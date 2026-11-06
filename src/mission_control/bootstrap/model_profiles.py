"""Model Profiles from `deployments/<app>/models.toml` (ADR-0063, OC-R6 / OVE-200).

An installation's Model Catalog is one file beside its Application Profile. Each `[[models]]` row
is one :class:`ModelProfile` (vendor, exact model id, context window, list prices, supports, Data
Class ceiling); a row names no lane. Nothing is discovered: the caller names the application, and
a missing or invalid file fails closed. Stdlib and domain types only, like
`bootstrap/application_profiles.py`; the registry import is lazy for the same reason.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from mission_control.domain.resolution.profiles import ModelProfile

if TYPE_CHECKING:
    from mission_control.application.resolution.registries import ModelCatalog

MODELS_FILE: Final = "models.toml"
MODEL_CATALOG_SCHEMA: Final = "mc.model_catalog.v1"


class ModelCatalogError(ValueError):
    """An application has no readable, valid model catalog file (fail closed)."""


class ModelCatalogFile(BaseModel):
    """One parsed `models.toml`: its rows, each a Model Profile, profile names unique."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["mc.model_catalog.v1"] = MODEL_CATALOG_SCHEMA
    models: tuple[ModelProfile, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_profiles(self) -> ModelCatalogFile:
        names = [row.profile for row in self.models]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"model profiles named twice: {duplicates}")
        # W1 D24 (fail closed at load, before any launch): an OpenAI row with function tools
        # declares the Responses API; chat completions refuses tools with reasoning.
        unsupported = sorted(
            row.profile
            for row in self.models
            if row.requires_responses_api() and row.api_surface != "responses"
        )
        if unsupported:
            raise ValueError(
                f"API_SURFACE_UNSUPPORTED: OpenAI rows with tool use must declare "
                f'api_surface = "responses" (function tools with reasoning are refused on '
                f"/v1/chat/completions): {unsupported}"
            )
        return self


def models_path(root: Path, application_id: str) -> Path:
    return root / application_id / MODELS_FILE


def load_model_catalog_file(path: Path) -> ModelCatalogFile:
    try:
        document: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ModelCatalogError(f"no model catalog at {path.as_posix()}") from None
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ModelCatalogError(f"unreadable model catalog {path.as_posix()}: {error}") from None
    try:
        return ModelCatalogFile.model_validate(document)
    except ValidationError as error:
        raise ModelCatalogError(f"invalid model catalog {path.as_posix()}: {error}") from None


def compose_model_catalog(root: Path, application_id: str) -> ModelCatalog:
    """The Model Catalog of one installed application, from its own `models.toml`."""

    # Lazy: the registries import the harness protocol; this module stays import-light.
    from mission_control.application.resolution.registries import ModelCatalog

    return ModelCatalog(load_model_catalog_file(models_path(root, application_id)).models)


__all__ = [
    "MODELS_FILE",
    "MODEL_CATALOG_SCHEMA",
    "ModelCatalogError",
    "ModelCatalogFile",
    "compose_model_catalog",
    "load_model_catalog_file",
    "models_path",
]
