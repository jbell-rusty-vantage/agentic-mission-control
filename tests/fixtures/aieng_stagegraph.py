"""Real paid AI Engineer Deep Agents StageGraph fixtures over scoped Mission Control.

Frontier-model / agent-orchestration research with GitHub, arXiv, Context7, Firecrawl and
Tavily sources, independent KS verification and AIDB native ingestion into a DISPOSABLE
loopback AI Engineer database. Never the AI Engineer graph. Run only through the explicit
CLI driver with the owner's finite budget; captured sources and transcripts are retained.

Provenance slice 2 (OVE-204): Mission Control owns the producer key. :func:`knowledge_host`
generates it, publishes its JWKS for the KS host (which adds only its own evaluator key) and the
lane signs every producer-side K01 credential with it (``mission_invocation`` origins).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from tests.fixtures.qualia_runtime import SpendLedger
from tests.fixtures.qualia_web_tools import WebCallBudget

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / ".scratch/aieng-stagegraph-2026-10-31"
APPLICATION = "ai-engineer"
# The KS component installation in the disposable AIDB database (singleton; never reinstalled).
KS_INSTALLATION = "0192a4f0-0000-7000-8000-0000000a1e11"
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:54822/postgres"
MODEL_LIMIT_USD = 24.0
WEB_LIMIT_USD = 30.0
SESSION_CEILING_USD = 60.0
WEB_RESERVATION_PER_CALL_USD = 0.2
# K01 credential issuer and audience Mission Control mints for and the KS host verifies.
KNOWLEDGE_ISSUER = "mission-control"
KNOWLEDGE_AUDIENCE = "knowledge-services-executor"


def database_url() -> str:
    url = os.environ.get("AIENG_FIXTURE_DATABASE_URL", DEFAULT_DATABASE_URL)
    if urlsplit(url).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("AI Engineer fixture writes only to a disposable loopback database")
    return url


def ledgers(
    evidence_root: Path = EVIDENCE,
    *,
    model_cap_usd: float = MODEL_LIMIT_USD,
    web_cap_usd: float = WEB_LIMIT_USD,
) -> tuple[SpendLedger, WebCallBudget]:
    """Shared append-only ledgers under ``evidence_root/budget``.

    Default root and caps: USD24 models + USD30 web reservations + USD6 margin = USD60, with
    the first allowance (USD30 models / USD24 and 120 web calls) retained as an explicit prior
    policy (amendments only rebalance within the owner's USD60 and never reset spend). Any
    other root or cap is a fresh ledger with its own caps and no inherited prior policy.
    """
    if model_cap_usd <= 0 or not WEB_RESERVATION_PER_CALL_USD <= web_cap_usd <= 35:
        raise ValueError("model cap must be positive and web cap within USD0.2..35")
    budget = evidence_root / "budget"
    inherited = (
        evidence_root.resolve() == EVIDENCE.resolve()
        and model_cap_usd == MODEL_LIMIT_USD
        and web_cap_usd == WEB_LIMIT_USD
    )
    max_calls = min(140, round(web_cap_usd / WEB_RESERVATION_PER_CALL_USD))
    return (
        SpendLedger(budget, limit=model_cap_usd),
        WebCallBudget(
            ledger_path=budget / "web-usage.jsonl",
            max_calls=max_calls,
            max_calls_per_tool=min(40, max_calls),
            max_reserved_usd=web_cap_usd,
            reservation_per_call_usd=WEB_RESERVATION_PER_CALL_USD,
            prior_limit_policies=(
                {
                    "max_calls": 120,
                    "max_calls_per_tool": 40,
                    "max_reserved_usd": "24",
                    "reservation_per_call_usd": "0.2",
                },
            )
            if inherited
            else (),
        ),
    )


def knowledge_origin(invocation: str) -> dict[str, Any]:
    from tests.fixtures.mission_control_common_db import canonical_scope

    from mission_control.application.knowledge.access import instant
    from mission_control.contracts.knowledge_protocol import Origin

    tenant = canonical_scope(application_id=APPLICATION).split("/")[3]
    return Origin(
        kind="standalone",
        installationId=KS_INSTALLATION,
        applicationId=APPLICATION,
        tenantId=tenant,
        issuer=KNOWLEDGE_ISSUER,
        subject="mission-control-runtime",
        mission=None,
        recoveryAuthorityRef=None,
        invocationId=invocation,
        authenticatedAt=instant(datetime.now(UTC)),
    ).model_dump(mode="json")


def write_issuer_key(root: Path) -> tuple[Path, Path, str]:
    """Mission Control's disposable Ed25519 issuer key: private JWK (MC only) and public JWKS."""
    from mission_control.adapters.knowledge.credentials import (
        generate_signing_key,
        write_jwks,
        write_private_jwk,
    )

    key = generate_signing_key(f"mc-aieng-{secrets.token_hex(4)}")
    key_path, jwks_path = root / "mc-knowledge-private.jwk.json", root / "knowledge-jwks.json"
    write_private_jwk(key, key_path)
    write_jwks(jwks_path, key)
    return key_path, jwks_path, key.kid


def host_config(root: Path, jwks_path: Path) -> dict[str, Any]:
    from tests.fixtures.aieng_knowledge import AIDB_WORKSPACE

    return {
        "origin": knowledge_origin("aieng-stagegraph-startup"),
        "jwksPath": str(jwks_path),
        "issuer": KNOWLEDGE_ISSUER,
        "audience": KNOWLEDGE_AUDIENCE,
        "evidenceRoot": str(root),
        "workspaceDir": str(AIDB_WORKSPACE),
        # Unset: the host expects the AIDB workspace's head (set to accept an advanced head).
        "migrationHead": os.environ.get("AIENG_FIXTURE_MIGRATION_HEAD") or None,
    }


@asynccontextmanager
async def knowledge_host(root: Path) -> Any:
    """The AI Engineer KS fixture host over the disposable AIDB database (JSON lines on stdio).

    Yields ``(process, ready, key_path)``: ``key_path`` is Mission Control's own private JWK
    (the host never sees it); ``ready["jwks"]`` names MC's kid and the host evaluator kid."""
    from tests.integration.deep_agents.test_report_source_real_service import response

    key_path, jwks_path, kid = write_issuer_key(root)
    config = root / "knowledge-host.json"
    config.write_text(json.dumps(host_config(root, jwks_path)), encoding="utf-8")
    environment = {**os.environ, "AIENG_FIXTURE_DATABASE_URL": database_url()}
    with (root / "knowledge-host.log").open("wb") as log:
        process = await asyncio.to_thread(
            subprocess.Popen,
            [
                "node",
                "--import",
                "tsx",
                "src/knowledge-operation/tests/aieng-fixture-host.ts",
                str(config),
            ],
            cwd=ROOT.parent / "knowledge-services/apps/verification-executor",
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=log,
        )
        try:
            ready = await response(process)
            assert ready["ready"], ready
            assert ready["jwks"]["missionControlKids"] == [kid], ready
            assert ready["issuer"] == KNOWLEDGE_ISSUER and ready["audience"] == KNOWLEDGE_AUDIENCE
            yield process, ready, key_path
        finally:
            if process.poll() is None:
                process.terminate()
                await asyncio.to_thread(process.wait, 15)


RECORD_SCHEMA = {
    "type": "object",
    "required": ["summary", "source_urls", "limitations", "details"],
    "properties": {
        "summary": {"type": "string", "minLength": 10},
        "source_urls": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "limitations": {"type": "array", "items": {"type": "string"}},
        "details": {"type": "object"},
    },
    "additionalProperties": False,
}
REQUIRED_OBLIGATIONS = frozenset(
    {
        "discover.discovery",
        "frameworks.framework",
        "literature.appraisal",
        "synthesize.report",
        "verify.verification",
        "ingest.ingestion",
        "finalize.summary",
    }
)
DEPENDENT_STAGES = frozenset(
    {"frameworks", "literature", "synthesize", "verify", "ingest", "finalize"}
)


async def run_aieng(
    *,
    attempt: str,
    vendor: str = "firecrawl",
    resume_source: str | None = None,
    resume_run_id: str | None = None,
    evidence_root: Path = EVIDENCE,
    model_cap_usd: float = MODEL_LIMIT_USD,
    web_cap_usd: float = WEB_LIMIT_USD,
) -> dict[str, Any]:
    """Full source graph with live controls, then the recorded-point Tavily fork of literature."""
    import pytest
    from tests.acceptance.mission_control.test_overnight_stagegraph import run_stagegraph_fixture
    from tests.fixtures.aieng_full_manifest import (
        INTERRUPTED,
        QUEUED,
        full_manifest,
        stage_tool_names,
    )
    from tests.fixtures.aieng_knowledge import build_aieng_knowledge_tools
    from tests.fixtures.aieng_web_tools import build_aieng_web_tools
    from tests.fixtures.mission_control_common_db import AI_ENGINEER_INSTALLATION_ID
    from tests.fixtures.mission_control_production_stack import open_postgres_production_stack
    from tests.fixtures.overnight_stagegraph_evidence import export_stagegraph
    from tests.fixtures.qualia_control_api import qualia_control_api
    from tests.fixtures.qualia_interventions import Interventions
    from tests.fixtures.qualia_proof import verify_capabilities, verify_transfers
    from tests.fixtures.qualia_runtime import live_components, live_technical_binding, model_profile
    from tests.fixtures.qualia_scenarios import controller, fork_from_completed_stage
    from tests.fixtures.qualia_stagegraph import build_bindings, lifecycle_for
    from tests.fixtures.rrm009_production_stack import technical_binding
    from tests.integration.temporal.test_manifest_launch_production import host_pins

    from mission_control.adapters.postgres.knowledge.output_contracts import (
        PostgresOutputContractStore,
    )
    from mission_control.adapters.postgres.run_control.run_control_repository import (
        PostgresRunControlRepository,
    )
    from mission_control.bootstrap.composition import compose_knowledge_lane
    from mission_control.bootstrap.settings import get_settings

    evidence_root = evidence_root.resolve()  # noqa: ASYNC240 -- before any I/O starts
    destination = (evidence_root / attempt).resolve()
    if destination.parent != evidence_root:
        raise ValueError("attempt must be a direct child of the ignored evidence directory")
    if bool(resume_source) != bool(resume_run_id):
        raise ValueError("retained source and exact source run ID must be supplied together")
    destination.mkdir(parents=True, exist_ok=False)
    runtime_root, retained_database = destination, None
    if resume_source is not None:
        from tests.fixtures.qualia_recovery import require_completed_source, retained_runtime

        runtime_root = (evidence_root / resume_source).resolve(strict=True)
        if runtime_root.parent != evidence_root or runtime_root == destination:
            raise ValueError("retained source must be another fixture attempt")
        retained_database = retained_runtime(runtime_root, APPLICATION)
        await require_completed_source(retained_database[0], resume_run_id)
        (destination / "retained-source.json").write_text(
            json.dumps({"source_root": str(runtime_root), "source_run_id": resume_run_id}),
            encoding="utf-8",
        )
    ledger, web_budget = ledgers(
        evidence_root, model_cap_usd=model_cap_usd, web_cap_usd=web_cap_usd
    )
    real_key = os.environ["OPENAI_API_KEY"]
    profile = model_profile(prefix="aieng")
    technical = live_technical_binding(technical_binding(), profile)
    web = build_aieng_web_tools(
        destination / "web",
        environment=os.environ,
        skill_custody_root=runtime_root / "web" if resume_source is not None else None,
        budget=web_budget,
        node_executable=Path("C:/Program Files/nodejs/node.exe"),
        browser_entrypoint=Path(os.environ["APPDATA"])
        / "npm/node_modules/agent-browser/bin/agent-browser.js",
    )
    bindings_path = destination / "launch-bindings.json"
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setenv("MISSION_CONTROL_APPLICATION", APPLICATION)
        monkeypatch.setenv("MISSION_CONTROL_E2E_KEEP_DATABASE", "1")
        get_settings.cache_clear()
        async with knowledge_host(destination) as (process, ready, key_path):
            from types import SimpleNamespace

            knowledge = build_aieng_knowledge_tools(
                process,
                ready=ready,
                evidence_dir=destination / "web",
                ledger=ledger,
                timeout_seconds=420,
            )
            interventions = Interventions(positions=frozenset({QUEUED, INTERRUPTED}))
            definition, component, binding, tool = interventions.capability()
            extra = SimpleNamespace(
                definitions={**knowledge.definitions, definition.logical_id: definition},
                bindings={**knowledge.bindings, definition.logical_id: binding},
                registry_tools={**knowledge.registry_tools, component.ref.digest: tool},
                components=[*knowledge.components, component],
            )
            components = live_components(
                technical,
                ledger,
                tools={**web.registry_tools, **extra.registry_tools},
                skills=web.registry_skill_bundles,
            )
            bindings = build_bindings(technical, web, extra, profile_key="aieng.sol")
            bindings_path.write_text(bindings.model_dump_json(indent=2), encoding="utf-8")

            async def lane(settings: Any, pool: Any) -> Any:
                settings.knowledge_binding_url = ready["url"]
                settings.knowledge_binding_audience = ready["audience"]
                settings.knowledge_issuer = ready["issuer"]
                settings.knowledge_issuer_key_file = key_path
                settings.knowledge_describe_tenant = ready["roles"]["producer"]["tenantId"]
                settings.knowledge_component_installation_id = KS_INSTALLATION
                settings.knowledge_disposable_installation = True
                settings.mc_judge_openai_api_key = None
                settings.mc_auditor_anthropic_api_key = None
                composed = await compose_knowledge_lane(
                    settings,
                    pool,
                    application_id=APPLICATION,
                    installation_id=str(AI_ENGINEER_INSTALLATION_ID),
                )
                # Producer-side K01 calls of the fixture tools use this lane's gateway.
                knowledge.bridge.attach_lane(composed)
                return composed

            async with open_postgres_production_stack(
                root=runtime_root,
                monkeypatch=monkeypatch,
                application_id=APPLICATION,
                technical_override=technical,
                components=components,
                knowledge_lane=lane,
                scoped_mission_root=True,
                fixture_owner_prerequisites=False,
                retained_database=retained_database,
                extra_environment={
                    "OPENAI_API_KEY": real_key,
                    "MANIFEST_LAUNCH_BINDINGS_PATH": str(bindings_path),
                    "CAPABILITY_PINS_PATH": str(host_pins(destination / "capability-pins.json")),
                },
            ) as stack:
                from dataclasses import asdict

                assert stack.database is not None
                checkpoint_dsn = stack.settings.db.checkpoint_dsn
                assert checkpoint_dsn is not None
                # Local disposable credentials stay in the ignored evidence directory only.
                recovery = destination / "runtime-recovery.private.json"
                with recovery.open("x", encoding="utf-8") as stream:
                    json.dump(
                        {
                            "schema": "qualia-local-runtime-recovery.v1",
                            "root": str(runtime_root.resolve()),
                            "database": asdict(stack.database),
                            "checkpoint_dsn": checkpoint_dsn.get_secret_value(),
                            "temporal_database": str((runtime_root / "temporal.sqlite").resolve()),
                        },
                        stream,
                        default=str,
                        indent=2,
                    )
                if resume_source is not None:
                    from tests.fixtures.qualia_recovery import retained_fork_manifests

                    fork_manifests = retained_fork_manifests(runtime_root)
                else:
                    fork_manifests = (
                        full_manifest(web, extra.components, vendor=vendor, interventions=True),
                        full_manifest(web, extra.components, vendor="tavily", interventions=False),
                    )
                lifecycle = await lifecycle_for(
                    stack,
                    components,
                    web,
                    profile,
                    extra,
                    fork_manifests=fork_manifests,
                    preparation_root=destination,
                    application_id=APPLICATION,
                    output_schemas={"aieng_record@1": RECORD_SCHEMA},
                )
                scope = stack.database.scope("tenant-1")
                outputs_store = PostgresOutputContractStore(stack.worker_pool)
                if resume_run_id is not None:
                    original = await PostgresRunControlRepository(stack.worker_pool).get_run(
                        scope, resume_run_id
                    )
                    assert original.workflow_type_ref == lifecycle._programs.workflow_ref

                def billing() -> dict[str, Any]:
                    return {
                        "kind": "actual OpenAI Responses model usage",
                        "ledger": str(ledger.path),
                        "estimated_usd_upper_bound": ledger.spent,
                        "unresolved_reservations_usd": sum(ledger.reservations.values()),
                    }

                async def collect(run_id: str, target: Path) -> None:
                    reports = []
                    for output in await outputs_store.accepted_outputs(scope, run_id):
                        value = output.candidate.get("value")
                        details = value.get("details") if isinstance(value, dict) else None
                        markdown = (
                            details.get("report_markdown") if isinstance(details, dict) else None
                        )
                        if isinstance(markdown, str):
                            reports.append(f"## {output.obligation_key}\n\n{markdown}")
                    if reports:
                        (target / "ENGINEERING-EVIDENCE.md").write_text(
                            f"# Agent orchestration evidence: run {run_id}\n\nAccepted StageGraph "
                            "outputs. KS evaluates the separately registered assertions; this "
                            "prose alone is not verification, admission or W1/W2 qualification. "
                            "See knowledge-results.json for actual evaluations and AIDB "
                            "receipts.\n\n" + "\n\n".join(reports),
                            encoding="utf-8",
                        )
                    (target / "knowledge-results.json").write_text(
                        json.dumps(knowledge.worker.results, indent=2), encoding="utf-8"
                    )
                    (target / "mc-knowledge-calls.json").write_text(
                        json.dumps(knowledge.worker.knowledge_calls, indent=2), encoding="utf-8"
                    )
                    gaps = await export_stagegraph(
                        stack, scope, run_id, target, observed_billing=billing()
                    )
                    (target / "export-gaps.json").write_text(
                        json.dumps(gaps, indent=2), encoding="utf-8"
                    )

                async def verify(
                    run_id: str, expected_vendor: str = vendor, *, with_controls: bool = True
                ) -> None:
                    import hashlib

                    outputs = await outputs_store.accepted_outputs(scope, run_id)
                    assert {output.obligation_key for output in outputs} >= REQUIRED_OBLIGATIONS
                    assert ledger.spent > 0, "no actual provider usage observed"
                    engines = set()
                    for path in (destination / "web").glob("*.json"):
                        if path.name.endswith(".model.json"):
                            continue
                        capture = json.loads(path.read_text(encoding="utf-8"))
                        if (
                            capture.get("invocation", {}).get("run_id") != run_id
                            or "raw_path" not in capture
                        ):
                            continue
                        raw = await asyncio.to_thread(Path(capture["raw_path"]).read_bytes)
                        assert "sha256:" + hashlib.sha256(raw).hexdigest() == capture["raw_sha256"]
                        if capture.get("complete") and capture.get("source_usable") is not False:
                            engines.add(capture.get("capture_engine"))
                    extract = expected_vendor + (
                        "_scrape" if expected_vendor == "firecrawl" else "_extract"
                    )
                    assert {"github_file", "arxiv_abs", extract} <= engines, engines
                    await verify_transfers(
                        stack,
                        scope,
                        run_id,
                        outputs,
                        destination,
                        dependents=DEPENDENT_STAGES,
                        synthesis_bindings=frozenset({"framework", "appraisal"}),
                    )
                    await verify_capabilities(
                        stack,
                        scope,
                        run_id,
                        destination,
                        vendor=expected_vendor,
                        interventions=with_controls,
                        expected=stage_tool_names(expected_vendor, interventions=with_controls),
                        skill_prefix="aieng",
                    )
                    (destination / f"native-outcome-{run_id}.json").write_text(
                        json.dumps(knowledge.worker.results, indent=2), encoding="utf-8"
                    )
                    assert any(
                        (item.get("native") or {}).get("status") == "native_applied"
                        and (item.get("native_context") or {}).get("run", {}).get("runId") == run_id
                        for item in knowledge.worker.results
                    ), "No actual admitted AIDB write with complete readback"

                async with qualia_control_api(stack) as control_http:
                    control_task = None

                    async def progress(active_run_id: str) -> None:
                        nonlocal control_task
                        stop = destination / "stop-requested.txt"
                        if stop.exists():
                            raise RuntimeError(
                                "Fixture stopped for repair: "
                                + stop.read_text(encoding="utf-8")[:2000]
                            )
                        if control_task is None:
                            control_task = asyncio.create_task(
                                controller(
                                    stack,
                                    control_http,
                                    active_run_id,
                                    interventions,
                                    destination,
                                    timeout_seconds=900,
                                    queued=QUEUED,
                                    interrupted=INTERRUPTED,
                                    marker_prefix="AIENG",
                                )
                            )
                        if control_task.done():
                            control_task.result()

                    try:
                        if resume_run_id is not None:
                            run_id = resume_run_id
                            target = destination / "source-reexport"
                            target.mkdir()
                            gaps = await export_stagegraph(
                                stack, scope, run_id, target, observed_billing=billing()
                            )
                            (target / "export-gaps.json").write_text(
                                json.dumps(gaps, indent=2), encoding="utf-8"
                            )
                        else:
                            run_id = await run_stagegraph_fixture(
                                stack,
                                lifecycle,
                                fork_manifests[0],
                                destination,
                                collect=collect,
                                verify=verify,
                                progress=progress,
                                timeout_seconds=4200,
                            )
                            assert control_task is not None
                            await control_task
                    finally:
                        if control_task is not None and not control_task.done():
                            control_task.cancel()
                            await asyncio.gather(control_task, return_exceptions=True)
                    fork_root = destination / "tavily-fork"
                    fork_root.mkdir()
                    fork_result = None
                    try:
                        fork_result = await fork_from_completed_stage(
                            stack,
                            control_http,
                            run_id,
                            lifecycle,
                            fork_manifests[1],
                            fork_root,
                            stage=INTERRUPTED,
                            timeout_seconds=4200,
                            skill_prefix="aieng",
                            marker_prefix="AIENG",
                            required_tools=frozenset({"tavily_extract", "arxiv_abs"}),
                        )
                        await verify(fork_result["derived_run_id"], "tavily", with_controls=False)
                    finally:
                        scenario_path = fork_root / "fork-scenario.json"
                        if scenario_path.exists():
                            scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
                            receipt = scenario.get("plan", {}).get("fork", {}).get("receipt", {})
                            if receipt.get("target_run_id"):
                                await collect(receipt["target_run_id"], fork_root)
                return {
                    "run_id": run_id,
                    "evidence": str(destination),
                    "model_usd_upper_bound": ledger.spent,
                    "fork_run_id": fork_result["derived_run_id"] if fork_result else None,
                }
