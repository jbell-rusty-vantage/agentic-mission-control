"""Vendor only the static ingress import closure. No dependency install or deployment."""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "src"
TARGET = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "temporalio",
    "langgraph",
    "langchain",
    "deepagents",
    "claude_agent_sdk",
    "cursor_sdk",
    "openai",
    "anthropic",
)


def closure() -> dict[str, bytes]:
    pending = ["mission_control.bootstrap.ingress"]
    found: dict[str, bytes] = {}
    while pending:
        module = pending.pop()
        relative = Path(*module.split("."))
        source = SOURCE / relative.with_suffix(".py")
        if not source.exists():
            source = SOURCE / relative / "__init__.py"
        if not source.exists():
            raise ValueError(f"unresolved local import: {module}")
        name = source.relative_to(SOURCE).as_posix()
        if name in found:
            continue
        content = source.read_bytes()
        found[name] = content
        for parent in source.relative_to(SOURCE).parents:
            init = SOURCE / parent / "__init__.py"
            if init.is_file():
                pending.append(".".join(parent.parts))
        for node in ast.walk(ast.parse(content)):
            imports = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package = module.split(".")[:-1]
                    imports = [
                        ".".join(
                            package[: len(package) - node.level + 1]
                            + (node.module or "").split(".")
                        )
                    ]
                elif node.module:
                    imports = [node.module]
            for dependency in imports:
                if dependency.split(".")[0] in FORBIDDEN:
                    raise ValueError(f"heavy dependency in ingress: {dependency}")
                if dependency.startswith("mission_control"):
                    pending.append(dependency)
    return found


def external_imports(files: dict[str, bytes]) -> set[str]:
    """Include conditional imports: a full developer environment can hide missing wheels."""
    roots: set[str] = set()
    for content in files.values():
        for node in ast.walk(ast.parse(content)):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                roots.add(node.module.split(".")[0])
    return roots - set(sys.stdlib_module_names) - {"mission_control"}


def validate_external_dependencies(files: dict[str, bytes], lock: dict) -> None:
    """Every external import must have a wheel in the slim project's locked closure."""
    distributions = {package["name"] for package in lock["package"]}
    aliases = {"yaml": "pyyaml", "pydantic_core": "pydantic-core"}
    missing = {
        module
        for module in external_imports(files)
        if aliases.get(module, module.replace("_", "-")) not in distributions
    }
    if missing:
        raise ValueError(f"unlocked external imports in ingress: {sorted(missing)}")


def main() -> None:
    files = closure()
    validate_external_dependencies(files, tomllib.loads((TARGET / "uv.lock").read_text()))
    existing = TARGET / "mission_control"
    if existing.is_symlink():
        raise ValueError("vendored source directory must not be a symlink")
    # Refuse stale source rather than letting previous builds silently expand the closure.
    stale = {
        path.relative_to(TARGET).as_posix()
        for path in existing.rglob("*.py")
        if path.relative_to(TARGET).as_posix() not in files
    }
    if stale:
        raise ValueError("stale vendored modules; build in a clean deployment checkout")
    manifest = {}
    for name, content in sorted(files.items()):
        target = TARGET / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        manifest[name] = hashlib.sha256(content).hexdigest()
    (TARGET / "closure.json").write_text(json.dumps(manifest, indent=2) + "\n")
    sys.stdout.write(
        json.dumps({"files": len(files), "bytes": sum(map(len, files.values()))}) + "\n"
    )


if __name__ == "__main__":
    main()
