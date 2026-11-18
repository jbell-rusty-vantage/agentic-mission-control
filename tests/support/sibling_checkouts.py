"""Repositories beside this one that a few fixtures read and Mission Control never copies.

A CI checkout holds only this repository, and a developer's sibling moves on its own schedule,
so a test that reads one runs only when its variable names the checkout. Without the variable
the test skips and says which one to set; a variable that names a missing directory fails,
because explicit configuration never falls back.

The pinned Biotech SDL has its own variable, ``BIOTECH_SCHEMA_SDL_PATH`` (see
``biotech_mission_adapters.bootstrap.schema_source``): :func:`authoritative_schema_path`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from biotech_mission_adapters.bootstrap.schema_source import (
    SCHEMA_SOURCE_ENV,
    SOURCE_REFERENCE,
    locate_authoritative_schema,
)

# `biotech/biotech-knowledge-services`: the Qualia native-input schema, vocabulary and guide.
BKS_CHECKOUT_ENV = "MC_BKS_CHECKOUT"
# `aiengineer/ai-engineer-db-contract`: its generated `workspace/` task and relation pages.
AIDB_CHECKOUT_ENV = "MC_AIDB_CHECKOUT"


def sibling_checkout(variable: str, repository: str) -> Path:
    """The checkout ``variable`` names, or skip the calling test with that name."""

    configured = os.environ.get(variable, "").strip()
    if not configured:
        pytest.skip(f"{variable} is not set: it names the {repository} checkout this test reads")
    checkout = Path(configured)
    if not checkout.is_dir():
        pytest.fail(f"{variable}={configured} is not a directory", pytrace=False)
    return checkout.resolve()


def authoritative_schema_path() -> Path:
    """The Biotech-owned SDL ``BIOTECH_SCHEMA_SDL_PATH`` names, or skip the calling test.

    The reference Mission Control publishes pins one exact release of that file, so the test
    names the file explicitly instead of reading whatever a neighbouring checkout holds today.
    """

    if not os.environ.get(SCHEMA_SOURCE_ENV, "").strip():
        pytest.skip(
            f"{SCHEMA_SOURCE_ENV} is not set: it names the Biotech-owned SDL whose bytes "
            f"{SOURCE_REFERENCE.name} pins"
        )
    return locate_authoritative_schema()
