"""The Mission Brief: the Interview's result is part of the `mission/v2` manifest.

The block is validated where the manifest is parsed (bounded sizes, no credential-shaped
text), sealed in the committed `MissionDefinition@1` (so it changes the manifest and the
definition digests and travels with the revision), read back in the compile report, and its
absence is a warning, never a blocker. No database, no network.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from mission_control.application.chains.service import ManifestStructureService
from mission_control.application.guide.mission_templates import load_template
from mission_control.domain.authoring.brief import (
    BRIEF_ANSWER_MAX,
    BRIEF_ANSWERS_MAX,
    BRIEF_DONE_MEANS_MAX,
    BRIEF_OUT_OF_SCOPE_MAX,
    BRIEF_REQUEST_MAX,
    PURPOSE_MEANINGS,
    MissionBrief,
    MissionPurpose,
    secret_like,
)
from mission_control.domain.authoring.canonical import stable_json_digest
from mission_control.domain.authoring.manifest import (
    ManifestRejected,
    canonical_manifest_bytes,
    load_manifest_yaml,
    manifest_json_schema,
)
from mission_control.domain.authoring.manifest_v2 import (
    BRIEF_MISSING,
    brief_warnings,
    manifest_v2_json_schema,
    parse_manifest_any,
)
from mission_control.domain.authoring.mission_definition import (
    MissionDefinition,
    manifest_to_definitions,
)
from tests.architecture.test_package_boundaries import APPLICATION_NEEDLES
from tests.support.manifests.compile import MINIMAL, scope, service
from tests.unit.guide.support import SANDBOXES

ROOT = Path(__file__).resolve().parents[3]
APPLICATION = "ai-engineer"
BRIEF: dict[str, Any] = {
    "purpose": "system",
    "request": "Show me that a first mission runs end to end here.",
    "answers": [
        {"question": "What should the text be about?", "answer": "What a Mission Manifest is."},
        {"question": "Who reviews it?", "answer": "I do, the same day."},
    ],
    "done_means": "I read three clear sentences and approve them.",
    "out_of_scope": ["No web research."],
}


def document(brief: dict[str, Any] | None = BRIEF) -> dict[str, Any]:
    """The `smallest` template with its examples, and this brief (or none)."""

    template = load_template("smallest")
    values = template.examples() | {
        "application_id": APPLICATION,
        "sandbox_profile": next(iter(SANDBOXES)),
    }
    loaded = load_manifest_yaml(template.fill(values))
    if brief is None:
        del loaded["mission"]["brief"]
    else:
        loaded["mission"]["brief"] = json.loads(json.dumps(brief))
    return loaded


def text(loaded: dict[str, Any]) -> str:
    return canonical_manifest_bytes(loaded).decode("utf-8")


def issues(loaded: dict[str, Any]) -> dict[str, str]:
    with pytest.raises(ManifestRejected) as rejected:
        parse_manifest_any(loaded)
    return {item.pointer: item.message for item in rejected.value.issues}


# -- the model -----------------------------------------------------------------------------------


def test_the_brief_parses_into_the_manifest_and_names_no_application() -> None:
    manifest = parse_manifest_any(document())
    brief = manifest.mission.brief  # type: ignore[union-attr]

    assert brief == MissionBrief.model_validate(BRIEF)
    assert brief.purpose is MissionPurpose.SYSTEM and brief.requested_by is None
    assert [item.question for item in brief.answers] == [
        "What should the text be about?",
        "Who reviews it?",
    ]
    assert brief_warnings(manifest) == ()
    # The purpose vocabulary is about the kind of work, never an application.
    assert [item.value for item in MissionPurpose] == ["research", "content", "system", "other"]
    assert set(PURPOSE_MEANINGS) == set(MissionPurpose)
    vocabulary = " ".join((*PURPOSE_MEANINGS.values(), *(item.value for item in MissionPurpose)))
    assert not [needle for needle in APPLICATION_NEEDLES if needle in vocabulary.lower()]


def test_only_purpose_and_request_are_required() -> None:
    smallest = MissionBrief.model_validate({"purpose": "other", "request": "Do the thing."})

    assert smallest.answers == () and smallest.out_of_scope == ()
    assert smallest.done_means is None and smallest.requested_by is None
    assert issues(document({"purpose": "system"})) == {"/mission/brief/request": "Field required"}
    assert "/mission/brief/purpose" in issues(document({"request": "Do the thing."}))
    assert "/mission/brief/purpose" in issues(document(BRIEF | {"purpose": "marketing"}))
    # An unknown key is refused, as everywhere in a manifest.
    assert "/mission/brief/priority" in issues(document(BRIEF | {"priority": "high"}))


@pytest.mark.parametrize(
    ("change", "pointer"),
    [
        ({"request": "x" * (BRIEF_REQUEST_MAX + 1)}, "/mission/brief/request"),
        ({"done_means": "x" * (BRIEF_DONE_MEANS_MAX + 1)}, "/mission/brief/done_means"),
        (
            {"answers": [{"question": "q", "answer": "a"}] * (BRIEF_ANSWERS_MAX + 1)},
            "/mission/brief/answers",
        ),
        (
            {"answers": [{"question": "q", "answer": "x" * (BRIEF_ANSWER_MAX + 1)}]},
            "/mission/brief/answers/0/answer",
        ),
        ({"out_of_scope": ["x"] * (BRIEF_OUT_OF_SCOPE_MAX + 1)}, "/mission/brief/out_of_scope"),
        ({"request": "   "}, "/mission/brief/request"),
        ({"requested_by": "two words"}, "/mission/brief/requested_by"),
    ],
)
def test_the_brief_is_bounded_at_its_pointer(change: dict[str, Any], pointer: str) -> None:
    assert pointer in issues(document(BRIEF | change))


def test_the_limits_admit_their_own_maximum() -> None:
    largest = BRIEF | {
        "request": "x" * BRIEF_REQUEST_MAX,
        "done_means": "y" * BRIEF_DONE_MEANS_MAX,
        "answers": [{"question": "q", "answer": "a" * BRIEF_ANSWER_MAX}] * BRIEF_ANSWERS_MAX,
        "out_of_scope": ["z"] * BRIEF_OUT_OF_SCOPE_MAX,
    }

    brief = parse_manifest_any(document(largest)).mission.brief  # type: ignore[union-attr]
    assert brief is not None and len(brief.answers) == BRIEF_ANSWERS_MAX


@pytest.mark.parametrize(
    ("field", "value", "shape"),
    [
        ("request", "Use the key sk-live1234567890abcdef to call the API.", "sk_key"),
        ("done_means", "It works with OPENAI_API_KEY=abc123def456.", "env_secret"),
        ("request", "Clone https://user:hunter2@example.invalid/repo.git", "url_userinfo"),
        ("request", "Send Authorization: Bearer abcdef0123456789abcdef", "bearer_token"),
    ],
)
def test_text_shaped_like_a_credential_is_refused_without_repeating_it(
    field: str, value: str, shape: str
) -> None:
    found = issues(document(BRIEF | {field: value}))

    message = found[f"/mission/brief/{field}"]
    assert "secret-like content" in message and shape in message
    # The refusal names the pattern class, never the value.
    assert not [
        word for word in ("sk-live", "abc123def456", "hunter2", "abcdef0123") if word in message
    ]


def test_an_answer_shaped_like_a_credential_is_refused_at_the_answer() -> None:
    answers = [{"question": "Which token?", "answer": "ghp_abcdefghijklmnopqrstuvwxyz0123"}]

    found = issues(document(BRIEF | {"answers": answers}))
    assert "github_token" in found["/mission/brief/answers/0/answer"]


def test_ordinary_words_about_authentication_are_not_secrets() -> None:
    prose = "Add basic authentication and bearer authentication to the token endpoint."

    assert secret_like(prose) == ()
    assert parse_manifest_any(document(BRIEF | {"request": prose})).mission is not None


def test_a_mission_v1_manifest_cannot_carry_a_brief() -> None:
    loaded = load_manifest_yaml(MINIMAL.read_text(encoding="utf-8"))
    assert loaded["manifest"] == "mission/v1"
    assert brief_warnings(parse_manifest_any(loaded)) == ()

    loaded["mission"]["brief"] = dict(BRIEF)
    assert "/mission/brief" in issues(loaded)


# -- the schemas ---------------------------------------------------------------------------------


def test_the_v2_schema_carries_the_brief_and_the_v1_schema_does_not() -> None:
    definitions = manifest_v2_json_schema()["$defs"]

    block = definitions["MissionBlockV2"]["properties"]["brief"]
    assert {"$ref": "#/$defs/MissionBrief"} in block["anyOf"] and block["default"] is None
    brief = definitions["MissionBrief"]
    assert brief["required"] == ["purpose", "request"] and brief["additionalProperties"] is False
    assert brief["properties"]["request"]["maxLength"] == BRIEF_REQUEST_MAX
    assert brief["properties"]["answers"]["maxItems"] == BRIEF_ANSWERS_MAX
    assert brief["properties"]["out_of_scope"]["maxItems"] == BRIEF_OUT_OF_SCOPE_MAX
    assert definitions["MissionPurpose"]["enum"] == [item.value for item in MissionPurpose]
    assert definitions["BriefAnswer"]["required"] == ["question", "answer"]
    assert "MissionBrief" not in manifest_json_schema()["$defs"]
    assert "brief" not in manifest_json_schema()["$defs"]["MissionBlock"]["properties"]


def test_the_committed_schemas_are_the_generated_ones() -> None:
    spec = importlib.util.spec_from_file_location(
        "manifest_schemas", ROOT / "scripts" / "manifest_schemas.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.drifted(module.SCHEMAS) == []


# -- the definition ------------------------------------------------------------------------------


def test_the_brief_is_sealed_in_the_definition_and_absent_when_not_authored() -> None:
    with_brief, without = document(), document(None)
    (sealed,) = manifest_to_definitions(parse_manifest_any(with_brief), with_brief)
    (bare,) = manifest_to_definitions(parse_manifest_any(without), without)

    assert sealed.brief == MissionBrief.model_validate(BRIEF)
    dumped = sealed.model_dump(mode="json")
    assert dumped["brief"]["request"] == BRIEF["request"]
    # As a revision stores it and a later read validates it again.
    assert MissionDefinition.model_validate(dumped).brief == sealed.brief
    # Additive: a definition without a brief keeps its dump and its digest bytes.
    assert bare.brief is None and "brief" not in bare.model_dump(mode="json")
    assert stable_json_digest(bare) == stable_json_digest(bare.model_copy(update={"brief": None}))
    # The brief is part of what a revision seals: it moves both digests.
    assert sealed.manifest_digest != bare.manifest_digest
    assert (
        sealed.digest != bare.model_copy(update={"manifest_digest": sealed.manifest_digest}).digest
    )


# -- compile -------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_manifest_with_a_brief_compiles_and_reads_it_back() -> None:
    compile_service, _, _ = await service()

    compilation = await compile_service.compile(text(document()), scope(APPLICATION))

    report = compilation.report
    assert compilation.ok and report.startable is True
    assert BRIEF_MISSING not in {item.reason for item in report.warnings}
    # Who asked defaults to the principal the compile runs for (the submitter at submit).
    expected = MissionBrief.model_validate(BRIEF | {"requested_by": "owner"})
    assert compilation.definitions[0].brief == expected
    assert report.definitions[0].brief == expected
    assert report.model_dump(mode="json")["definitions"][0]["brief"]["purpose"] == "system"
    # The Compiled Program is lowered from the definition that carries the default.
    assert report.definitions[0].definition_digest == compilation.definitions[0].digest
    assert report.resolution is not None
    assert report.resolution.lowering[0].definition_digest == compilation.definitions[0].digest


@pytest.mark.asyncio
async def test_an_authored_requester_is_kept() -> None:
    compile_service, _, _ = await service()
    authored = document(BRIEF | {"requested_by": "user:john"})

    compilation = await compile_service.compile(text(authored), scope(APPLICATION))

    assert compilation.ok
    assert compilation.definitions[0].brief.requested_by == "user:john"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_a_manifest_without_a_brief_compiles_with_a_warning() -> None:
    compile_service, _, _ = await service()

    compilation = await compile_service.compile(text(document(None)), scope(APPLICATION))

    report = compilation.report
    assert compilation.ok and report.blockers == () and report.startable is True
    (warning,) = [item for item in report.warnings if item.reason == BRIEF_MISSING]
    assert warning.pointer == "/mission/brief" and "records no brief" in warning.message
    assert compilation.definitions[0].brief is None
    assert "brief" not in report.model_dump(mode="json")["definitions"][0]


def test_the_structural_compile_warns_and_reads_the_brief_back_too() -> None:
    structure = ManifestStructureService()

    with_brief = structure.compile(text(document()))
    without = structure.compile(text(document(None)))

    assert with_brief.definitions[0].brief == MissionBrief.model_validate(BRIEF)
    assert BRIEF_MISSING not in {item.reason for item in with_brief.warnings}
    assert BRIEF_MISSING in {item.reason for item in without.warnings}
    assert without.definitions[0].brief is None


@pytest.mark.asyncio
async def test_a_mission_v1_manifest_compiles_without_the_warning() -> None:
    compile_service, _, _ = await service()

    compilation = await compile_service.compile(MINIMAL.read_text(encoding="utf-8"), scope())

    assert BRIEF_MISSING not in {item.reason for item in compilation.report.warnings}
