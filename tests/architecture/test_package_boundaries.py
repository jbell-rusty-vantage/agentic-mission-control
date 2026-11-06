"""Executable ownership rules for the single general Mission Control distribution.

These inspect every source module, including function-local and TYPE_CHECKING imports.
They fail on an empty scan, so moving a directory cannot silently disable the gates.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "mission_control"
PROVIDER_OR_TRANSPORT_SDKS = {
    "asyncpg",
    "psycopg",
    "psycopg_pool",
    "pymongo",
    "beanie",
    "motor",
    "temporalio",
    "fastapi",
    "starlette",
    "fastmcp",
    "mcp",
    "uvicorn",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langchain_anthropic",
    "langchain_mcp_adapters",
    "langgraph",
    "langgraph_sdk",
    "langgraph_api",
    "deepagents",
    "openai",
    "anthropic",
    "supabase",
    "neo4j",
    "redis",
    "httpx",
    "aiohttp",
    "aioboto3",
    "boto3",
    "botocore",
    "langsmith",
    "socketio",
    "requests",
}
EXTERNAL_APPLICATION_PACKAGES = {
    "app",
    "biotech_mission_adapters",
    "biotech_postgres_db_contract",
    "ai_engineer",
    "aiengineer",
    "experiments",
}


def sources(directory: Path = PACKAGE) -> list[Path]:
    files = sorted(directory.rglob("*.py"))
    assert files, f"Architecture scan found no Python sources: {directory}"
    return files


def imports(path: Path) -> list[tuple[int, str]]:
    module = ".".join(path.relative_to(PACKAGE.parent).with_suffix("").parts)
    package = (
        module.removesuffix(".__init__") if path.name == "__init__.py" else module.rsplit(".", 1)[0]
    )
    result = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))):
        if isinstance(node, ast.Import):
            result.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            name = node.module or ""
            if node.level:
                name = importlib.util.resolve_name("." * node.level + name, package)
            result.append((node.lineno, name))
        elif isinstance(node, ast.Call) and node.args:
            # Literal dynamic imports must obey the same rules as ordinary imports.
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if name in {"import_module", "__import__"}:
                argument = node.args[0]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    result.append((node.lineno, argument.value))
    return result


def violations(directory: Path, forbidden_layers: set[str]) -> list[str]:
    found = []
    for path in sources(directory):
        for line, module in imports(path):
            parts = module.split(".")
            if parts[0] in PROVIDER_OR_TRANSPORT_SDKS or (
                parts[0] == "mission_control" and len(parts) > 1 and parts[1] in forbidden_layers
            ):
                found.append(f"{path.relative_to(ROOT)}:{line}: {module}")
    return found


@pytest.mark.parametrize("area", ["contracts", "domain"])
def test_contracts_and_domain_are_framework_neutral(area):
    assert not (
        found := violations(PACKAGE / area, {"application", "adapters", "interfaces", "bootstrap"})
    ), "\n".join(found)


# The describe aggregator (OC-R3, design §6.1) is the one application module that reads lane
# packages: their `describe.py` modules, which are declarations as data (domain imports only,
# `test_lane_describe_modules_are_pure_declarations`). Nothing else in the application imports
# an adapter.
DESCRIBE_AGGREGATOR = PACKAGE / "application" / "execution" / "harness" / "describe.py"
_LANE_DESCRIBE_MODULE = re.compile(r"^mission_control\.adapters\.(\w+)\.describe$")


def test_application_depends_on_ports_not_concrete_implementations():
    found = violations(PACKAGE / "application", {"adapters", "interfaces", "bootstrap"})
    aggregated = f"{DESCRIBE_AGGREGATOR.relative_to(ROOT)}:"
    allowed = [
        line
        for line in found
        if line.startswith(aggregated)
        and (match := _LANE_DESCRIBE_MODULE.match(line.rsplit(": ", 1)[1]))
        and match.group(1) in LANE_PACKAGES
    ]
    assert allowed, "the describe aggregator reads no lane package describe module"
    assert not (rest := [line for line in found if line not in allowed]), "\n".join(rest)


def test_lane_describe_modules_are_pure_declarations():
    modules = sorted(
        path
        for path in (PACKAGE / "adapters").glob("*/describe.py")
        if path.parent.name in LANE_PACKAGES
    )
    assert len(modules) >= 6, modules
    for path in modules:
        _assert_pure_declaration(path, seen=set())


# What a lane's declaration data may import: domain types, the standard library pieces they
# need, pydantic, and pure modules of its own lane package (Deep Agents `routes.py`, R6).
_PURE_EXTERNAL = {"__future__", "collections", "typing", "pydantic"}


def _assert_pure_declaration(path: Path, *, seen: set[Path]) -> None:
    if path in seen:
        return
    seen.add(path)
    lane = path.parent.name
    for line, module in imports(path):
        parts = module.split(".")
        where = f"{path.relative_to(ROOT)}:{line}: {module}"
        if parts[0] != "mission_control":
            assert parts[0] in _PURE_EXTERNAL, where
        elif parts[1] == "adapters":
            assert parts[2] == lane and len(parts) == 4, where
            _assert_pure_declaration(PACKAGE / "adapters" / lane / f"{parts[3]}.py", seen=seen)
        else:
            assert parts[1] == "domain", where


def test_core_has_no_legacy_or_application_owned_imports():
    found = [
        f"{path.relative_to(ROOT)}:{line}: {module}"
        for path in sources()
        for line, module in imports(path)
        if module.split(".")[0] in EXTERNAL_APPLICATION_PACKAGES
    ]
    assert not found, "General runtime imports application or legacy code:\n" + "\n".join(found)
    # Personal untracked experiments are not part of the distribution or our cleanup scope.
    tracked = (
        subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={ROOT.as_posix()}",
                "ls-files",
                "-z",
                "--",
                "app",
                "mission_control",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        .stdout.decode()
        .split("\0")
    )
    duplicates = [name for name in tracked if name.endswith(".py") and (ROOT / name).is_file()]
    assert not duplicates, f"Tracked second Python implementation remains: {duplicates}"


def test_all_internal_import_modules_exist_in_the_single_source_package():
    missing = []
    for path in sources():
        for line, module in imports(path):
            if module == "mission_control" or not module.startswith("mission_control."):
                continue
            target = PACKAGE.parent.joinpath(*module.split("."))
            if not target.with_suffix(".py").is_file() and not target.is_dir():
                missing.append(f"{path.relative_to(ROOT)}:{line}: {module}")
    assert not missing, "Imports missing from installed source package:\n" + "\n".join(missing)


@pytest.mark.parametrize(
    "module",
    ["mission_control.domain.programs.watchers", "mission_control.domain.programs.completion"],
)
def test_domain_program_modules_import_first_in_a_fresh_interpreter(module):
    # The authoring package root re-exports lazily; an eager root closed an import cycle
    # (programs -> authoring.manifest -> authoring root -> compiler -> contracts -> programs).
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]


def test_temporal_workflow_sources_do_not_import_application_or_provider_io():
    directory = PACKAGE / "adapters" / "temporal"
    workflows = []
    forbidden = PROVIDER_OR_TRANSPORT_SDKS - {"temporalio"}
    for path in sources(directory):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        aliases = {
            alias.asname or alias.name: f"{node.module}.{alias.name}"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
            if node.module == "temporalio"
        }
        if not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "defn"
            and isinstance(node.func.value, ast.Name)
            and aliases.get(node.func.value.id) == "temporalio.workflow"
            for node in ast.walk(tree)
        ):
            continue
        workflows.append(path)
        bad = [
            module
            for _line, module in imports(path)
            if module.split(".")[0] in forbidden
            or module.startswith(
                (
                    "mission_control.application.",
                    "mission_control.interfaces.",
                    "mission_control.bootstrap.",
                    "mission_control.adapters.postgres.",
                    "mission_control.adapters.deep_agents.",
                )
            )
        ]
        assert not bad, f"Workflow imports provider/business IO: {path}: {bad}"
    assert workflows, "No Temporal workflow definitions found by the architecture gate"


def test_distribution_and_configured_entrypoints_use_only_the_new_namespace():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["name"] == "mission-control"
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/mission_control"
    ]
    targets = list(project["project"].get("scripts", {}).values())
    configs = list(ROOT.glob("langgraph*.json")) + list((ROOT / "agent_server").glob("*.json"))
    assert configs, "Agent Server deployment configuration disappeared"
    for path in configs:
        config = json.loads(path.read_text(encoding="utf-8"))
        targets.extend(config.get("graphs", {}).values())
        for section, key in (("auth", "path"), ("http", "app")):
            if value := config.get(section, {}).get(key):
                targets.append(value)
    assert targets
    for target in targets:
        module, _separator, _symbol = target.partition(":")
        assert module.startswith("mission_control."), f"Stale configured entrypoint: {target}"
        source = PACKAGE.parent.joinpath(*module.split(".")).with_suffix(".py")
        assert source.is_file(), f"Configured entrypoint is absent from the wheel source: {target}"


def test_no_mongo_driver_can_reenter_the_runtime():
    roots = (PACKAGE, ROOT / "integrations" / "biotech" / "src" / "biotech_mission_adapters")
    failures = []
    for root in roots:
        for path in sources(root):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                if any(name.split(".")[0] in {"beanie", "pymongo", "motor"} for name in names):
                    failures.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not failures, "Mongo persistence imports returned: " + ", ".join(failures)


def test_core_does_not_install_legacy_module_aliases():
    for path in sources():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Subscript):
                continue
            if not isinstance(node.value, ast.Attribute) or node.value.attr != "modules":
                continue
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                assert node.slice.value != "app" and not node.slice.value.startswith("app."), (
                    f"Legacy module alias access: {path}:{node.lineno}"
                )


# OC-R2 (ADR-0063, design §6.1): a sealed lane binding is read only by the lane that produced it.
# Lane packages decode their own bytes; the typed contracts that define `seal`/`unseal`/
# `carried_by` live in the domain. The modules below still decode a typed binding outside a lane
# package: lane machinery that R3 relocates into its lane package (session-lane driver,
# hosted-lane and Cursor composition, Deep Agents checkpoint lineage, context packing, prerequisite
# checks and the Managed budget gate). The list may only shrink; nothing in `application/programs`,
# `adapters/temporal/workflows`, `domain/execution` (other than the defining contracts) or the
# operation activity decodes a binding.
LANE_PACKAGES = frozenset(
    {
        "deep_agents",
        "cursor",
        "claude",
        "codex",
        "anthropic_managed",
        "openai_agents",
        "remote_session",
        "agent_server",
    }
)
BINDING_CONTRACT_MODULES = frozenset(
    {
        "domain/execution/bindings.py",
        "domain/execution/contracts.py",
        "domain/execution/lanes.py",
        "domain/resolution/sealed.py",
    }
)
SEALED_BINDING_READERS_OUTSIDE_LANES = frozenset(
    {
        "adapters/github/governed_comment.py",
        "adapters/operations/runtime_ports.py",
        "adapters/postgres/cursor_costs.py",
        "adapters/temporal/hosted_lane_composition.py",
        "adapters/temporal/local_signals.py",
        "application/agentic_components/placement.py",
        "application/authoring/provider_launch.py",
        "application/context/facts.py",
        "application/context/pack_service.py",
        "application/environments/requirements.py",
        "application/execution/harness/budget_controls.py",
        "application/execution/harness/lane_turns.py",
        "application/execution/hosted_tools.py",
        "application/execution/operations/checkpoint_lineage.py",
        "application/execution/operations/operation_execution.py",
        "application/prerequisites/bootstrap_probe.py",
        "application/prerequisites/preflight.py",
        "application/recovery/run_forks.py",
        "bootstrap/hosted_readonly.py",
        "bootstrap/ingress_drainer.py",
        "bootstrap/owner_probe.py",
    }
)
_DECODES = re.compile(r"\.(?:carried_by|unseal)\(")
_RAW_PAYLOAD = re.compile(r"\.lane_binding\.payload\b")


def test_only_lane_packages_decode_a_sealed_lane_binding():
    readers = set()
    for path in sources(PACKAGE):
        relative = path.relative_to(PACKAGE).as_posix()
        parts = relative.split("/")
        if parts[0] == "adapters" and parts[1] in LANE_PACKAGES:
            continue
        if relative in BINDING_CONTRACT_MODULES:
            continue
        if _DECODES.search(path.read_text(encoding="utf-8-sig")):
            readers.add(relative)
    assert readers <= SEALED_BINDING_READERS_OUTSIDE_LANES, sorted(
        readers - SEALED_BINDING_READERS_OUTSIDE_LANES
    )
    assert readers == SEALED_BINDING_READERS_OUTSIDE_LANES, (
        "no longer a reader; drop it from the residual list",
        sorted(SEALED_BINDING_READERS_OUTSIDE_LANES - readers),
    )


def test_no_module_outside_a_lane_package_reads_raw_sealed_bytes():
    """Raw `lane_binding.payload` bytes are read only through a typed contract's `unseal`, in a
    lane package or the sealing module itself; no residual reader may parse them by hand."""

    raw = []
    for path in sources(PACKAGE):
        relative = path.relative_to(PACKAGE).as_posix()
        parts = relative.split("/")
        if parts[0] == "adapters" and parts[1] in LANE_PACKAGES:
            continue
        if relative == "domain/resolution/sealed.py":
            continue
        if _RAW_PAYLOAD.search(path.read_text(encoding="utf-8-sig")):
            raw.append(relative)
    assert not raw, raw


def test_runtime_resource_scans_have_real_inputs():
    migrations = PACKAGE / "adapters" / "postgres" / "migrations"
    assert list(migrations.glob("*.sql")), "Runtime migration source scan became empty"
    assert not (PACKAGE / "domain" / "coordinator" / "reviewed_payloads").exists()
    payloads = (
        ROOT
        / "integrations"
        / "biotech"
        / "src"
        / "biotech_mission_adapters"
        / "resources"
        / "reviewed_payloads"
    )
    assert list((payloads.parent.parent / "migrations").glob("*.sql"))
    documents = list(payloads.glob("*.json"))
    assert documents, "Reviewed capability payloads disappeared"
    for document in documents:
        assert json.loads(document.read_text(encoding="utf-8"))


# OC-R4 (design §1 application row; §4: nothing outside deployments/<app>/ and the KS binding
# package names an application): the kernel names no application, K01 binding or apply contract
# as a value. Docstrings and comments may cite them; the one place they are named as data is
# deployments/<app>/application.toml.
# Matched case-insensitively as substrings of every non-docstring string constant, f-string
# parts included (`ast.walk` visits a JoinedStr's Constant parts).
APPLICATION_NEEDLES = ("biotech", "ai-engineer", "ai_engineer", "aiengineer", "ingestion-intent")
# (path, exact value) -> why the kernel may hold it.
APPLICATION_NAME_ALLOWED = {
    (
        "src/mission_control/adapters/deep_agents/runtime_persistence_verifier.py",
        "biotech_mission_adapters",
    ): "the optional integration package's schema, listed so the checkpoint login is proven "
    "unable to reach it (FORBIDDEN_SCHEMAS); it names a package, not an application",
}


def _docstrings(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                found.add(id(body[0].value))
    return found


def test_the_kernel_names_no_application_binding_or_apply_contract():
    sources = sorted(PACKAGE.rglob("*.py"))
    assert sources, "Kernel source scan became empty"
    leaks: list[str] = []
    allowed_seen: set[tuple[str, str]] = set()
    for path in sources:
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        docstrings = _docstrings(tree)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
            ):
                continue
            lowered = node.value.lower()
            if not any(needle in lowered for needle in APPLICATION_NEEDLES):
                continue
            if (relative, node.value) in APPLICATION_NAME_ALLOWED:
                allowed_seen.add((relative, node.value))
                continue
            leaks.append(f"{relative}:{node.lineno} {node.value[:80]!r}")
    assert leaks == [], "the kernel names an application:\n" + "\n".join(leaks)
    # An allow-list entry that no longer matches is stale and must be removed.
    assert allowed_seen == set(APPLICATION_NAME_ALLOWED)


def test_the_leak_scan_sees_f_string_parts_and_titles() -> None:
    tree = ast.parse('title = f"{x} Biotech Research"\nname = "AI-Engineer app"\n')
    values = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    hits = {v for v in values if any(n in v.lower() for n in APPLICATION_NEEDLES)}
    assert hits == {" Biotech Research", "AI-Engineer app"}
