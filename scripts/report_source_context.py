"""Reproducible local fixture context over canonical domain materializers and KS contracts.

The resulting context is read-only guidance, never a grant to write native knowledge.
Only the canonical CLIs load schema IR; this composer reads their bounded outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

MC_ROOT = Path(__file__).resolve().parents[1]
PROFILES = MC_ROOT / "tests/fixtures/report-source-foundation/context"
KS = "platform/knowledge-services"
AIDB = "aiengineer/ai-engineer-db-contract"
BKS = "biotech/biotech-knowledge-services"
IMPORT = re.compile(r"(?:from\s+|import\s*)[\"']([^\"']+)[\"']")
NAMED_PROTOCOL_IMPORT = re.compile(
    r"import\s+(?:type\s+)?\{([^}]+)\}\s+from\s+[\"']@aiengineer/knowledge-operation-protocol[\"']"
)


def _protocol_dependencies(root: Path, text: str) -> list[str]:
    """Resolve named public exports without pulling the whole protocol barrel into context."""
    base = root / "packages/knowledge-operation-protocol/src"
    names = {
        re.sub(r"^type\s+", "", name.strip()).split(" as ")[0]
        for group in NAMED_PROTOCOL_IMPORT.findall(text)
        for name in group.split(",")
        if name.strip()
    }
    if not names:
        raise ValueError("protocol imports must be named")
    resolved = {}
    for reference in IMPORT.findall((base / "index.ts").read_text(encoding="utf-8")):
        path = (base / reference).with_suffix(".ts")
        exports = set(
            re.findall(
                r"export\s+(?:declare\s+)?(?:const|type|interface|function|class|enum)\s+(\w+)",
                path.read_text(encoding="utf-8"),
            )
        )
        for name in names & exports:
            resolved[name] = path.relative_to(root).as_posix()
    if names - resolved.keys():
        raise ValueError(f"unresolved protocol symbols: {sorted(names - resolved.keys())}")
    return sorted(set(resolved.values()))


def digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()


def confined(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes root: {relative}")
    return path


def contract_closure(root: Path, seeds: list[str]) -> tuple[dict[str, bytes], list[str]]:
    """Resolve local module dependencies; external runtime libraries stay explicit references."""
    pending = list(seeds)
    files: dict[str, bytes] = {}
    external: set[str] = set()
    while pending:
        name = pending.pop()
        if name in files:
            continue
        path = confined(root, name)
        files[name] = path.read_bytes()  # Missing references fail closed.
        if path.suffix != ".ts":
            continue
        for reference in IMPORT.findall(files[name].decode("utf-8")):
            if reference.startswith("."):
                dependency = path.parent / reference
                dependency = dependency.with_suffix(".ts")
                pending.append(dependency.resolve().relative_to(root.resolve()).as_posix())
            elif reference == "@aiengineer/knowledge-operation-protocol":
                pending.extend(_protocol_dependencies(root, files[name].decode("utf-8")))
            elif reference in {"zod", "node:crypto"}:
                external.add(reference)
            else:
                raise ValueError(f"unresolved contract dependency: {reference}")
    return dict(sorted(files.items())), sorted(external)


def _run(arguments: list[str], cwd: Path) -> None:
    result = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(
            f"materializer failed ({result.returncode}): {result.stderr or result.stdout}"
        )


def _domain(workspace: Path, profile: dict[str, Any], out: Path) -> dict[str, Any]:
    domain = out / "domain"
    if profile["application"] == "ai-engineer":
        scope = out / "scope.json"
        scope.write_bytes(canonical(profile["scope"]))
        _run(
            [
                "node",
                "scripts/schema-workspace/cli.mjs",
                "materialize",
                "--scope",
                str(scope),
                "--out",
                str(domain),
                "--format",
                "tree",
            ],
            workspace / AIDB,
        )
        manifest = json.loads((domain / "manifest.json").read_text(encoding="utf-8"))
        return {
            "route": "aidb-canonical-scope-cli",
            "source": manifest["build"],
            "selection": manifest["scope"],
            "retained_vocabularies": manifest["layers"]["vocabularies"],
            "closure": (
                "Canonical FK stubs; domain cards are navigation only, not runtime dependencies."
            ),
        }
    _run(
        [
            "node",
            "packages/schema-workspace/dist/cli.js",
            "slice",
            "--tasks",
            "trace-answer-to-source",
            "--purpose",
            "read",
            "--max-tokens",
            "12000",
            "--out",
            str(domain),
        ],
        workspace / BKS,
    )
    sliced = json.loads((domain / "slice.json").read_text(encoding="utf-8"))
    return {"route": "bks-canonical-slice-cli", "slice": sliced}


def materialize_context(workspace_root: Path, profile_path: Path, out_dir: Path) -> dict[str, Any]:
    """Create a fresh bundle; callers must verify and read context.txt before delivery."""
    workspace_root, out_dir = workspace_root.resolve(), out_dir.resolve()
    profile_bytes = profile_path.read_bytes()
    profile = json.loads(profile_bytes)
    if profile["format"] != "mc-report-source-context-profile.v1":
        raise ValueError("unsupported profile")
    if out_dir.exists():
        raise ValueError("output directory must be fresh")
    out_dir.mkdir(parents=True)
    (out_dir / "profile.json").write_bytes(profile_bytes)
    metadata = _domain(workspace_root, profile, out_dir)
    contracts, external = contract_closure(workspace_root / KS, profile["shared_contracts"])
    for name, data in contracts.items():
        target = confined(out_dir / "shared", name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    domain_files = sorted(
        p.relative_to(out_dir).as_posix() for p in (out_dir / "domain").rglob("*") if p.is_file()
    )
    if profile["application"] == "ai-engineer":
        selected = ["domain/" + p for p in profile["navigation_cards"]]
    else:
        selected = [p for p in domain_files if p.endswith((".md", ".graphql"))]
    selected += ["shared/" + name for name in contracts]
    omitted = sorted(set(domain_files) - set(selected))
    # Links in navigation cards are advisory, and omitted targets are never silently resolved.
    navigation_refs = []
    for name in selected:
        if name.startswith("domain/") and name.endswith(".md"):
            for reference in re.findall(
                r"\]\(([^)]+)\)", (out_dir / name).read_text(encoding="utf-8")
            ):
                if "://" not in reference and not reference.startswith("#"):
                    target = (out_dir / name).parent / reference.split("#")[0]
                    relative = target.resolve().relative_to(out_dir).as_posix()
                    if relative not in selected:
                        navigation_refs.append(
                            {
                                "from": name,
                                "target": relative,
                                "status": "navigation-only; omitted from runtime context",
                            }
                        )
    header = {
        k: profile[k]
        for k in (
            "id",
            "application",
            "task_scope",
            "audience",
            "use",
            "report_kind",
            "qualifier_profile",
            "authority",
        )
    }
    context = b"# Report/source foundation: read-only context\n" + canonical(header)
    context += (
        b"\nDomain navigation is advisory. Shared KS contracts govern operational records. "
        b"No native write authority.\n"
    )
    context += canonical(
        {"navigation_only_omitted_targets": sorted({item["target"] for item in navigation_refs})}
    )
    if "slice" in metadata:
        context += canonical(
            {key: metadata["slice"][key] for key in ("closure", "omissions", "budget")}
        )
    else:
        context += canonical(
            {
                "retained_vocabularies_in_evidence_only": metadata["retained_vocabularies"],
                "domain_scope_omissions": metadata["selection"]["omitted"]["relations"],
                "scope_note": metadata["closure"],
            }
        )
    for name in selected:
        context += f"\n--- {name} ---\n".encode() + (out_dir / name).read_bytes() + b"\n"
    # StateBackend read_file normalizes line endings. Preserve raw source copies separately,
    # and bind the delivered representation to explicit LF bytes before sealing its digest.
    context = context.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if len(context) > profile["max_context_bytes"]:
        raise ValueError(
            f"context byte budget exceeded: {len(context)} > {profile['max_context_bytes']}"
        )
    (out_dir / "context.txt").write_bytes(context)
    inventory = {}
    for path in sorted(out_dir.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            inventory[path.relative_to(out_dir).as_posix()] = {
                "digest": digest(data),
                "bytes": len(data),
            }
    manifest = {
        "format": "mc-report-source-context.v1",
        "profile": profile["id"],
        "context": {
            "path": "context.txt",
            "digest": digest(context),
            "bytes": len(context),
            "max_bytes": profile["max_context_bytes"],
            "normalization": "utf8-lf.v1",
        },
        "materializer": metadata,
        "selected": selected,
        "omitted_artifacts": omitted,
        "navigation_omissions": navigation_refs,
        "shared_dependency_closure": list(contracts),
        "external_dependencies": external,
        "files": inventory,
        "composer_digest": digest(Path(__file__).read_bytes()),
        "shared_source_fingerprint": digest(
            canonical({name: digest(data) for name, data in contracts.items()})
        ),
    }
    manifest["manifest_digest"] = digest(canonical(manifest))
    (out_dir / "manifest.json").write_bytes(canonical(manifest))
    return verify_context(out_dir)


def verify_context(out_dir: Path, expected_manifest_digest: str | None = None) -> dict[str, Any]:
    """Verify inventory and manifest before reading exact bytes into a receiving context."""
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    expected = manifest.pop("manifest_digest")
    if expected_manifest_digest is not None and expected != expected_manifest_digest:
        raise ValueError("unexpected manifest identity")
    if manifest["format"] != "mc-report-source-context.v1":
        raise ValueError("unsupported bundle format")
    if digest(canonical(manifest)) != expected:
        raise ValueError("manifest digest mismatch")
    manifest["manifest_digest"] = expected
    actual_paths = {
        path.relative_to(out_dir).as_posix() for path in out_dir.rglob("*") if path.is_file()
    }
    if actual_paths != set(manifest["files"]) | {"manifest.json"}:
        raise ValueError("bundle inventory mismatch")
    for name, record in manifest["files"].items():
        data = confined(out_dir, name).read_bytes()
        if digest(data) != record["digest"] or len(data) != record["bytes"]:
            raise ValueError(f"bundle digest mismatch: {name}")
    data = confined(out_dir, manifest["context"]["path"]).read_bytes()
    if (
        digest(data) != manifest["context"]["digest"]
        or len(data) != manifest["context"]["bytes"]
        or len(data) > manifest["context"]["max_bytes"]
    ):
        raise ValueError("context digest or budget mismatch")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["ai-engineer", "biotech"], required=True)
    parser.add_argument("--workspace", type=Path, default=MC_ROOT.parents[1])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = materialize_context(args.workspace, PROFILES / f"{args.profile}.json", args.out)
    print(json.dumps({"profile": result["profile"], "context": result["context"]}, indent=2))
