"""FX-TR-REMOTE (TRACING-PROPOSAL §P9, WP-TR-5): the remote saver on the production offline
stack.

The signed scoped stack (`tests/fixtures/scoped_api_stack.py`) with its LangGraph saver DSN
pointed at `tests/fixtures/tcp_proxy.SaverProxy` (`scoped_stack(..., saver_proxy=)`), so both
the workers and the API open the saver through the proxy while the common Mission Control
database stays direct. `MISSION_CONTROL_POINTS_WALK_BUDGET_MS=50` is set before the stack
starts. A plain Stage Graph run (draft, declared wait, review) is launched with the proxy
transparent; the delay is then raised so cognition still completes but every points walk
(several saver round trips per checkpoint) exceeds the budget:

- settlement still completes and at least one unit's result point carries
  `channel_facts.points_status == "incomplete"` (with `points_walked`);
- the run inspection's `points_incomplete` names those units, and `missionctl run inspect`
  prints the same list over real loopback HTTP;
- with the delay removed, `missionctl run points RUN --reconcile` reports `points_added > 0`
  and no `saver_unreachable` unit; afterwards `points_incomplete` is empty and no result
  point reads incomplete any more;
- with the proxy cut, `state-as-of` on a root result point answers `503 state_unavailable`
  (`reason` in `saver_unreachable` / `saver_not_served`) while `missionctl run transcript RUN
  --by step --full` still exits 0 with output (the Transcript reads the common database only).

Evidence: `.scratch/tracing-stage-1/fx-tr-remote.json`, written before the assertions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.acceptance.mission_control.test_cognition_points import (
    BASE,
    all_points,
    at_wait,
    completed,
    is_root,
    launch,
    satisfy_wait,
)
from tests.acceptance.mission_control.test_tracing import (
    _write_evidence,
    cli,
    find_keys,
    parse_cli_json,
)
from tests.fixtures.scoped_api_stack import (
    ScopedStack,
    inspect,
    scoped_stack,
    serve_loopback,
    until,
)
from tests.fixtures.stage2_outputs import write_outputs
from tests.fixtures.tcp_proxy import SaverProxy

pytestmark = pytest.mark.common_db

WALK_BUDGET_MS = "50"
SAVER_DELAY_SECONDS = 0.15
UNAVAILABLE_REASONS = {"saver_unreachable", "saver_not_served"}


def points_status(point: dict[str, Any]) -> str | None:
    """`channel_facts.points_status` of a point (absent on a complete walk)."""

    facts = point.get("channel_facts") or {}
    value = facts.get("points_status")
    return None if value is None else str(value)


def unit_key(point: dict[str, Any]) -> str:
    return str(point["coordinate"]["unit_key"])


async def root_result_points(stack: ScopedStack, run_id: str) -> list[dict[str, Any]]:
    """Every unit's root result point (the settlement's point) of the run."""

    return [item for item in await all_points(stack, run_id, role="result") if is_root(item)]


def first_value(document: dict[str, Any] | None, name: str) -> Any:
    """The first `name` anywhere in a CLI document (top level first)."""

    if document is None:
        return None
    if name in document:
        return document[name]
    found = find_keys(document, name)
    return found[0] if found else None


@pytest.mark.asyncio
async def test_fx_tr_remote(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISSION_CONTROL_POINTS_WALK_BUDGET_MS", WALK_BUDGET_MS)
    proxy = SaverProxy()
    failures: list[str] = []
    evidence: dict[str, Any] = {
        "fixture": "FX-TR-REMOTE",
        "walk_budget_ms": int(WALK_BUDGET_MS),
        "saver_delay_seconds": SAVER_DELAY_SECONDS,
    }
    async with (
        scoped_stack(tmp_path, monkeypatch, saver_proxy=proxy) as stack,
        serve_loopback(stack.application) as url,
    ):
        evidence["proxy_port"] = proxy.port
        run_id = await launch(stack, "StageGraph")
        evidence["run_id"] = run_id
        # From here every saver round trip (the workers' and the API's) costs the delay:
        # cognition still completes, every points walk exceeds the budget.
        proxy.delay_seconds = SAVER_DELAY_SECONDS
        await until(lambda: at_wait(stack, run_id), seconds=600)
        await satisfy_wait(stack, run_id)
        await until(lambda: completed(stack, run_id), seconds=600)

        # 1. Settlement completed with an incomplete points walk on at least one unit.
        results = await root_result_points(stack, run_id)
        statuses = {
            unit_key(item): {
                "points_status": points_status(item),
                "points_walked": (item.get("channel_facts") or {}).get("points_walked"),
                "point_id": item["point_id"],
            }
            for item in results
        }
        evidence["result_points_before"] = statuses
        incomplete_units = sorted(
            key for key, facts in statuses.items() if facts["points_status"] == "incomplete"
        )
        evidence["incomplete_units"] = incomplete_units
        if not results:
            failures.append("the run recorded no root result points")
        if not incomplete_units:
            failures.append(
                f"no unit's result point reads points_status=incomplete under the delay: {statuses}"
            )
        for key in incomplete_units:
            walked = statuses[key]["points_walked"]
            if not isinstance(walked, int):
                failures.append(f"{key}: points_walked is not an int: {walked!r}")

        # 2. The inspection names them, and the CLI prints the same list.
        state = await inspect(stack, run_id)
        inspected = state.get("points_incomplete")
        evidence["inspection_points_incomplete"] = inspected
        if not isinstance(inspected, list):
            failures.append(f"run inspection has no points_incomplete list: {inspected!r}")
        elif sorted(inspected) != incomplete_units:
            failures.append(
                f"inspection points_incomplete {sorted(inspected)} != result points' "
                f"{incomplete_units}"
            )
        code, out, err = await cli(url, stack.token, "run", "inspect", run_id)
        document = parse_cli_json(out)
        cli_incomplete = first_value(document, "points_incomplete")
        evidence["cli_inspect"] = {"exit": code, "points_incomplete": cli_incomplete}
        if code != 0:
            failures.append(f"missionctl run inspect exited {code}: {err.strip()[-400:]}")
        elif document is None:
            failures.append(f"missionctl run inspect printed no JSON: {out[:400]!r}")
        elif not isinstance(cli_incomplete, list) or sorted(cli_incomplete) != incomplete_units:
            failures.append(
                f"missionctl run inspect points_incomplete {cli_incomplete!r} != {incomplete_units}"
            )

        # 3. With the delay removed, --reconcile completes the points.
        proxy.delay_seconds = 0.0
        code, out, err = await cli(url, stack.token, "run", "points", run_id, "--reconcile")
        report = parse_cli_json(out)
        points_added = first_value(report, "points_added")
        saver_unreachable = first_value(report, "saver_unreachable")
        evidence["cli_reconcile"] = {
            "exit": code,
            "points_added": points_added,
            "saver_unreachable": saver_unreachable,
            "report": report,
        }
        if code != 0:
            failures.append(
                f"missionctl run points --reconcile exited {code}: {err.strip()[-400:]}"
            )
        elif report is None:
            failures.append(f"missionctl run points --reconcile printed no JSON: {out[:400]!r}")
        else:
            if not isinstance(points_added, int) or points_added <= 0:
                failures.append(f"reconcile points_added is not > 0: {points_added!r}")
            if saver_unreachable not in ([], None) and saver_unreachable != ():
                failures.append(f"reconcile reports saver_unreachable units: {saver_unreachable!r}")
            if saver_unreachable is None:
                failures.append("reconcile report has no saver_unreachable list")
        state = await inspect(stack, run_id)
        evidence["inspection_points_incomplete_after"] = state.get("points_incomplete")
        if state.get("points_incomplete") != []:
            failures.append(
                f"points_incomplete after reconcile is {state.get('points_incomplete')!r}, not []"
            )
        results_after = await root_result_points(stack, run_id)
        statuses_after = {unit_key(item): points_status(item) for item in results_after}
        evidence["result_points_after"] = statuses_after
        still = sorted(key for key, value in statuses_after.items() if value == "incomplete")
        if still:
            failures.append(f"result points still read incomplete after reconcile: {still}")
        if set(statuses_after) != set(statuses):
            failures.append(
                f"reconcile changed the set of units with a result point: "
                f"{sorted(statuses)} -> {sorted(statuses_after)}"
            )

        # 4. Saver cut: state-as-of is a typed 503; the transcript still answers.
        proxy.set_closed(True)
        evidence["proxy_closed"] = {
            "served": proxy.connections_served,
            "refused_before_reads": proxy.connections_refused,
        }
        probe = results_after[0] if results_after else None
        if probe is None:
            failures.append("no root result point to probe state-as-of with the saver cut")
        else:
            response = await stack.http.get(
                f"{BASE}/{run_id}/points/{probe['point_id']}/state-as-of"
            )
            body: Any
            try:
                body = response.json()
            except ValueError:
                body = response.text
            evidence["state_as_of_cut"] = {"status": response.status_code, "body": body}
            detail = body.get("detail") if isinstance(body, dict) else None
            if response.status_code != 503:
                failures.append(
                    f"state-as-of with the saver cut answered {response.status_code}, not 503"
                )
            elif not isinstance(detail, dict) or detail.get("code") != "state_unavailable":
                failures.append(f"state-as-of 503 detail is not state_unavailable: {body!r}")
            elif detail.get("reason") not in UNAVAILABLE_REASONS:
                failures.append(
                    f"state-as-of reason {detail.get('reason')!r} not in {UNAVAILABLE_REASONS}"
                )
        code, out, err = await cli(
            url, stack.token, "run", "transcript", run_id, "--by", "step", "--full"
        )
        evidence["cli_transcript_cut"] = {
            "exit": code,
            "stdout_chars": len(out),
            "stdout_head": out[:400],
            "stderr_tail": err.strip()[-400:],
        }
        if code != 0:
            failures.append(
                f"missionctl run transcript --by step --full exited {code} with the saver cut: "
                f"{err.strip()[-400:]}"
            )
        elif not out.strip():
            failures.append("missionctl run transcript --by step --full printed nothing")
        evidence["proxy_refused_total"] = proxy.connections_refused
        # Tracing Stage 2 (§4a): the owner's files for this T0 run, read with the saver cut.
        evidence["outputs"] = await write_outputs(
            stack,
            url,
            fixture="fx-tr-remote-t0",
            run_id=run_id,
            group="stage",
            mission={
                "family": "StageGraph (draft, review), saver behind a delaying proxy",
                "walk_budget_ms": int(WALK_BUDGET_MS),
                "saver_delay_seconds": SAVER_DELAY_SECONDS,
            },
            extra_files={"evidence.json": evidence},
        )

    evidence["failures"] = failures
    path = _write_evidence("fx-tr-remote.json", evidence)
    assert not failures, (failures, path)
