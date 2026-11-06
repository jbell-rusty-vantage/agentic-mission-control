"""Experiment loop driver (OVE-169, EXPERIMENT-LOOP-2026-11 section 5): any manifest, any chain.

Generalises `scripts/sprint_oc_w1_driver.py`: render placeholders, compile, submit, start, watch,
apply an overlay plan, and collect run/outputs/transcript evidence over the ordinary operator HTTP
surface only (the routes `missionctl` calls). A chain manifest submits once; every member run the
chain admits (the relay starts consumers) is tracked from `GET chains/{chain_id}`.

    uv run --no-sync python scripts/experiment_loop_driver.py --app ai-engineer \\
        --api http://127.0.0.1:8010 --manifest tests/fixtures/manifests/experiment-loop/<e>.yml \\
        --out .scratch/sprint-oc/experiments/iter-<n>/<e> [--pack <pack.json>] \\
        [--producer producer.fallback] [--consumer producer.fallback] \\
        [--queue-instruction <stage>:<text>] [--inject-at <stage>:<text>] \\
        [--cancel-mission <mission-key> --after <event>] [--kill-worker-after <event>] \\
        [--operator-step <event>=<text>] \\
        plan | compile | run [--timeout S] | watch | collect

Events: `started`, `stage-started:<stage>` (the stage has a transcript entry, `GET runs/{id}/
transcript?node=`; cognition points arrive only at settlement), `stage-accepted:<stage>` (an
accepted output keyed `<stage>.*`), `waiting` (an active wait, e.g. a review gate),
`link-released` (a chain link is `released`), `terminal:<key>`.

What it does itself: queue an instruction at a stage boundary (`queue_instruction`, node-keyed,
sent right after start), interrupt-and-inject once a stage has started (`interrupt_and_inject`),
cancel a member mission's run after an event (`cancel`, urgency normal), all built by missionctl's
own body builders and bound to the run's current version and generation. What it only records
(prints and writes to `overlay.jsonl` for the human or agent runner): killing the worker, and any
`--operator-step` (approve a held review, fork from a point, inject a transport fault). It never
starts or stops processes.

Secret handling as the W1 driver: the bearer comes from the owner-only token file
(`--token-file`, default `.scratch/sprint-oc/runtime/<app>/operator-token.txt`), is never printed,
and every saved body is key-scrubbed (`scripts/overnight_evidence.redact`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.overnight_evidence import export_run, redact

TERMINAL_LIFECYCLE = "completed"
PLACEHOLDER = re.compile(r"__[A-Z][A-Z0-9_]*__")
EVENT = re.compile(
    r"^(?:started|waiting|link-released|(?:stage-started|stage-accepted|terminal):[a-z0-9][a-z0-9_-]*)$"
)
ACTIONS = ("queue_instruction", "interrupt_and_inject", "cancel", "kill_worker", "operator_step")
DEFAULT_INJECTION = "Operator injection: restate your current step in one sentence, then continue."
SELF_ACTED = frozenset({"queue_instruction", "interrupt_and_inject", "cancel"})


# --- pure parts (unit-tested without network) -----------------------------------------------


TITLE_LINE = re.compile(r"^(\s*(?:-\s+)?title:\s*)(.+?)\s*$", re.MULTILINE)


def render(
    text: str, *, pack: Any | None, producer: str, consumer: str, salt: str | None = None
) -> str:
    """Substitute the fixture placeholders; refuse anything left unresolved.

    `salt` (L2-06, driver side) appends ` [salt]` to every mission title so an otherwise
    unchanged manifest compiles to a new digest and the rerun gets a fresh run.
    """

    if "__PACK__" in text:
        if pack is None:
            raise ValueError("the manifest has __PACK__; pass --pack")
        text = text.replace("__PACK__", json.dumps(pack, separators=(",", ":"), sort_keys=True))
    text = text.replace("__PRODUCER__", producer).replace("__CONSUMER__", consumer)
    unresolved = sorted(set(PLACEHOLDER.findall(text)))
    if unresolved:
        raise ValueError(f"unresolved fixture placeholders: {unresolved}")
    if salt:
        text = TITLE_LINE.sub(lambda match: f"{match.group(1)}{match.group(2)} [{salt}]", text)
    return text


@dataclass(frozen=True)
class OverlayStep:
    action: str
    trigger: str
    stage: str | None = None
    mission: str | None = None
    text: str | None = None

    @property
    def self_acted(self) -> bool:
        return self.action in SELF_ACTED


def _event(text: str) -> str:
    if not EVENT.match(text):
        raise ValueError(f"unknown event {text!r}")
    return text


def _stage_text(value: str, flag: str, *, default_text: str | None = None) -> tuple[str, str]:
    stage, sep, text = value.partition(":")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", stage):
        raise ValueError(f"{flag} needs <stage>:<text>, got {value!r}")
    if not sep or not text.strip():
        if default_text is None:
            raise ValueError(f"{flag} needs <stage>:<text>, got {value!r}")
        text = default_text
    return stage, text.strip()


def overlay_plan(options: argparse.Namespace) -> list[OverlayStep]:
    """The ordered overlay steps the options declare."""

    steps: list[OverlayStep] = []
    for value in options.queue_instruction or ():
        stage, text = _stage_text(value, "--queue-instruction")
        steps.append(OverlayStep("queue_instruction", "started", stage=stage, text=text))
    for value in options.inject_at or ():
        stage, text = _stage_text(
            value,
            "--inject-at",
            default_text=DEFAULT_INJECTION,
        )
        steps.append(
            OverlayStep("interrupt_and_inject", f"stage-started:{stage}", stage=stage, text=text)
        )
    if bool(options.cancel_mission) != bool(options.after):
        raise ValueError("--cancel-mission and --after go together")
    if options.cancel_mission:
        steps.append(OverlayStep("cancel", _event(options.after), mission=options.cancel_mission))
    if options.kill_worker_after:
        steps.append(
            OverlayStep(
                "kill_worker",
                _event(options.kill_worker_after),
                text="Kill the Mission Control worker process now (D39); restart it after the "
                "observation window and record the recovery.",
            )
        )
    for value in options.operator_step or ():
        event, sep, text = value.partition("=")
        if not sep or not text.strip():
            raise ValueError(f"--operator-step needs <event>=<text>, got {value!r}")
        steps.append(OverlayStep("operator_step", _event(event.strip()), text=text.strip()))
    return steps


@dataclass
class Observation:
    """What the public surfaces showed at one poll, across every tracked run."""

    started: set[str] = field(default_factory=set)
    stages_started: set[str] = field(default_factory=set)
    accepted: set[str] = field(default_factory=set)
    waiting: bool = False
    links: list[str] = field(default_factory=list)
    terminal: set[str] = field(default_factory=set)


def event_holds(event: str, seen: Observation) -> bool:
    kind, _, subject = event.partition(":")
    if kind == "started":
        return bool(seen.started)
    if kind == "waiting":
        return seen.waiting
    if kind == "link-released":
        return "released" in seen.links
    if kind == "stage-started":
        return subject in seen.stages_started
    if kind == "stage-accepted":
        return any(key.startswith(f"{subject}.") for key in seen.accepted)
    if kind == "terminal":
        return subject in seen.terminal
    raise ValueError(f"unknown event {event!r}")


def manifest_missions(document: dict[str, Any]) -> list[dict[str, Any]]:
    return list(document.get("missions") or [document["mission"]])


def stage_keys(document: dict[str, Any]) -> set[str]:
    keys: set[str] = set()

    def walk(node: dict[str, Any]) -> None:
        keys.add(node["key"])
        for child in node.get("nodes", ()):
            walk(child)

    for mission in manifest_missions(document):
        walk(mission["program"])
    return keys


def check_plan(steps: list[OverlayStep], document: dict[str, Any]) -> list[str]:
    """Refuse overlay steps that name a stage or mission the manifest does not have."""

    stages = stage_keys(document)
    missions = {item["key"] for item in manifest_missions(document)}
    problems = []
    for step in steps:
        if step.stage is not None and step.stage not in stages:
            problems.append(f"{step.action}: unknown stage {step.stage!r}")
        if step.mission is not None and step.mission not in missions:
            problems.append(f"{step.action}: unknown mission {step.mission!r}")
        subject = step.trigger.partition(":")[2]
        if step.trigger.startswith(("stage-started:", "stage-accepted:")) and subject not in stages:
            problems.append(f"{step.action}: trigger names unknown stage {subject!r}")
        if step.trigger.startswith("terminal:") and subject not in missions:
            problems.append(f"{step.action}: trigger names unknown mission {subject!r}")
    return problems


# --- network driver --------------------------------------------------------------------------


class Driver:
    def __init__(self, options: argparse.Namespace, steps: list[OverlayStep]) -> None:
        from mission_control.domain.authoring.manifest import load_manifest_yaml

        self.options = options
        self.app = options.app
        self.out = Path(options.out)
        self.out.mkdir(parents=True, exist_ok=True)
        pack = json.loads(Path(options.pack).read_text(encoding="utf-8")) if options.pack else None
        self.text = render(
            Path(options.manifest).read_text(encoding="utf-8"),
            pack=pack,
            producer=options.producer,
            consumer=options.consumer,
            salt=options.run_salt,
        )
        self.document = load_manifest_yaml(self.text)
        problems = check_plan(steps, self.document)
        if problems:
            raise ValueError("; ".join(problems))
        self.steps = steps
        self.done: set[int] = set()
        token_file = Path(
            options.token_file or f".scratch/sprint-oc/runtime/{self.app}/operator-token.txt"
        )
        token = token_file.read_text(encoding="utf-8").strip()
        headers = {"Authorization": f"Bearer {token}"}
        self.root = httpx.Client(
            base_url=options.api.rstrip("/"), headers=headers, timeout=options.http_timeout
        )
        self.client = httpx.Client(
            base_url=f"{options.api.rstrip('/')}/v1/applications/{self.app}",
            headers=headers,
            timeout=options.http_timeout,
        )
        self.state_path = self.out / "driver-state.json"
        self.state: dict[str, Any] = (
            json.loads(self.state_path.read_text(encoding="utf-8"))
            if self.state_path.exists()
            else {"chain_id": None, "runs": {}}
        )

    # persistence -----------------------------------------------------------------------------

    def save(self, name: str, status: int, body: Any) -> None:
        document = {
            "status": status,
            "body": redact(body),
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        path = self.out / "http" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document, indent=1), encoding="utf-8")

    def persist_state(self) -> None:
        self.state_path.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    def record(self, step: OverlayStep, outcome: dict[str, Any]) -> None:
        entry = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **asdict(step),
            **redact(outcome),
        }
        with (self.out / "overlay.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        print(json.dumps({"overlay": entry}), flush=True)

    def call(self, method: str, path: str, name: str, **kwargs: Any) -> tuple[int, Any]:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            self.save(name, 0, {"transport_error": type(exc).__name__})
            return 0, {"transport_error": type(exc).__name__}
        try:
            body: Any = response.json()
        except ValueError:
            body = {"text": response.text[:4000]}
        self.save(name, response.status_code, body)
        return response.status_code, body

    def write_rendered(self) -> None:
        (self.out / "01-authored-mission.yml").write_text(self.text, encoding="utf-8")
        digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        (self.out / "manifest.rendered.sha256").write_text(digest + "\n", encoding="utf-8")

    # lifecycle -------------------------------------------------------------------------------

    def compile(self) -> int:
        self.write_rendered()
        status, body = self.call(
            "POST", "/missions:compile", "compile", json={"manifest_yaml": self.text}
        )
        report = body.get("report", body) if isinstance(body, dict) else {}
        summary = {k: report.get(k) for k in ("ok", "manifest_digest", "blockers", "warnings")}
        print(json.dumps({"status": status, **summary}, indent=1)[:6000])
        return 0 if status == 200 and report.get("ok") else 1

    def submit(self) -> int:
        self.write_rendered()
        request_id = str(uuid.uuid4())
        status, body = self.call(
            "POST",
            "/missions:submit",
            "submit",
            json={"manifest_yaml": self.text, "request_id": request_id},
            headers={"Idempotency-Key": request_id},
        )
        if status not in (200, 201) or not isinstance(body, dict):
            print(json.dumps({"status": status, "body": redact(body)})[:4000])
            return 1
        self.state["chain_id"] = body.get("chain_id")
        for mission in body.get("missions", []):
            if mission.get("run_id"):
                self.state["runs"][mission["mission_key"]] = {
                    "run_id": mission["run_id"],
                    "started": False,
                }
        self.persist_state()
        print(json.dumps({"status": status, "state": self.state}, indent=1))
        return 0

    def start_pending(self) -> int:
        failures = 0
        for key, run in self.state["runs"].items():
            if run["started"] or run.get("relay"):
                continue
            status, _ = self.call(
                "POST", "/missions:start", f"start.{key}", json={"run_id": run["run_id"]}
            )
            run["started"] = status in (200, 202)
            failures += not run["started"]
            print(json.dumps({"start": key, "status": status}), flush=True)
        self.persist_state()
        return int(bool(failures))

    def observe(self) -> Observation:
        seen = Observation()
        chain_id = self.state.get("chain_id")
        if chain_id:
            status, body = self.call("GET", f"/chains/{chain_id}", "chain.poll")
            if status == 200 and isinstance(body, dict):
                seen.links = [link.get("state", "") for link in body["chain"]["links"]]
                for member in body.get("members", []):
                    if member.get("run_key") and member["mission_key"] not in self.state["runs"]:
                        # Admitted and started by the chain relay, never by this driver.
                        self.state["runs"][member["mission_key"]] = {
                            "run_id": member["run_key"],
                            "started": True,
                            "relay": True,
                        }
                        self.persist_state()
        stages = stage_keys(self.document)
        for key, run in self.state["runs"].items():
            run_id = quote(run["run_id"], safe="")
            status, body = self.call("GET", f"/runs/{run_id}/inspection", f"poll.{key}")
            if status != 200 or not isinstance(body, dict):
                continue
            if body.get("lifecycle") not in (None, "pending"):
                seen.started.add(key)
            if body.get("lifecycle") == TERMINAL_LIFECYCLE:
                seen.terminal.add(key)
            if (body.get("projection") or {}).get("active_waits"):
                seen.waiting = True
            status, outputs = self.call("GET", f"/runs/{run_id}/outputs", f"outputs.{key}")
            if status == 200 and isinstance(outputs, dict):
                seen.accepted |= {row["obligation_key"] for row in outputs.get("accepted", [])}
            for step in self.steps:
                stage = step.trigger.partition(":")[2]
                if step.trigger.startswith("stage-started:") and stage in stages:
                    # Loop iter-1 L1-10: cognition points are written only at settlement, so
                    # the earliest public signal of a running stage is its transcript entries.
                    status, page = self.call(
                        "GET",
                        f"/runs/{run_id}/transcript",
                        f"transcript.{key}.{stage}",
                        params={"node": stage, "limit": 1, "format": "json"},
                    )
                    if status == 200 and isinstance(page, dict) and page.get("entries"):
                        seen.stages_started.add(stage)
        return seen

    def act(self, step: OverlayStep) -> None:
        if not step.self_acted:
            self.record(step, {"performed": False, "runner_action_required": step.text})
            return
        from mission_control.interfaces.cli.main import (
            MissionClient,
            cancel_command_body,
            queue_command_body,
        )

        client = MissionClient(self.root, self.app)
        if step.action == "cancel":
            run = self.state["runs"].get(step.mission or "")
            if run is None:
                self.record(step, {"performed": False, "error": "mission has no tracked run"})
                return
            args = argparse.Namespace(
                run_id=run["run_id"], urgency="normal", reason="experiment overlay", request_id=None
            )
            body = cancel_command_body(client, args)
        else:
            # The stage's run: a stage key belongs to one tracked mission's program.
            run = self._run_of_stage(step.stage or "")
            spec = self.out / "overlay" / f"{len(self.done):02d}-{step.action}.json"
            spec.parent.mkdir(parents=True, exist_ok=True)
            spec.write_text(
                json.dumps({"text": step.text, "node_key": step.stage}), encoding="utf-8"
            )
            args = argparse.Namespace(
                run_id=run,
                file=str(spec),
                action="inject" if step.action == "interrupt_and_inject" else "queue",
                add_context=False,
                boundary="next_turn",
                node_key=step.stage,
                expand="auto",
                reason="experiment overlay",
                request_id=None,
            )
            body = queue_command_body(client, args)
        response = client.command(body["target"]["id"], body)
        try:
            result: Any = response.json()
        except ValueError:
            result = {"text": response.text[:2000]}
        self.save(f"overlay.{len(self.done):02d}.{step.action}", response.status_code, result)
        self.record(step, {"performed": True, "http": response.status_code, "kind": body["kind"]})

    def _run_of_stage(self, stage: str) -> str:
        for mission in manifest_missions(self.document):
            if stage in stage_keys({"mission": mission}):
                run = self.state["runs"].get(mission["key"])
                if run is not None:
                    return str(run["run_id"])
        raise ValueError(f"no tracked run owns stage {stage!r}")

    def watch(self, timeout: float) -> int:
        deadline = time.monotonic() + timeout
        last: Any = None
        missions = {item["key"] for item in manifest_missions(self.document)}
        while time.monotonic() < deadline:
            seen = self.observe()
            for index, step in enumerate(self.steps):
                if index in self.done or not event_holds(step.trigger, seen):
                    continue
                try:
                    self.act(step)
                except (ValueError, KeyError, httpx.HTTPError) as exc:
                    self.record(step, {"performed": False, "error": f"{type(exc).__name__}: {exc}"})
                self.done.add(index)
            summary = (sorted(seen.started), sorted(seen.terminal), seen.waiting, seen.links)
            if summary != last:
                print(json.dumps({"observed": summary}), flush=True)
                last = summary
            if (
                seen.terminal
                and seen.terminal >= set(self.state["runs"])
                and (not self.state.get("chain_id") or seen.terminal >= missions)
            ):
                return self.collect()
            time.sleep(self.options.poll)
        print(json.dumps({"timeout": timeout}))
        self.collect()
        return 2

    def collect(self) -> int:
        gaps: dict[str, list[str]] = {}
        for key, run in self.state["runs"].items():
            gaps[key] = export_run(self.client, run["run_id"], self.out / f"run-{key}")
        if self.state.get("chain_id"):
            self.call("GET", f"/chains/{self.state['chain_id']}", "chain.final")
        pending = [asdict(step) for index, step in enumerate(self.steps) if index not in self.done]
        result = {"runs": self.state["runs"], "evidence_gaps": gaps, "overlay_not_fired": pending}
        (self.out / "collect.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(json.dumps(result, indent=1))
        return int(any(gaps.values()))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--app", required=True, choices=("ai-engineer", "biotech"))
    parser.add_argument("--api", default="http://127.0.0.1:8010")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pack")
    parser.add_argument("--producer", default="producer.fallback")
    parser.add_argument("--consumer", default="producer.fallback")
    parser.add_argument("--token-file")
    parser.add_argument("--run-salt", help="append [SALT] to every mission title (fresh run)")
    parser.add_argument("--http-timeout", type=float, default=120.0)
    parser.add_argument("--poll", type=float, default=10.0)
    parser.add_argument("--queue-instruction", action="append", metavar="STAGE:TEXT")
    parser.add_argument("--inject-at", action="append", metavar="STAGE[:TEXT]")
    parser.add_argument("--cancel-mission", metavar="MISSION_KEY")
    parser.add_argument("--after", metavar="EVENT")
    parser.add_argument("--kill-worker-after", metavar="EVENT")
    parser.add_argument("--operator-step", action="append", metavar="EVENT=TEXT")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="print the rendered overlay plan; no network")
    sub.add_parser("compile")
    run = sub.add_parser("run", help="submit, start, watch with overlays, collect")
    run.add_argument("--timeout", type=float, default=3600.0)
    watch = sub.add_parser("watch", help="resume watching the runs in --out/driver-state.json")
    watch.add_argument("--timeout", type=float, default=3600.0)
    sub.add_parser("collect")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    options = parser.parse_args(argv)
    try:
        steps = overlay_plan(options)
    except ValueError as exc:
        parser.error(str(exc))
    if options.command == "plan":
        from mission_control.domain.authoring.manifest import load_manifest_yaml

        text = Path(options.manifest).read_text(encoding="utf-8")
        problems = check_plan(steps, load_manifest_yaml(PLACEHOLDER.sub("x", text)))
        print(
            json.dumps(
                {
                    "steps": [asdict(step) | {"self_acted": step.self_acted} for step in steps],
                    "problems": problems,
                },
                indent=1,
            )
        )
        return int(bool(problems))
    driver = Driver(options, steps)
    if options.command == "compile":
        return driver.compile()
    if options.command == "run":
        if driver.compile() or driver.submit() or driver.start_pending():
            driver.collect()
            return 1
        return driver.watch(options.timeout)
    if options.command == "watch":
        return driver.watch(options.timeout)
    return driver.collect()


if __name__ == "__main__":
    sys.exit(main())
