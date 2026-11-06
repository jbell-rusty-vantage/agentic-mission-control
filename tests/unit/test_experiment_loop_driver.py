"""OVE-169 experiment loop driver: argument parsing, overlay plan, event matching and rendering,
offline (no network, no provider, no database)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from mission_control.domain.authoring.manifest import load_manifest_yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "experiment_loop_driver", ROOT / "scripts/experiment_loop_driver.py"
)
assert SPEC is not None and SPEC.loader is not None
driver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = driver  # dataclasses resolve their module by name
SPEC.loader.exec_module(driver)
LOOP = ROOT / "tests/fixtures/manifests/experiment-loop"
BASE = ["--app", "ai-engineer", "--out", "unused"]


def options(*extra: str, manifest: str = "e2-stagegraph-fanout-join.mission.yml"):
    return driver.build_parser().parse_args(
        [*BASE, "--manifest", str(LOOP / manifest), *extra, "plan"]
    )


def document(name: str) -> dict:
    text = (LOOP / name).read_text(encoding="utf-8")
    return load_manifest_yaml(driver.render(text, pack={}, producer="p", consumer="c"))


def test_defaults_are_the_cheap_rows_and_loopback_api() -> None:
    parsed = options()
    assert (parsed.producer, parsed.consumer) == ("producer.fallback", "producer.fallback")
    assert parsed.api == "http://127.0.0.1:8010"
    assert driver.overlay_plan(parsed) == []


def test_overlay_plan_orders_and_types_every_step() -> None:
    steps = driver.overlay_plan(
        options(
            "--queue-instruction",
            "synthesize:Name each binding's tier first.",
            "--inject-at",
            "collect_a",
            "--kill-worker-after",
            "stage-started:collect_b",
            "--operator-step",
            "waiting=Approve the review task in the packet.",
        )
    )
    assert [(s.action, s.trigger, s.stage) for s in steps] == [
        ("queue_instruction", "started", "synthesize"),
        ("interrupt_and_inject", "stage-started:collect_a", "collect_a"),
        ("kill_worker", "stage-started:collect_b", None),
        ("operator_step", "waiting", None),
    ]
    assert steps[0].text == "Name each binding's tier first."
    assert steps[1].text  # a default injection text
    assert [s.self_acted for s in steps] == [True, True, False, False]
    assert driver.check_plan(steps, document("e2-stagegraph-fanout-join.mission.yml")) == []


def test_cancel_mission_needs_an_event_and_a_known_mission() -> None:
    with pytest.raises(ValueError, match="go together"):
        driver.overlay_plan(options("--cancel-mission", "e4-evidence"))
    steps = driver.overlay_plan(
        options(
            "--cancel-mission",
            "e4-evidence",
            "--after",
            "link-released",
            manifest="e4-linked-chain.mission.yml",
        )
    )
    assert [(s.action, s.mission, s.trigger) for s in steps] == [
        ("cancel", "e4-evidence", "link-released")
    ]
    chain = document("e4-linked-chain.mission.yml")
    assert driver.check_plan(steps, chain) == []
    wrong = [driver.OverlayStep("cancel", "terminal:nope", mission="nope")]
    assert driver.check_plan(wrong, chain) == [
        "cancel: unknown mission 'nope'",
        "cancel: trigger names unknown mission 'nope'",
    ]


@pytest.mark.parametrize(
    "bad", ["--queue-instruction=synthesize", "--queue-instruction=Bad Stage:x", "--after=soon"]
)
def test_malformed_overlays_are_refused(bad: str) -> None:
    extra = [bad]
    if bad.startswith("--after"):
        extra = ["--cancel-mission", "e4-evidence", bad]
    with pytest.raises(ValueError):
        driver.overlay_plan(options(*extra))


def test_check_plan_refuses_unknown_stages() -> None:
    steps = driver.overlay_plan(options("--inject-at", "nonexistent:hi"))
    assert driver.check_plan(steps, document("e2-stagegraph-fanout-join.mission.yml")) == [
        "interrupt_and_inject: unknown stage 'nonexistent'",
        "interrupt_and_inject: trigger names unknown stage 'nonexistent'",
    ]


def test_events_match_only_what_the_surfaces_showed() -> None:
    seen = driver.Observation(
        started={"e4-evidence"},
        stages_started={"collect"},
        accepted={"collect.notes"},
        links=["armed"],
    )
    assert driver.event_holds("started", seen)
    assert driver.event_holds("stage-started:collect", seen)
    assert not driver.event_holds("stage-started:map", seen)
    assert driver.event_holds("stage-accepted:collect", seen)
    assert not driver.event_holds("stage-accepted:col", seen)  # exact stage prefix only
    assert not driver.event_holds("link-released", seen)
    assert not driver.event_holds("waiting", seen)
    assert not driver.event_holds("terminal:e4-evidence", seen)
    seen.links.append("released")
    seen.terminal.add("e4-evidence")
    assert driver.event_holds("link-released", seen)
    assert driver.event_holds("terminal:e4-evidence", seen)


def test_render_substitutes_and_refuses_leftovers() -> None:
    text = (LOOP / "e1-goal-loop-report.mission.yml").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="--pack"):
        driver.render(text, pack=None, producer="producer.default", consumer="x")
    rendered = driver.render(
        text, pack={"reportId": "r", "b": 1}, producer="producer.default", consumer="x"
    )
    assert '{"b":1,"reportId":"r"}' in rendered and "profile: producer.default" in rendered
    with pytest.raises(ValueError, match="__OTHER__"):
        driver.render("a: __OTHER__", pack=None, producer="p", consumer="c")


def test_stage_keys_cover_nested_bodies_and_every_chain_member() -> None:
    assert {"research", "compare", "prepare", "review"} <= driver.stage_keys(
        document("e5-nested-goal-in-graph.mission.yml")
    )
    assert {"collect", "map", "review"} <= driver.stage_keys(
        document("e4-linked-chain.mission.yml")
    )


def test_plan_command_prints_the_plan_without_network(capsys: pytest.CaptureFixture) -> None:
    code = driver.main(
        [
            *BASE,
            "--manifest",
            str(LOOP / "e3-stagegraph-route-revisit.mission.yml"),
            "--inject-at",
            "check:Restate the source count.",
            "plan",
        ]
    )
    printed = json.loads(capsys.readouterr().out)
    assert code == 0 and printed["problems"] == []
    assert printed["steps"][0]["action"] == "interrupt_and_inject"
    assert printed["steps"][0]["self_acted"] is True


def test_a_queued_instruction_is_sent_through_missionctl_body_and_no_token_is_written(
    tmp_path: Path,
) -> None:
    import httpx

    secret = "operator-token-must-not-leak"
    token = tmp_path / "token.txt"
    token.write_text(secret, encoding="utf-8")
    out = tmp_path / "out"
    parsed = driver.build_parser().parse_args(
        [
            "--app",
            "ai-engineer",
            "--out",
            str(out),
            "--manifest",
            str(LOOP / "e2-stagegraph-fanout-join.mission.yml"),
            "--token-file",
            str(token),
            "--queue-instruction",
            "synthesize:Name each binding's tier first.",
            "run",
        ]
    )
    steps = driver.overlay_plan(parsed)
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {secret}"
        if request.method == "GET":
            return httpx.Response(200, json={"version": 7, "execution_generation": 1})
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"accepted": True})

    instance = driver.Driver(parsed, steps)
    instance.root = httpx.Client(
        base_url="http://127.0.0.1:8010",
        headers={"Authorization": f"Bearer {secret}"},
        transport=httpx.MockTransport(handler),
    )
    instance.state["runs"] = {"e2-stagegraph-fanout-join": {"run_id": "run-1", "started": True}}
    instance.act(steps[0])
    (body,) = sent
    assert (body["kind"], body["expected_version"], body["target"]) == (
        "queue_instruction",
        7,
        {"kind": "run", "id": "run-1"},
    )
    assert body["payload"]["node_key"] == "synthesize"
    assert body["payload"]["boundary"] == "next_turn"
    assert body["payload"]["content"] == {"text": "Name each binding's tier first."}
    for path in out.rglob("*"):
        if path.is_file():
            assert secret not in path.read_text(encoding="utf-8")
    (entry,) = [json.loads(line) for line in (out / "overlay.jsonl").read_text().splitlines()]
    assert entry["performed"] is True and entry["http"] == 200


@pytest.mark.parametrize(
    ("transcript_entries", "point_entries", "expected"),
    [
        ([{"node": "collect_a"}], [], True),  # running: transcript has the node, no point yet
        ([], [{"point_id": "p-1"}], False),  # points alone never trigger
        ([], [], False),
    ],
)
def test_stage_started_triggers_from_the_transcript_node_filter(
    tmp_path: Path, transcript_entries: list, point_entries: list, expected: bool
) -> None:
    """Loop iter-1 L1-10: cognition points are written only at settlement, so a point-based
    `stage-started:<stage>` fired after the stage finished; the trigger is the transcript's
    node filter, the earliest public signal of a running stage."""

    import httpx

    token = tmp_path / "token.txt"
    token.write_text("t", encoding="utf-8")
    parsed = driver.build_parser().parse_args(
        [
            "--app",
            "ai-engineer",
            "--out",
            str(tmp_path / "out"),
            "--manifest",
            str(LOOP / "e2-stagegraph-fanout-join.mission.yml"),
            "--token-file",
            str(token),
            "--inject-at",
            "collect_a:Check the quotes again.",
            "run",
        ]
    )
    steps = driver.overlay_plan(parsed)
    asked: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        asked.append((request.url.path, params))
        if request.url.path.endswith("/transcript"):
            return httpx.Response(200, json={"entries": transcript_entries})
        if request.url.path.endswith("/points"):
            return httpx.Response(200, json={"entries": point_entries})
        if request.url.path.endswith("/inspection"):
            return httpx.Response(200, json={"lifecycle": "active", "projection": {}})
        return httpx.Response(200, json={"accepted": []})

    instance = driver.Driver(parsed, steps)
    instance.client = httpx.Client(
        base_url="http://127.0.0.1:8010", transport=httpx.MockTransport(handler)
    )
    instance.state["runs"] = {"e2-stagegraph-fanout-join": {"run_id": "run-1", "started": True}}
    seen = instance.observe()
    assert ("collect_a" in seen.stages_started) is expected
    assert driver.event_holds("stage-started:collect_a", seen) is expected
    (query,) = [params for path, params in asked if path.endswith("/runs/run-1/transcript")]
    assert query["node"] == "collect_a" and query["format"] == "json"


def test_run_salt_retitles_every_mission_so_a_rerun_gets_a_fresh_run() -> None:
    """L2-06 (driver side): an unchanged manifest re-submitted reuses its old run; a salt
    changes each mission title (and nothing else) so the compiled digest and run differ."""

    for name in ("e2-stagegraph-fanout-join.mission.yml", "e4-linked-chain.mission.yml"):
        text = (LOOP / name).read_text(encoding="utf-8")
        plain = driver.render(text, pack={}, producer="p", consumer="c")
        salted = driver.render(text, pack={}, producer="p", consumer="c", salt="iter3-a")
        missions_plain = load_manifest_yaml(plain)
        missions_salted = load_manifest_yaml(salted)
        assert missions_plain != missions_salted
        titles = [line for line in salted.splitlines() if line.strip().startswith("title:")]
        assert titles and all(line.rstrip().endswith("[iter3-a]") for line in titles)
        assert salted.replace(" [iter3-a]", "") == plain
    assert options("--run-salt", "x").run_salt == "x"
