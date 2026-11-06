"""Run the bounded local foundation proof matrix, serially, with durable exit evidence.

Run with the MC virtualenv Python. Requires an explicit loopback PostgreSQL admin DSN,
built canonical BKS/KS packages, and existing local dependencies. Never loads .env files,
calls paid providers, launches a mission, installs into persistent application targets,
or promotes a sprint gate.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
KS = ROOT.parent / "knowledge-services"


def run(out: Path, dsn_variable: str, timeout: int = 420) -> int:
    dsn = os.environ.get(dsn_variable, "")
    if urlsplit(dsn).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("explicit loopback PostgreSQL admin DSN required")
    if out.exists():
        raise ValueError("proof output directory must be fresh")
    pnpm = shutil.which("corepack")
    if pnpm is None:
        raise ValueError("corepack is required for the existing KS dependency environment")
    out.mkdir(parents=True)
    env = {
        key: value
        for key, value in os.environ.items()
        if not any(
            term in key.upper()
            for term in (
                "API_KEY",
                "SUPABASE",
                "NEO4J",
                "DATABASE_URL",
                "DIRECT_URL",
                "POSTGRES_URL",
            )
        )
    }
    env.update(
        MISSION_CONTROL_TEST_ADMIN_DSN=dsn,
        KNOWLEDGE_DB_CONTRACT_ADMIN_DSN=dsn,
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
    )
    pytest = [sys.executable, "-m", "pytest", "-q", "--override-ini", "addopts=", "--tb=short"]
    steps = []
    for app in ("ai-engineer", "biotech"):
        context = out / f"context-{app}"
        steps.append(
            (
                f"context-{app}",
                ROOT,
                [
                    sys.executable,
                    "scripts/report_source_context.py",
                    "--profile",
                    app,
                    "--out",
                    str(context),
                ],
            )
        )
        for shape in ("repair", "transfer"):
            steps.append(
                (
                    f"render-{app}-{shape}",
                    ROOT,
                    [
                        sys.executable,
                        "scripts/report_source_foundation.py",
                        "--app",
                        app,
                        "--shape",
                        shape,
                        "--context",
                        str(context),
                        "--out",
                        str(out / f"fixture-{app}-{shape}"),
                    ],
                )
            )
    steps.extend(
        [
            (
                "tool-and-fixture-units",
                ROOT,
                [
                    *pytest,
                    "tests/unit/knowledge/test_submission_foundation.py",
                    "tests/unit/knowledge/test_report_registration.py",
                    "tests/unit/test_report_source_context.py",
                    "tests/unit/test_report_source_foundation.py",
                    "tests/unit/test_report_source_proof.py",
                ],
            ),
            (
                "scripted-deep-agents",
                ROOT,
                [
                    *pytest,
                    "tests/integration/deep_agents/test_report_source_context.py",
                    "tests/integration/deep_agents/test_wi02_dependent_stage_transfer.py",
                ],
            ),
            (
                "postgres-output-contracts",
                ROOT,
                [*pytest, "tests/integration/postgres/test_output_contracts_postgres.py"],
            ),
            (
                "joined-mc-ks-consumer",
                ROOT,
                [*pytest, "tests/integration/deep_agents/test_report_source_real_service.py"],
            ),
            (
                "real-ks-service",
                KS / "apps/verification-executor",
                [
                    pnpm,
                    "pnpm",
                    "exec",
                    "vitest",
                    "run",
                    "src/knowledge-operation/report-source-foundation.integration.test.ts",
                    "--maxWorkers=1",
                ],
            ),
        ]
    )
    matrix = {
        "schema": "report-source-foundation.proof.v1",
        "qualified": False,
        "steps": [],
        "pins": {},
        "unrun": [
            "paid model/search qualification",
            "full MC-to-KS foundation mission",
            "native application",
            "W1/W2 release",
        ],
    }
    for name, repo in (("MC", ROOT), ("KS", KS)):
        matrix["pins"][name] = {
            "head": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True
            ).strip(),
            "dirty": bool(
                subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=repo, text=True
                ).strip()
            ),
        }
    failed = False
    for name, cwd, command in steps:
        if failed:
            matrix["steps"].append({"name": name, "status": "unrun"})
            continue
        log_path = out / f"{name}.log"
        with log_path.open("w", encoding="utf-8") as log:
            try:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                )
                code = result.returncode
            except subprocess.TimeoutExpired:
                log.write("\nTimed out; no pass claimed.\n")
                code = 124
            except OSError as error:
                log.write(f"\nCommand could not start: {type(error).__name__}\n")
                code = 127
        failed = code != 0
        matrix["steps"].append(
            {
                "name": name,
                "status": "failed" if failed else "passed",
                "exit_code": code,
                "command": command,
                "cwd": str(cwd),
                "log": log_path.name,
            }
        )
        (out / "matrix.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    (out / "matrix.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    return int(failed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--admin-dsn-env", default="MISSION_CONTROL_TEST_ADMIN_DSN")
    parser.add_argument("--timeout", type=int, default=420)
    args = parser.parse_args()
    raise SystemExit(run(args.out.resolve(), args.admin_dsn_env, args.timeout))
