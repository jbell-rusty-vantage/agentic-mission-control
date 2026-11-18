"""Builders, constants and fakes that other test files import.

Moved from tests/unit/authoring/test_output_promises_compile.py.
"""

from __future__ import annotations

from tests.support.manifests.compile import minimal, scope, service, text


def promised_manifest() -> dict:  # type: ignore[type-arg]
    document = minimal()
    synthesize = document["mission"]["program"]["nodes"][1]
    synthesize["outputs"] = [
        {
            "name": "claims",
            "schema": "claim_table@1",
            "coverage": {"subjects": ["nct-1", "nct-2"], "pointer": "/claims", "key": "study"},
        },
        {
            "name": "summary",
            "form": "text",
            "enforcement": "expected",
            "media_type": "text/markdown",
        },
        {
            "name": "patch",
            "form": "code_change",
            "enforcement": "optional",
            "repository": "github.com/overtonbell/mission-control",
            "requirements": [{"key": "tests", "validator": "mc.check.command@1"}],
        },
    ]
    return document


async def compiled_configuration():  # type: ignore[no-untyped-def]
    compiler, _, _ = await service()
    result = await compiler.compile(text(promised_manifest()), scope())
    assert result.ok, result.report.blockers
    configuration = result.programs[0].configuration
    assert configuration.output_promises is not None
    return configuration
