"""Authoring: manifests, definitions and their compilation.

The package root re-exports lazily, so importing a leaf module such as ``manifest`` does not
load the compiler (whose contracts import ``domain.programs`` modules that themselves build on
``manifest``).
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mission_control.domain.authoring.compiler import compile_effective_run_configuration
    from mission_control.domain.authoring.contracts import (
        EffectiveRunConfiguration,
        ExactDefinitionRef,
    )

_EXPORTS = {
    "EffectiveRunConfiguration": "mission_control.domain.authoring.contracts",
    "ExactDefinitionRef": "mission_control.domain.authoring.contracts",
    "compile_effective_run_configuration": "mission_control.domain.authoring.compiler",
}


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(module), name)


__all__ = [
    "EffectiveRunConfiguration",
    "ExactDefinitionRef",
    "compile_effective_run_configuration",
]
