"""Sprint OC W1 driver (OVE-169 / WI-06): render, compile, submit, start, wait and collect.

Drives one W1/W2 fixture through the ordinary operator HTTP surface (the same routes `missionctl
mission compile|submit|start` call), never through test seams. Secret-safe: the operator bearer is
read from the owner-only token file (`scripts/sprint_oc_deployment_file.py --app <app> token`) and
never printed; responses are saved to the ignored evidence directory after a key-name scrub.

    uv run --no-sync python <worktree>/scripts/sprint_oc_w1_driver.py --app ai-engineer \
        --api http://127.0.0.1:8010 --manifest <fixture.yml> --pack <pack.json> \
        --evidence .scratch/sprint-oc/evidence/w1/ai-engineer/<label> compile
    ... submit            (admits the run; prints run_id)
    ... start --run RUN   (explicit start)
    ... wait --run RUN --timeout 1800
    ... collect --run RUN (run, outputs, transcript, settlement inspection)
    ... validate --run RUN (persisted acceptance checks; not independent qualification)

Native W1 runs use --minimum-iterations 2. The omitted-report negative probe uses
--expected-unfulfilled root.report; ordinary positive fixtures must not use this switch.
W2 accepts --consumer to render the distinct consumer profile.

The fixture's `__PACK__` placeholder is replaced by the frozen KS evidence pack
(`scripts/sprint_oc_w1_pack.mjs`), compact JSON, before compile; the rendered manifest and its
SHA-256 are saved beside the responses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml

# Support direct script invocation and importlib-based fixture tests alike.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.overnight_evidence import export_run, redact

TERMINAL_LIFECYCLE = "completed"


def scrub(value: Any) -> Any:
    return redact(value)


class Driver:
    def __init__(self, options: argparse.Namespace) -> None:
        self.app = options.app
        self.evidence = Path(options.evidence)
        self.evidence.mkdir(parents=True, exist_ok=True)
        token_file = Path(
            options.token_file or f".scratch/sprint-oc/runtime/{self.app}/operator-token.txt"
        )
        token = token_file.read_text(encoding="utf-8").strip()
        self.client = httpx.Client(
            base_url=f"{options.api.rstrip('/')}/v1/applications/{self.app}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=options.http_timeout,
        )
        self.options = options
        self.root = httpx.Client(
            base_url=options.api.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=options.http_timeout,
        )
        deployment = json.loads(
            Path(f".scratch/sprint-oc/runtime/{self.app}/deployment.json").read_text(
                encoding="utf-8"
            )
        )
        auth = deployment["applications"][0]["authentication"]
        self.scope = "mc/{}/{}/{}".format(
            auth["binding"]["installation_id"], self.app, auth["grants"][0]["tenant_ids"][0]
        )

    def save(self, name: str, status: int, body: Any) -> None:
        document = {
            "status": status,
            "body": scrub(body),
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (self.evidence / f"{name}.json").write_text(
            json.dumps(document, indent=1), encoding="utf-8"
        )

    def call(
        self, method: str, path: str, name: str, *, root: bool = False, **kwargs: Any
    ) -> tuple[int, Any]:
        client = self.root if root else self.client
        try:
            response = client.request(method, path, **kwargs)
        except httpx.RequestError as exc:
            self.save(name, 0, {"transport_error": type(exc).__name__})
            return 0, {"transport_error": type(exc).__name__}
        try:
            body: Any = response.json()
        except ValueError:
            body = {"text": response.text[:4000]}
        self.save(name, response.status_code, body)
        return response.status_code, body

    def rendered(self) -> str:
        text = Path(self.options.manifest).read_text(encoding="utf-8")
        if "__PACK__" in text:
            pack = json.loads(Path(self.options.pack).read_text(encoding="utf-8"))
            text = text.replace("__PACK__", json.dumps(pack, separators=(",", ":"), sort_keys=True))
        text = text.replace("__PRODUCER__", self.options.producer)
        text = text.replace("__CONSUMER__", self.options.consumer)
        unresolved = sorted(set(re.findall(r"__[A-Z][A-Z0-9_]*__", text)))
        if unresolved:
            raise ValueError(f"unresolved fixture placeholders: {unresolved}")
        out = self.evidence / "manifest.rendered.yml"
        out.write_text(text, encoding="utf-8")
        (self.evidence / "01-authored-mission.yml").write_text(text, encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        (self.evidence / "manifest.rendered.sha256").write_text(digest + "\n", encoding="utf-8")
        return text

    def compile(self) -> int:
        status, body = self.call(
            "POST", "/missions:compile", "compile", json={"manifest_yaml": self.rendered()}
        )
        report = body.get("report", body) if isinstance(body, dict) else {}
        summary = {k: report.get(k) for k in ("ok", "manifest_digest", "blockers", "warnings")}
        print(json.dumps({"status": status, **summary}, indent=1)[:6000])
        return 0 if status == 200 and report.get("ok") else 1

    def submit(self) -> int:
        request_id = str(uuid.uuid4())
        status, body = self.call(
            "POST",
            "/missions:submit",
            "submit",
            json={"manifest_yaml": self.rendered(), "request_id": request_id},
            headers={"Idempotency-Key": request_id},
        )
        print(
            json.dumps({"status": status, "request_id": request_id, "body": scrub(body)}, indent=1)[
                :4000
            ]
        )
        return 0 if status in (200, 201) else 1

    def start(self, run: str) -> int:
        status, body = self.call("POST", "/missions:start", "start", json={"run_id": run})
        print(json.dumps({"status": status, "body": scrub(body)}, indent=1)[:4000])
        return 0 if status in (200, 202) else 1

    def wait(self, run: str, timeout: float) -> int:
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            status, body = self.call("GET", f"/runs/{run}/inspection", "run.poll")
            if status != 200 or not isinstance(body, dict) or body.get("run_id") != run:
                self.collect(run)
                return 1
            state = (body.get("lifecycle"), body.get("phase"), body.get("execution_outcome"))
            if state != last:
                print(json.dumps({"http": status, "state": state}), flush=True)
                last = state
            if body.get("lifecycle") == TERMINAL_LIFECYCLE:
                # Terminal execution alone never qualifies a fixture, including negative probes.
                self.collect(run)
                return self.validate(run)
            time.sleep(self.options.poll)
        print(json.dumps({"timeout": timeout, "state": last}))
        self.collect(run)
        return 2

    def collect(self, run: str) -> int:
        gaps = export_run(self.client, run, self.evidence)
        print(json.dumps({"collected": run, "evidence_gaps": gaps}))
        return int(bool(gaps))

    def validate(self, run: str) -> int:
        manifest = yaml.safe_load(Path(self.options.manifest).read_text(encoding="utf-8"))
        program = manifest["mission"]["program"]
        family = program["behavior"]
        minimum_iterations = self.options.minimum_iterations
        if family == "goal_loop" and any(
            row.get("name") == "native_receipt" for row in program.get("outputs", [])
        ):
            minimum_iterations = max(2, minimum_iterations)
        endpoint = "evidence" if family == "goal_loop" else "completion-evidence"
        documents: dict[str, Any] = {}
        failures = []
        for name in ("inspection", "outputs", endpoint):
            status, body = self.call("GET", f"/runs/{run}/{name}", f"validate.{name}")
            if status != 200 or not isinstance(body, dict) or body.get("run_id") != run:
                failures.append(f"{name}: unavailable or wrong run")
            else:
                documents[name] = body
        if not failures and family == "stage_graph":
            details: list[dict[str, Any]] = []
            for plan in documents["outputs"].get("transfer_plans", []):
                if plan.get("receiver_position") != "consume":
                    continue
                status, detail = self.call(
                    "GET", f"/transfer-plans/{plan['plan_id']}", f"validate.plan.{len(details)}"
                )
                if status != 200 or not isinstance(detail, dict):
                    failures.append("consumer transfer detail unavailable")
                else:
                    details.append(detail)
            documents["consumer_plans"] = details
        if not failures:
            failures.extend(
                check_acceptance(
                    program,
                    documents,
                    expected_unfulfilled=self.options.expected_unfulfilled,
                    minimum_iterations=minimum_iterations,
                )
            )
        result = {
            "run_id": run,
            "acceptance_checks_passed": not failures,
            "expected_unfulfilled": self.options.expected_unfulfilled,
            "failures": failures,
            "qualified": False,
            "proof_limits": [
                "independent evidence review still required",
                "native readback and exact receiving bytes require separate proof",
            ],
        }
        self.save("acceptance", 200, result)
        print(json.dumps(result, indent=1))
        return 1 if failures else 0


def check_acceptance(
    program: dict[str, Any],
    documents: dict[str, Any],
    *,
    expected_unfulfilled: str | None = None,
    minimum_iterations: int = 1,
) -> list[str]:
    """Check persisted host decisions, never infer acceptance from execution completion.

    This bounded check does not certify model quality, native readback or delivered bytes.
    """
    failures = []
    inspection = documents["inspection"]
    if inspection.get("lifecycle") != "completed":
        failures.append("run is not terminal")
    outputs = documents["outputs"]
    fulfillment = outputs.get("fulfillment") or {}
    decisions = {row["obligation_key"]: row for row in fulfillment.get("decisions", [])}
    accepted = {row["obligation_key"] for row in outputs.get("accepted", [])}
    goal = program["behavior"] == "goal_loop"
    verifications = []
    if goal:
        result = documents["evidence"].get("result", {})
        record = result.get("record") or {}
        details = record.get("family_result") or {}
        if (
            result.get("status") != "recorded"
            or record.get("run_id") != inspection.get("run_id")
            or details.get("family") != "GoalDirected"
        ):
            failures.append("persisted GoalDirected result not recorded for this run")
        verifications = details.get("verification_results", [])
        if not verifications:
            failures.append("persisted goal verification chronology missing")
        for verification in verifications:
            identity = verification.get("executor_identity", {}).get("iteration", {})
            if (
                identity.get("run_id") != inspection.get("run_id")
                or not isinstance(identity.get("goal_iteration"), int)
                or not verification.get("verification_id")
                or not verification.get("verifier_operation_identity")
            ):
                failures.append("goal verification identity missing or wrong run")
        validations = []
    else:
        page = documents["completion-evidence"]
        if page.get("status") != "recorded" or not page.get("decisions"):
            failures.append("completion evidence not recorded")
        if page.get("next_after_family_version") is not None:
            failures.append("completion evidence is paginated; full chronology not collected")
        validations = page.get("decisions", [])
    if expected_unfulfilled:
        row = decisions.get(expected_unfulfilled, {})
        if row.get("enforcement") != "required" or row.get("disposition") != "unfulfilled":
            failures.append("expected required-output omission not proven")
        if expected_unfulfilled in accepted:
            failures.append("omitted output was accepted")
        refused = (
            (
                bool(verifications)
                and verifications[-1].get("decision") == "rejected"
                and f"output:{expected_unfulfilled}"
                in verifications[-1].get("unmet_obligations", [])
            )
            if goal
            else any(d.get("validation", {}).get("status") == "unsatisfied" for d in validations)
        )
        if not refused:
            failures.append("negative completion refusal not recorded")
        return failures
    if inspection.get("execution_outcome") != "completed":
        failures.append("positive fixture execution did not complete successfully")
    nodes = [program] if goal else program["nodes"]
    required = {
        f"{node['key']}.{out['name']}"
        for node in nodes
        for out in node.get("outputs", [])
        if out["enforcement"] == "required"
    }
    if not required:
        failures.append("fixture declares no required output")
    for key in sorted(required):
        if key not in accepted:
            failures.append(f"{key}: no accepted revision")
        if decisions.get(key, {}).get("disposition") != "fulfilled":
            failures.append(f"{key}: no current fulfilled decision")
    accepted_completion = (
        (
            bool(verifications)
            and verifications[-1].get("decision") == "accepted"
            and details.get("final_verifier_action") == "accepted"
        )
        if goal
        else any(d.get("validation", {}).get("status") == "satisfied" for d in validations)
    )
    if not accepted_completion:
        failures.append("accepted completion decision not recorded")
    if not goal:
        heads = [
            row["revision"]["revision_id"]
            for row in outputs.get("accepted", [])
            if row["obligation_key"] == "produce.report"
        ]
        plans = documents.get("consumer_plans", [])
        if not plans:
            failures.append("consumer sealed transfer evidence missing")
        for detail in plans:
            sources = detail.get("plan", {}).get("exact_sources", [])
            selected = [row for row in sources if row.get("source_kind") == "produced_output"]
            if not selected or any(
                row.get("binding") != "report"
                or row.get("source_ref") not in heads
                or row.get("admission") != "accepted"
                for row in selected
            ):
                failures.append("consumer selection differs from exact accepted producer report")
            if not any(row.get("result") == "ready" for row in detail.get("receipts", [])):
                failures.append("consumer has no ready delivery receipt")
    if goal:
        iterations = {
            v.get("executor_identity", {}).get("iteration", {}).get("goal_iteration")
            for v in verifications
        }
        iterations.discard(None)
        if len(iterations) < minimum_iterations:
            failures.append("minimum distinct verified iterations not reached")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--app", required=True, choices=("ai-engineer", "biotech"))
    parser.add_argument("--api", required=True)
    parser.add_argument("--manifest")
    parser.add_argument("--pack")
    parser.add_argument(
        "--producer",
        default="producer.default",
        help="models.toml row (dry run: producer.fallback)",
    )
    parser.add_argument("--consumer", default="producer.fallback")
    parser.add_argument("--expected-unfulfilled", help="negative probe: exact omitted required key")
    parser.add_argument("--minimum-iterations", type=int, default=1)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--token-file")
    parser.add_argument("--http-timeout", type=float, default=120.0)
    parser.add_argument("--poll", type=float, default=10.0)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("compile")
    sub.add_parser("submit")
    for name in ("start", "wait", "collect", "validate"):
        command = sub.add_parser(name)
        command.add_argument("--run", required=True)
        if name == "wait":
            command.add_argument("--timeout", type=float, default=1800.0)
    options = parser.parse_args()
    if options.command in {"compile", "submit", "wait", "validate"} and not options.manifest:
        parser.error("--manifest is required for rendering and acceptance checks")
    if options.minimum_iterations < 1:
        parser.error("--minimum-iterations must be positive")
    driver = Driver(options)
    if options.command == "compile":
        return driver.compile()
    if options.command == "submit":
        return driver.submit()
    if options.command == "start":
        return driver.start(options.run)
    if options.command == "wait":
        return driver.wait(options.run, options.timeout)
    if options.command == "validate":
        return driver.validate(options.run)
    return driver.collect(options.run)


if __name__ == "__main__":
    sys.exit(main())
