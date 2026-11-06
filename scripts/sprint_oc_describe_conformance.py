"""Check every Application Profile against a live Knowledge Services describe (W0, WI-24).

Design §10 (application profile conformance): each `deployments/*/application.toml` names a
binding the KS descriptor advertises, its apply contract equals the backend's `nativeContract`,
and its minimums are not below the annex's required classes. The offline suite checks this
against the hand-copied `tests/conformance/applications/ks_backend_descriptors.json`; this
script checks it against captures of the LIVE composition, written by KS
`apps/verification-executor/scripts/capture-live-describe.mjs` (`ks.live-describe-capture.v1`):
the K01 `knowledge.describe` document of each binding plus its registry `BACKEND.describe()`.

    uv run --no-sync python scripts/sprint_oc_describe_conformance.py --require-all
        --capture <ai-engineer capture.json> --capture <biotech capture.json>
        [--out <report.json>] [--descriptors-file <ks_backend_descriptors.json>]
        [--expect-component knowledge-verification-2.5.0] [--expect-schema-digest sha256:...]
        [--refresh-descriptors [--accept-descriptor-change]]

Every live registration must EQUAL its entry in the authoritative descriptors file (default the
committed `ks_backend_descriptors.json`), and the live describe's guarantees, protocol versions and
apply operation must agree with that entry; the pinned schema must equal `--expect-component` and
`--expect-schema-digest` exactly, and each `describeDigest` is recomputed from its `describe`.

`--refresh-descriptors` rewrites the registry descriptors in `--descriptors-file` from the captures
(atomically: temporary file plus rename); backends no capture names are kept. It refuses when any
check fails, and when the live registrations differ from the file unless
`--accept-descriptor-change` is given; the per-field descriptor diff is reported either way. An
accepted change is written only if every check passes against the refreshed descriptors. The
script is otherwise read-only, opens no connection and holds no secret (a capture holds none).
Exit: 0 every check passed, 1 a check failed or a refresh was refused, 2 the input was refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mission_control.bootstrap.application_profiles import load_application_file
from mission_control.bootstrap.composition import knowledge_component_supported
from mission_control.contracts.knowledge_protocol import PROTOCOL_VERSION
from mission_control.contracts.knowledge_protocol_results import BindingDescriptor
from mission_control.domain.resolution.profiles import (
    ANNEX_CONSEQUENTIAL_SIGNOFF_CLASSES,
    ANNEX_REQUIRED_REVIEW_CLASSES,
    below_annex_minimums,
)

_ABSENT = object()
ROOT = Path(__file__).resolve().parents[1]
DEPLOYMENTS = ROOT / "deployments"
DESCRIPTORS = ROOT / "tests" / "conformance" / "applications" / "ks_backend_descriptors.json"
CAPTURE_FORMAT = "ks.live-describe-capture.v1"
EXPECTED_COMPONENT = "knowledge-verification-2.5.0"
# release-bundle.json components.knowledgeVerification.k01PinnedSchema.digest (KS 2.5.0).
EXPECTED_SCHEMA_DIGEST = "sha256:728e4d8aa64a857185be19181886da22ad8952dcec6e4f8a3bf9bf0578d2fd18"
# Checks that compare the live composition with the descriptors file; an accepted refresh may
# change them, every other failing check refuses the refresh.
DESCRIPTOR_CHECKS = frozenset({"registration_equals_descriptors", "describe_matches_descriptors"})
REGISTRATION_FIELDS = (
    "id",
    "capabilities",
    "conditionalCapabilities",
    "storageClass",
    "writeAtomicity",
    "nativeCancellation",
    "nativeContract",
    "researchStore",
)


class Refused(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Check:
    application: str
    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "application": self.application,
            "check": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }


_STR = (str,)
_OPT_STR = (str, type(None))
_OPT_INT = (int, type(None))
# Exact key sets of `ks.live-describe-capture.v1` (KS capture-live-describe.mjs) and their types.
CAPTURE_KEYS: dict[str, tuple[type, ...]] = {
    "format": _STR,
    "capturedAt": _STR,
    "purpose": _STR,
    "composition": _STR,
    "executor": (dict,),
    "envFile": (dict,),
    "registeredBackends": (list,),
    "bindings": (list,),
}
EXECUTOR_KEYS: dict[str, tuple[type, ...]] = {
    "dist": _STR,
    "distSha256": _STR,
    "commit": _OPT_STR,
    "trackedChanges": _OPT_INT,
    "node": _STR,
}
ROW_KEYS: dict[str, tuple[type, ...]] = {
    "application": _STR,
    "binding": _STR,
    "installationId": _OPT_STR,
    "tenantsConfigured": (int,),
    "served": (bool,),
    "unsupportedReason": _OPT_STR,
    "capabilities": (list,),
    "registration": (dict,),
    "describe": (dict,),
    "describeDigest": _STR,
}


def _validate_object(value: Any, keys: dict[str, tuple[type, ...]], where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise Refused("CAPTURE_SHAPE", f"{where} is not an object")
    missing = sorted(set(keys) - set(value))
    unexpected = sorted(set(value) - set(keys))
    if missing or unexpected:
        raise Refused("CAPTURE_SHAPE", f"{where}: missing {missing} unexpected {unexpected}")
    for key, types in keys.items():
        item = value[key]
        # bool is an int subclass; an int field must not accept true/false.
        if not isinstance(item, types) or (isinstance(item, bool) and bool not in types):
            raise Refused("CAPTURE_SHAPE", f"{where}.{key} is {type(item).__name__}")
    return value


def _validate_registration(registration: dict[str, Any], where: str) -> None:
    missing = sorted(set(REGISTRATION_FIELDS) - set(registration))
    if missing:
        raise Refused("CAPTURE_SHAPE", f"{where}.registration: missing {missing}")
    for field in ("id", "storageClass", "writeAtomicity", "nativeCancellation"):
        if not isinstance(registration[field], str):
            raise Refused("CAPTURE_SHAPE", f"{where}.registration.{field} is not a string")
    conditional = registration["conditionalCapabilities"]
    if not isinstance(registration["capabilities"], list) or not isinstance(conditional, list):
        raise Refused("CAPTURE_SHAPE", f"{where}.registration capabilities are not lists")
    if not all(isinstance(c, dict) and isinstance(c.get("capability"), str) for c in conditional):
        raise Refused("CAPTURE_SHAPE", f"{where}.registration.conditionalCapabilities is malformed")


def load_capture(path: Path) -> dict[str, Any]:
    """A `ks.live-describe-capture.v1` document with exactly the keys and types KS writes."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Refused("CAPTURE_UNREADABLE", str(path)) from None
    if not isinstance(document, dict) or document.get("format") != CAPTURE_FORMAT:
        raise Refused("CAPTURE_FORMAT", f"{path} is not {CAPTURE_FORMAT}")
    if not isinstance(document.get("bindings"), list):
        raise Refused("CAPTURE_FORMAT", f"{path} has no bindings list")
    name = path.name
    _validate_object(document, CAPTURE_KEYS, name)
    _validate_object(document["executor"], EXECUTOR_KEYS, f"{name}.executor")
    for index, row in enumerate(document["bindings"]):
        where = f"{name}.bindings[{index}]"
        _validate_object(row, ROW_KEYS, where)
        if not all(isinstance(c, str) for c in row["capabilities"]):
            raise Refused("CAPTURE_SHAPE", f"{where}.capabilities holds a non-string")
        _validate_registration(row["registration"], where)
    return document


def canonical_json(value: Any) -> str:
    """The KS capture script's `canonical()`: sorted keys, no whitespace, JSON.stringify scalars."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def describe_digest(describe: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(describe).encode("utf-8")).hexdigest()


def load_descriptors(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Refused("DESCRIPTORS_UNREADABLE", str(path)) from None
    backends = document.get("backends") if isinstance(document, dict) else None
    if not isinstance(backends, list) or not all(
        isinstance(b, dict) and isinstance(b.get("id"), str) for b in backends
    ):
        raise Refused("DESCRIPTORS_FORMAT", f"{path} has no backends list with ids")
    return document


def captured_bindings(captures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [row for capture in captures for row in capture["bindings"]]
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row["application"], row["binding"])
        if key in seen:
            raise Refused("CAPTURE_DUPLICATE", f"{key[0]}/{key[1]} is captured twice")
        seen.add(key)
    return rows


def check_profile(
    path: Path,
    rows: list[dict[str, Any]],
    descriptors: dict[str, Any],
    *,
    expect_component: str = EXPECTED_COMPONENT,
    expect_schema_digest: str | None = EXPECTED_SCHEMA_DIGEST,
) -> list[Check]:
    """The design §10 facts for one profile against its captured live binding and descriptors."""

    profile = load_application_file(path).profile
    app = profile.application_id
    knowledge = profile.knowledge
    checks: list[Check] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append(Check(app, name, passed, detail))

    outputs = profile.outputs
    missing_review = ANNEX_REQUIRED_REVIEW_CLASSES - set(outputs.required_review_classes)
    missing_signoff = ANNEX_CONSEQUENTIAL_SIGNOFF_CLASSES - set(
        outputs.consequential_signoff_classes
    )
    below = below_annex_minimums(profile)
    record(
        "minimums_not_below_annex",
        not below and not missing_review and not missing_signoff,
        "ok" if not below and not missing_review and not missing_signoff else f"{below}",
    )

    row = next(
        (r for r in rows if r["application"] == app and r["binding"] == knowledge.binding_id), None
    )
    if row is None:
        offered = sorted(
            f"{r['application']}/{r['binding']}" for r in rows if r["application"] == app
        )
        record(
            "binding_advertised",
            False,
            f"no live binding {knowledge.binding_id}; captured {offered}",
        )
        return checks
    describe = row["describe"]
    registration = row["registration"]
    recomputed = describe_digest(describe)
    record(
        "describe_digest",
        recomputed == row["describeDigest"],
        "ok"
        if recomputed == row["describeDigest"]
        else f"captured {row['describeDigest']} recomputed {recomputed}",
    )
    advertised = (
        row["served"] is True
        and describe.get("binding") == knowledge.binding_id
        and describe.get("application") == app
        and registration.get("id") == knowledge.binding_id
    )
    record(
        "binding_advertised",
        advertised,
        "served" if advertised else f"served={row['served']} reason={row['unsupportedReason']}",
    )
    try:
        BindingDescriptor.model_validate(describe)
        record("descriptor_parses", True, "mission_control BindingDescriptor")
    except ValueError as exc:
        record("descriptor_parses", False, str(exc).splitlines()[0])
    protocols = describe.get("protocolVersions")
    record(
        "protocol_pinned",
        protocols == [PROTOCOL_VERSION],
        f"advertised {protocols} pinned [{PROTOCOL_VERSION}]",
    )
    pinned_schema = describe.get("pinnedSchema")
    pinned_schema = pinned_schema if isinstance(pinned_schema, dict) else {}
    pinned = str(pinned_schema.get("name", ""))
    record("component_supported", knowledge_component_supported(pinned), pinned)
    digest = pinned_schema.get("digest")
    pinned_ok = pinned == expect_component and (
        expect_schema_digest is None or digest is None or digest == expect_schema_digest
    )
    record(
        "pinned_schema",
        pinned_ok,
        f"live {pinned} {digest} expected {expect_component} {expect_schema_digest}",
    )
    checks.extend(_descriptor_checks(app, knowledge.binding_id, row, descriptors))
    contract = {"name": knowledge.apply_contract_name, "version": knowledge.apply_contract_version}
    record(
        "apply_contract_equals_native_contract",
        registration.get("nativeContract") == contract,
        f"profile {contract} backend {registration.get('nativeContract')}",
    )
    apply_served = (
        "knowledge.apply" in describe.get("operations", []) and "apply" in row["capabilities"]
    )
    record(
        "apply_served", apply_served, "knowledge.apply advertised" if apply_served else "not served"
    )
    record(
        "storage_class",
        registration.get("storageClass") == knowledge.storage_class,
        f"profile {knowledge.storage_class} backend {registration.get('storageClass')}",
    )
    live_atomicity = describe.get("guarantees", {}).get("writeAtomicity")
    record(
        "write_atomicity",
        registration.get("writeAtomicity") == live_atomicity == knowledge.write_atomicity,
        f"profile {knowledge.write_atomicity} live {live_atomicity}",
    )
    readback = "native" if "readback" in row["capabilities"] else "unsupported"
    record(
        "readback_capability",
        knowledge.readback_capability == readback,
        f"profile {knowledge.readback_capability} live {readback}",
    )
    declared = set(registration.get("capabilities", [])) | {
        c["capability"] for c in registration.get("conditionalCapabilities", [])
    }
    undeclared = sorted(set(row["capabilities"]) - declared)
    record("describe_honesty", not undeclared, f"undeclared {undeclared}" if undeclared else "ok")
    return checks


def _descriptor_checks(
    app: str, binding: str, row: dict[str, Any], descriptors: dict[str, Any]
) -> list[Check]:
    """The live registration equals its descriptors entry; the live describe agrees with it."""

    entry = next((b for b in descriptors["backends"] if b["id"] == binding), None)
    if entry is None:
        detail = f"no descriptor {binding} in the descriptors file"
        return [
            Check(app, "registration_equals_descriptors", False, detail),
            Check(app, "describe_matches_descriptors", False, detail),
        ]
    registration = row["registration"]
    fields = sorted(set(entry) | set(registration))
    differing = [f for f in fields if entry.get(f, _ABSENT) != registration.get(f, _ABSENT)]
    describe = row["describe"]
    guarantees = describe.get("guarantees")
    guarantees = guarantees if isinstance(guarantees, dict) else {}
    operations = describe.get("operations")
    operations = operations if isinstance(operations, list) else []
    drift = [
        f"guarantees.{field} {guarantees.get(field)} descriptor {entry.get(field)}"
        for field in ("writeAtomicity", "nativeCancellation")
        if guarantees.get(field) != entry.get(field)
    ]
    if describe.get("protocolVersions") != [PROTOCOL_VERSION]:
        drift.append(f"protocolVersions {describe.get('protocolVersions')}")
    may_apply = "apply" in entry.get("capabilities", []) or any(
        c.get("capability") == "apply" for c in entry.get("conditionalCapabilities", [])
    )
    apply_advertised = "knowledge.apply" in operations
    apply_served = "apply" in row["capabilities"]
    if apply_advertised != apply_served or (apply_advertised and not may_apply):
        drift.append(
            f"operations knowledge.apply={apply_advertised} served apply={apply_served} "
            f"descriptor apply={may_apply}"
        )
    return [
        Check(
            app,
            "registration_equals_descriptors",
            not differing,
            "equal" if not differing else f"differing fields {differing}",
        ),
        Check(app, "describe_matches_descriptors", not drift, "; ".join(drift) or "ok"),
    ]


def run_checks(
    captures: list[dict[str, Any]],
    *,
    deployments: Path = DEPLOYMENTS,
    require_all: bool = False,
    descriptors: dict[str, Any] | None = None,
    expect_component: str = EXPECTED_COMPONENT,
    expect_schema_digest: str | None = EXPECTED_SCHEMA_DIGEST,
) -> list[Check]:
    if descriptors is None:
        descriptors = load_descriptors(DESCRIPTORS)
    rows = captured_bindings(captures)
    captured_apps = {row["application"] for row in rows}
    checks: list[Check] = []
    for path in sorted(deployments.glob("*/application.toml")):
        app = path.parent.name
        if app not in captured_apps:
            if require_all:
                checks.append(
                    Check(app, "captured", False, "no live capture names this application")
                )
            continue
        checks.extend(
            check_profile(
                path,
                rows,
                descriptors,
                expect_component=expect_component,
                expect_schema_digest=expect_schema_digest,
            )
        )
    if not checks:
        raise Refused("NOTHING_CHECKED", "no Application Profile matched a captured application")
    return checks


def refreshed_descriptors(
    current: dict[str, Any], captures: list[dict[str, Any]]
) -> dict[str, Any]:
    """`current` with each captured backend's registry descriptor replaced from the live capture."""

    backends = {backend["id"]: backend for backend in current.get("backends", [])}
    for row in captured_bindings(captures):
        registration = row["registration"]
        backends[registration["id"]] = {field: registration[field] for field in REGISTRATION_FIELDS}
    sources = [
        {
            "capturedAt": capture["capturedAt"],
            "commit": capture["executor"].get("commit"),
            "trackedChanges": capture["executor"].get("trackedChanges"),
            "distSha256": capture["executor"].get("distSha256"),
            "bindings": sorted(f"{r['application']}/{r['binding']}" for r in capture["bindings"]),
        }
        for capture in captures
    ]
    return {
        "source": {
            "repository": "platform/knowledge-services",
            "kind": "live-capture",
            "captures": sources,
            "note": (
                "Registry descriptors refreshed by scripts/sprint_oc_describe_conformance.py "
                "--refresh-descriptors from KS capture-live-describe.mjs captures of the live "
                "executor composition (W0). An offline drift guard; the live check is the script."
            ),
        },
        "backends": [backends[key] for key in sorted(backends)],
    }


def descriptor_diff(current: dict[str, Any], refreshed: dict[str, Any]) -> list[dict[str, Any]]:
    """Per backend and field, what a refresh would change in the descriptors file."""

    before = {b["id"]: b for b in current.get("backends", [])}
    after = {b["id"]: b for b in refreshed.get("backends", [])}
    diff: list[dict[str, Any]] = []
    for backend in sorted(set(before) | set(after)):
        old, new = before.get(backend, {}), after.get(backend, {})
        for field in sorted(set(old) | set(new)):
            if old.get(field, _ABSENT) != new.get(field, _ABSENT):
                diff.append(
                    {
                        "backend": backend,
                        "field": field,
                        "descriptors": old.get(field),
                        "live": new.get(field),
                    }
                )
    return diff


def write_atomically(path: Path, text: str) -> None:
    """Write `text` to a temporary file beside `path`, then rename it over `path`."""

    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--capture", type=Path, action="append", required=True)
    parser.add_argument("--deployments-root", type=Path, default=DEPLOYMENTS)
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--descriptors-file", type=Path, default=DESCRIPTORS)
    parser.add_argument("--expect-component", default=EXPECTED_COMPONENT)
    parser.add_argument("--expect-schema-digest", default=EXPECTED_SCHEMA_DIGEST)
    parser.add_argument("--refresh-descriptors", action="store_true")
    parser.add_argument("--accept-descriptor-change", action="store_true")
    args = parser.parse_args(argv)
    if args.accept_descriptor_change and not args.refresh_descriptors:
        parser.error("--accept-descriptor-change requires --refresh-descriptors")
    expect = {
        "expect_component": args.expect_component,
        "expect_schema_digest": args.expect_schema_digest,
    }
    try:
        captures = [load_capture(path) for path in args.capture]
        current = load_descriptors(args.descriptors_file)
        checks = run_checks(
            captures,
            deployments=args.deployments_root,
            require_all=args.require_all,
            descriptors=current,
            **expect,
        )
        refreshed = refreshed_descriptors(current, captures)
    except Refused as refused:
        print(json.dumps({"status": "refused", "code": refused.code, "detail": refused.detail}))
        return 2
    diff = descriptor_diff(current, refreshed)
    failed = [check for check in checks if not check.passed]
    report: dict[str, Any] = {
        "status": "failed" if failed else "passed",
        "expected": {"component": args.expect_component, "schemaDigest": args.expect_schema_digest},
        "descriptorsFile": str(args.descriptors_file),
        "descriptorDiff": diff,
        "captures": [
            {
                "capturedAt": c["capturedAt"],
                "commit": c["executor"].get("commit"),
                "bindings": [
                    {
                        "application": r["application"],
                        "binding": r["binding"],
                        "pinnedSchema": r["describe"].get("pinnedSchema"),
                        "describeDigest": r.get("describeDigest"),
                    }
                    for r in c["bindings"]
                ],
            }
            for c in captures
        ],
        "checks": [check.as_dict() for check in checks],
    }
    if args.refresh_descriptors:
        blocking = [c for c in failed if c.name not in DESCRIPTOR_CHECKS]
        descriptor_failures = [c for c in failed if c.name in DESCRIPTOR_CHECKS]
        if blocking:
            report["refreshed"] = None
            report["refreshRefused"] = "a non-descriptor check failed"
        elif (descriptor_failures or diff) and not args.accept_descriptor_change:
            report["refreshed"] = None
            report["refreshRefused"] = (
                "the live registrations differ from the descriptors file; review descriptorDiff "
                "and rerun with --accept-descriptor-change"
            )
            report["status"] = "failed"
        else:
            # Re-check against the refreshed descriptors in memory first: a live-internal
            # inconsistency (describe disagreeing with its own registration) is never written.
            rechecked = run_checks(
                captures,
                deployments=args.deployments_root,
                require_all=args.require_all,
                descriptors=refreshed,
                **expect,
            )
            if descriptor_failures or diff:
                report["acceptedDescriptorChange"] = [c.as_dict() for c in descriptor_failures]
                report["checks"] = [check.as_dict() for check in rechecked]
            if all(c.passed for c in rechecked):
                write_atomically(args.descriptors_file, json.dumps(refreshed, indent=2) + "\n")
                report["refreshed"] = str(args.descriptors_file)
                report["status"] = "passed"
            else:
                report["refreshed"] = None
                report["refreshRefused"] = (
                    "a check fails against the refreshed descriptors; the file is unchanged"
                )
                report["status"] = "failed"
    text = json.dumps(report, indent=2)
    if args.out:
        write_atomically(args.out, text + "\n")
    print(text)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
