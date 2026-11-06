"""Explicit opt-in driver for the owner's bounded paid Qualia fixtures."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.fixtures.qualia_stagegraph import run_pilot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--vendor", choices=["firecrawl", "tavily"], default="firecrawl")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--full", action="store_true")
    mode.add_argument("--native-probe", action="store_true")
    parser.add_argument("--resume-source", help="Retained local source attempt; fork only")
    parser.add_argument("--resume-run-id", help="Exact completed source run ID")
    parser.add_argument("--authorized-budget-usd", type=int, required=True)
    args = parser.parse_args()
    if args.authorized_budget_usd != 100:
        parser.error("this packet requires the recorded owner authorization of USD 100")
    if bool(args.resume_source) != bool(args.resume_run_id) or (
        args.resume_source and not args.full
    ):
        parser.error("retained fork requires --full, --resume-source and --resume-run-id")
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else asyncio.new_event_loop
    print(
        json.dumps(
            asyncio.run(
                run_pilot(
                    attempt=args.attempt,
                    vendor=args.vendor,
                    full=args.full,
                    native_probe=args.native_probe,
                    resume_source=args.resume_source,
                    resume_run_id=args.resume_run_id,
                ),
                loop_factory=loop_factory,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
