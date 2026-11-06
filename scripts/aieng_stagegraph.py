"""Explicit opt-in driver for the owner's bounded paid AI Engineer StageGraph fixtures.

Loads only named credentials (never printed): OpenAI/Firecrawl/Tavily from this repository's
.env, Context7 from Knowledge Services' .env, a GitHub token from the gh CLI. The disposable
loopback PostgreSQL admin DSN comes from the verified local container identity.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.fixtures.aieng_stagegraph import (  # noqa: E402
    EVIDENCE,
    MODEL_LIMIT_USD,
    SESSION_CEILING_USD,
    WEB_LIMIT_USD,
    run_aieng,
)

CONTAINER = "mc-overnight-20261029-pg17"


def disposable_admin_dsn() -> str:
    (target,) = json.loads(
        subprocess.run(
            ["docker", "inspect", CONTAINER], capture_output=True, text=True, check=True
        ).stdout
    )
    ports = target["NetworkSettings"]["Ports"]["5432/tcp"] or []
    if (
        target["Name"] != f"/{CONTAINER}"
        or target["Config"]["Image"] != "pgvector/pgvector:pg17"
        or not target["State"]["Running"]
        or not any(p["HostIp"] == "127.0.0.1" and p["HostPort"] == "55434" for p in ports)
    ):
        raise SystemExit("Disposable PostgreSQL identity unavailable")
    password = next(
        item.split("=", 1)[1]
        for item in target["Config"]["Env"]
        if item.startswith("POSTGRES_PASSWORD=")
    )
    return f"postgresql://postgres:{quote(password, safe='')}@127.0.0.1:55434/postgres"


def load_credentials() -> None:
    from dotenv import dotenv_values

    mission = dotenv_values(ROOT / ".env")
    knowledge = dotenv_values(ROOT.parent / "knowledge-services/.env")
    for name in ("OPENAI_API_KEY", "FIRECRAWL_API_KEY", "TAVILY_API_KEY"):
        os.environ[name] = str(mission.get(name) or "").strip()
    os.environ["CONTEXT7_API_KEY"] = str(knowledge.get("CONTEXT7_API_KEY") or "").strip()
    os.environ["GITHUB_TOKEN"] = subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True, check=True
    ).stdout.strip()
    missing = [
        n for n in ("OPENAI_API_KEY", "FIRECRAWL_API_KEY", "CONTEXT7_API_KEY") if not os.environ[n]
    ]
    if missing:
        raise SystemExit("Missing named credentials: " + ", ".join(missing))
    os.environ["MISSION_CONTROL_TEST_ADMIN_DSN"] = disposable_admin_dsn()
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Driver flags. Defaults preserve the recorded USD60 packet (evidence root, USD24 model and
    USD30 web caps); another run names its own evidence root and caps, whose sum must stay
    within the explicitly authorized budget."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--vendor", choices=["firecrawl", "tavily"], default="firecrawl")
    parser.add_argument("--resume-source", help="Retained local source attempt; fork only")
    parser.add_argument("--resume-run-id", help="Exact completed source run ID")
    parser.add_argument("--authorized-budget-usd", type=float, required=True)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=EVIDENCE,
        help="Ignored evidence directory holding the budget ledgers and attempts",
    )
    parser.add_argument("--model-cap-usd", type=float, default=MODEL_LIMIT_USD)
    parser.add_argument("--web-cap-usd", type=float, default=WEB_LIMIT_USD)
    args = parser.parse_args(argv)
    args.evidence_root = (
        args.evidence_root if args.evidence_root.is_absolute() else ROOT / args.evidence_root
    ).resolve()
    defaults = (
        args.evidence_root == EVIDENCE.resolve()
        and args.model_cap_usd == MODEL_LIMIT_USD
        and args.web_cap_usd == WEB_LIMIT_USD
    )
    if defaults and args.authorized_budget_usd != SESSION_CEILING_USD:
        parser.error("this packet requires the recorded owner authorization of USD 60")
    if args.model_cap_usd <= 0 or args.web_cap_usd <= 0:
        parser.error("model and web caps must be positive")
    if args.model_cap_usd + args.web_cap_usd > args.authorized_budget_usd:
        parser.error("model cap plus web cap exceeds the authorized budget")
    if not args.evidence_root.is_relative_to(ROOT / ".scratch"):
        parser.error("evidence root must be inside the ignored .scratch directory")
    if bool(args.resume_source) != bool(args.resume_run_id):
        parser.error("retained fork requires --resume-source and --resume-run-id")
    return args


def main() -> None:
    args = parse_args()
    load_credentials()
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
    result = asyncio.run(
        run_aieng(
            attempt=args.attempt,
            vendor=args.vendor,
            resume_source=args.resume_source,
            resume_run_id=args.resume_run_id,
            evidence_root=args.evidence_root,
            model_cap_usd=args.model_cap_usd,
            web_cap_usd=args.web_cap_usd,
        ),
        loop_factory=loop_factory,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
