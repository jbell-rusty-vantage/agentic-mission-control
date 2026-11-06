"""W0 application profile conformance against a LIVE Knowledge Services describe (design §10).

`scripts/sprint_oc_describe_conformance.py` checks every `deployments/*/application.toml` against
captures written by KS `apps/verification-executor/scripts/capture-live-describe.mjs`. The fixtures
here are real captures of that composition (KS 740df8c executor build, component 2.5.0 installed on
the local `sprint-v-pg17` disposable server, 2026-10-28); the remote captures are the integrator's.
The AI Engineer capture was re-taken on 2026-11-01 from the KS 6a4dd30 executor build against the
disposable local Supabase database (127.0.0.1:54822, component 2.5.0): it adds
`knowledge.plan_preview`, `knowledge.read_intent` and the `read_intent` conditional capability
(OVE-204 slice 4).
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "knowledge_protocol"
CAPTURES = (
    FIXTURES / "live-describe-capture.ai-engineer.local-pg17.json",
    FIXTURES / "live-describe-capture.biotech.local-pg17.json",
)
DESCRIPTORS = Path(__file__).with_name("ks_backend_descriptors.json")


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sprint_oc_describe_conformance", ROOT / "scripts" / "sprint_oc_describe_conformance.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module
    spec.loader.exec_module(module)
    return module


CHECKER = _module()


def _captures() -> list[dict[str, Any]]:
    return [CHECKER.load_capture(path) for path in CAPTURES]


def _failed(captures: list[dict[str, Any]], **kwargs: Any) -> set[tuple[str, str]]:
    return {(c.application, c.name) for c in CHECKER.run_checks(captures, **kwargs) if not c.passed}


def test_both_live_captures_conform() -> None:
    checks = CHECKER.run_checks(_captures(), require_all=True)

    assert {c.application for c in checks} == {"ai-engineer", "biotech"}
    assert all(c.passed for c in checks), [c for c in checks if not c.passed]
    names = {c.name for c in checks}
    assert {"binding_advertised", "apply_contract_equals_native_contract"} <= names
    assert {"minimums_not_below_annex", "apply_served", "component_supported"} <= names


def test_a_missing_application_fails_only_when_all_are_required() -> None:
    only_ai = [CHECKER.load_capture(CAPTURES[0])]

    assert _failed(only_ai) == set()
    assert _failed(only_ai, require_all=True) == {("biotech", "captured")}


def test_the_live_registrations_equal_the_offline_descriptors() -> None:
    current = json.loads(DESCRIPTORS.read_text(encoding="utf-8"))
    refreshed = CHECKER.refreshed_descriptors(current, _captures())

    def by_id(document: dict[str, Any]) -> dict[str, Any]:
        return {backend["id"]: backend for backend in document["backends"]}

    assert by_id(refreshed) == by_id(current)
    assert refreshed["source"]["kind"] == "live-capture"


def _mutated(index: int, change: Any) -> list[dict[str, Any]]:
    captures = copy.deepcopy(_captures())
    change(captures[index]["bindings"][0])
    return captures


@pytest.mark.parametrize(
    ("index", "change", "expected"),
    [
        (0, lambda b: b.update(binding="other-binding"), ("ai-engineer", "binding_advertised")),
        (
            1,
            lambda b: b.update(served=False, unsupportedReason="no component database"),
            ("biotech", "binding_advertised"),
        ),
        (
            0,
            lambda b: b["registration"].update(
                nativeContract={"name": "knowledge-ingestion-intent", "version": "v2"}
            ),
            ("ai-engineer", "apply_contract_equals_native_contract"),
        ),
        (
            0,
            lambda b: b["describe"]["operations"].remove("knowledge.apply"),
            ("ai-engineer", "apply_served"),
        ),
        (
            1,
            lambda b: b["describe"]["pinnedSchema"].update(name="knowledge-verification-2.4.0"),
            ("biotech", "component_supported"),
        ),
        (
            1,
            lambda b: b["describe"]["guarantees"].update(writeAtomicity="single_transaction"),
            ("biotech", "write_atomicity"),
        ),
        (0, lambda b: b["capabilities"].append("readback"), ("ai-engineer", "readback_capability")),
        (1, lambda b: b["describe"].pop("guarantees"), ("biotech", "descriptor_parses")),
    ],
)
def test_a_drifted_live_binding_fails_its_check(index: int, change: Any, expected: Any) -> None:
    assert expected in _failed(_mutated(index, change), require_all=True)


def test_a_capture_of_another_format_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "capture.json"
    path.write_text(json.dumps({"format": "other", "bindings": []}), encoding="utf-8")

    with pytest.raises(CHECKER.Refused, match="CAPTURE_FORMAT"):
        CHECKER.load_capture(path)


def test_refresh_is_written_only_when_every_check_passes(tmp_path: Path) -> None:
    target = tmp_path / "descriptors.json"
    target.write_text(DESCRIPTORS.read_text(encoding="utf-8"), encoding="utf-8")
    drifted = _mutated(0, lambda b: b["registration"].update(storageClass="graph"))
    drifted_path = tmp_path / "drifted.json"
    drifted_path.write_text(json.dumps(drifted[0]), encoding="utf-8")
    before = target.read_bytes()

    code = CHECKER.main(
        ["--capture", str(drifted_path), "--refresh-descriptors", "--descriptors-file", str(target)]
    )
    assert code == 1
    assert target.read_bytes() == before

    args = [f"--capture={path}" for path in CAPTURES]
    assert (
        CHECKER.main(
            [*args, "--require-all", "--refresh-descriptors", "--descriptors-file", str(target)]
        )
        == 0
    )
    assert json.loads(target.read_text(encoding="utf-8"))["source"]["kind"] == "live-capture"


def _write_captures(tmp_path: Path, captures: list[dict[str, Any]]) -> list[str]:
    paths = []
    for index, capture in enumerate(captures):
        path = tmp_path / f"capture-{index}.json"
        path.write_text(json.dumps(capture), encoding="utf-8")
        paths.append(f"--capture={path}")
    return paths


def _descriptors_copy(tmp_path: Path) -> Path:
    target = tmp_path / "descriptors.json"
    target.write_text(DESCRIPTORS.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def test_the_committed_capture_digests_recompute() -> None:
    for capture in _captures():
        for row in capture["bindings"]:
            assert CHECKER.describe_digest(row["describe"]) == row["describeDigest"]


def test_a_tampered_describe_digest_fails() -> None:
    tampered = _mutated(0, lambda b: b.update(describeDigest="sha256:" + "0" * 64))

    assert _failed(tampered, require_all=True) == {("ai-engineer", "describe_digest")}


def test_a_describe_edited_after_capture_fails_its_digest() -> None:
    edited = _mutated(1, lambda b: b["describe"].update(signingIssuer="someone-else"))

    assert ("biotech", "describe_digest") in _failed(edited, require_all=True)


@pytest.mark.parametrize(
    "change",
    [
        # A registration superset (extra field) is drift, not a pass: equality, not subset.
        lambda b: b["registration"].update(extra="x"),
        lambda b: b["registration"].update(nativeCancellation="none"),
        lambda b: b["registration"]["capabilities"].append("delivery"),
    ],
)
def test_registration_drift_from_the_descriptors_fails(change: Any) -> None:
    failed = _failed(_mutated(0, change), require_all=True)

    assert ("ai-engineer", "registration_equals_descriptors") in failed


def test_describe_drift_from_the_descriptors_fails() -> None:
    def drift(binding: dict[str, Any]) -> None:
        binding["describe"]["guarantees"]["nativeCancellation"] = "native"
        binding["describeDigest"] = CHECKER.describe_digest(binding["describe"])

    assert _failed(_mutated(1, drift), require_all=True) == {
        ("biotech", "describe_matches_descriptors")
    }


def test_drift_against_a_different_descriptors_file_fails() -> None:
    descriptors = json.loads(DESCRIPTORS.read_text(encoding="utf-8"))
    descriptors["backends"][0]["storageClass"] = "document"

    failed = _failed(_captures(), require_all=True, descriptors=descriptors)
    assert failed == {("ai-engineer", "registration_equals_descriptors")}


@pytest.mark.parametrize(
    ("change", "kwargs", "expected"),
    [
        (
            lambda b: b["describe"]["pinnedSchema"].update(name="knowledge-verification-2.6.0"),
            {},
            "pinned_schema",
        ),
        (
            lambda b: b["describe"]["pinnedSchema"].update(digest="sha256:" + "1" * 64),
            {},
            "pinned_schema",
        ),
        (
            lambda b: b["describe"].update(
                protocolVersions=["ks.knowledge_operation.v2", "ks.knowledge_operation.v3"]
            ),
            {},
            "protocol_pinned",
        ),
        (lambda b: None, {"expect_component": "knowledge-verification-2.6.0"}, "pinned_schema"),
    ],
)
def test_versions_are_pinned_exactly(change: Any, kwargs: dict[str, Any], expected: str) -> None:
    def mutate(binding: dict[str, Any]) -> None:
        change(binding)
        binding["describeDigest"] = CHECKER.describe_digest(binding["describe"])

    failed = _failed(_mutated(0, mutate), require_all=True, **kwargs)
    assert ("ai-engineer", expected) in failed
    assert ("ai-engineer", "describe_digest") not in failed


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c["bindings"][0].pop("registration"),
        lambda c: c["bindings"][0].update(served="yes"),
        lambda c: c["bindings"][0].update(surprise=True),
        lambda c: c.update(extra={}),
        lambda c: c["executor"].pop("distSha256"),
        lambda c: c["bindings"][0]["registration"].pop("storageClass"),
        lambda c: c["bindings"].append("not-an-object"),
        lambda c: c["bindings"][0].update(tenantsConfigured=True),
    ],
)
def test_a_malformed_capture_is_refused_with_exit_2(
    tmp_path: Path, change: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    capture = copy.deepcopy(_captures()[0])
    change(capture)
    (path,) = _write_captures(tmp_path, [capture])

    assert CHECKER.main([path]) == 2
    assert json.loads(capsys.readouterr().out)["code"] == "CAPTURE_SHAPE"


def test_refresh_is_refused_on_descriptor_drift_without_accept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = _descriptors_copy(tmp_path)
    before = target.read_bytes()
    captures = copy.deepcopy(_captures())
    captures[1]["bindings"][0]["registration"]["researchStore"] = "elsewhere"
    args = [*_write_captures(tmp_path, captures), "--require-all"]
    args += ["--refresh-descriptors", "--descriptors-file", str(target)]

    assert CHECKER.main(args) == 1
    report = json.loads(capsys.readouterr().out)
    assert target.read_bytes() == before
    assert report["refreshed"] is None
    assert "--accept-descriptor-change" in report["refreshRefused"]
    assert report["descriptorDiff"] == [
        {
            "backend": "biotech-graph",
            "field": "researchStore",
            "descriptors": "aiengineer-postgres/PostgresResearchBinding",
            "live": "elsewhere",
        }
    ]


def test_an_accepted_descriptor_change_is_written_atomically_and_rechecked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = _descriptors_copy(tmp_path)
    captures = copy.deepcopy(_captures())
    captures[0]["bindings"][0]["registration"]["researchStore"] = "elsewhere"
    args = [*_write_captures(tmp_path, captures), "--require-all", "--refresh-descriptors"]
    args += ["--accept-descriptor-change", "--descriptors-file", str(target)]

    assert CHECKER.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["refreshed"] == str(target)
    assert [c["check"] for c in report["acceptedDescriptorChange"]] == [
        "registration_equals_descriptors"
    ]
    assert all(c["passed"] for c in report["checks"])
    written = json.loads(target.read_text(encoding="utf-8"))
    by_id = {b["id"]: b for b in written["backends"]}
    assert by_id["aiengineer-postgres"]["researchStore"] == "elsewhere"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_an_accepted_refresh_is_still_refused_when_another_check_fails(tmp_path: Path) -> None:
    target = _descriptors_copy(tmp_path)
    before = target.read_bytes()
    captures = copy.deepcopy(_captures())
    captures[0]["bindings"][0]["registration"]["storageClass"] = "graph"
    args = [*_write_captures(tmp_path, captures), "--require-all", "--refresh-descriptors"]
    args += ["--accept-descriptor-change", "--descriptors-file", str(target)]

    assert CHECKER.main(args) == 1
    assert target.read_bytes() == before


def test_an_accepted_refresh_with_a_live_guarantee_mismatch_is_not_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = _descriptors_copy(tmp_path)
    before = target.read_bytes()
    captures = copy.deepcopy(_captures())
    row = captures[1]["bindings"][0]
    row["describe"]["guarantees"]["nativeCancellation"] = "native"
    row["describeDigest"] = CHECKER.describe_digest(row["describe"])
    args = [*_write_captures(tmp_path, captures), "--require-all", "--refresh-descriptors"]
    args += ["--accept-descriptor-change", "--descriptors-file", str(target)]

    assert CHECKER.main(args) == 1
    report = json.loads(capsys.readouterr().out)
    assert target.read_bytes() == before
    assert report["refreshed"] is None
    assert "unchanged" in report["refreshRefused"]
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
