"""MO47 recorded recipes over real scoped HTTP, PG17 and Temporal.

Deterministic cognition is a provider fixture. Runtime run/notification receipts stay
in ignored .scratch logs; the committed test records procedure, never private receipts.
"""

import json
from pathlib import Path

import pytest
from tests.acceptance.mission_control.test_wake_channels import finished, missionctl
from tests.fixtures.scoped_api_stack import prepare_run, scoped_stack, serve_loopback

pytestmark = pytest.mark.common_db
EXAMPLES = tuple(
    sorted((Path(__file__).resolve().parents[2] / "fixtures/manifests/watchers").glob("*.yml"))
)


async def test_declare_watchers_recipe_structural_compile_session() -> None:
    for example in EXAMPLES:
        compiler = missionctl(
            "http://unused.invalid",
            "fixture-unused",
            "mission",
            "compile",
            str(example),
            "--offline",
            "--json",
        )
        out, err = await finished(compiler, 60)
        assert compiler.returncode == 0, err or out
        report = json.loads(out)
        assert not report["blockers"]
        print(
            json.dumps(
                {
                    "recipe": "declare-watchers",
                    "example": example.name,
                    "mode": "offline_structure",
                    "blockers": 0,
                }
            ),
            flush=True,
        )


async def test_launch_then_wait_supervise_many_inspect_on_wake_and_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with (
        scoped_stack(tmp_path, monkeypatch) as stack,
        serve_loopback(stack.application) as url,
    ):
        tracked = []
        for _ in range(2):
            run_id, launch = await prepare_run(stack, "GoalDirected")
            response = await stack.http.post(
                f"/v1/applications/biotech/runs/{run_id}/launch", json=launch
            )
            assert response.status_code == 202, response.text
            inbox = response.json()["coordinator_inbox"]["subscription_id"]
            tracked.append((run_id, inbox))
            print(
                json.dumps({"recipe": "launch-then-wait", "run": run_id, "inbox": inbox}),
                flush=True,
            )
        assert len({inbox for _, inbox in tracked}) == 2
        seen = set()
        for run_id, inbox in tracked:
            waiter = missionctl(
                url,
                stack.token,
                "wait",
                "--run",
                run_id,
                "--kinds",
                "terminal_result,blocked,review_required,failed",
                "--wait",
                "120",
            )
            out, err = await finished(waiter, 150)
            assert waiter.returncode == 0, err
            (notification,) = [json.loads(line) for line in out.splitlines()]
            assert notification["kind"] == "terminal_result"
            assert notification["notification_id"] not in seen
            seen.add(notification["notification_id"])
            inspector = missionctl(url, stack.token, "run", "inspect", run_id, "--json")
            inspected, err = await finished(inspector, 60)
            assert inspector.returncode == 0, err
            state = json.loads(inspected)
            assert state["lifecycle"] == "completed"
            assert state["execution_outcome"] == "completed"
            print(
                json.dumps(
                    {
                        "recipe": "inspect-on-wake",
                        "run": run_id,
                        "lifecycle": state["lifecycle"],
                        "notification": notification["notification_id"],
                    }
                ),
                flush=True,
            )
            replay = missionctl(
                url,
                stack.token,
                "wait",
                "--inbox",
                inbox,
                "--kinds",
                "terminal_result",
                "--wait",
                "10",
            )
            repeated, err = await finished(replay, 30)
            assert replay.returncode == 0, err
            assert (
                json.loads(repeated.splitlines()[0])["notification_id"]
                == notification["notification_id"]
            )
            ack = missionctl(
                url, stack.token, "inbox", "ack", inbox, "--id", notification["notification_id"]
            )
            acked, err = await finished(ack, 30)
            assert ack.returncode == 0, err
            assert notification["notification_id"] in json.loads(acked)["acknowledged"]
            quiet = missionctl(
                url,
                stack.token,
                "wait",
                "--inbox",
                inbox,
                "--kinds",
                "terminal_result",
                "--wait",
                "1",
            )
            await finished(quiet, 30)
            assert quiet.returncode == 6
            print(
                json.dumps(
                    {
                        "recipe": "supervise-many",
                        "run": run_id,
                        "handled": True,
                        "pending_terminal": False,
                    }
                ),
                flush=True,
            )
