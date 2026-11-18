"""Offline fixture-driver acceptance and transport regressions; no provider or database calls."""

from __future__ import annotations

import argparse
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from mission_control.contracts.run_evidence import ResultEvidence
from mission_control.domain.coordinator.launch import (
    GoalDirectedResultDetails,
    WorkflowResultRecord,
)

SPEC = importlib.util.spec_from_file_location(
    "sprint_oc_fixture_driver",
    Path(__file__).resolve().parents[2] / "scripts/sprint_oc_w1_driver.py",
)
assert SPEC is not None and SPEC.loader is not None
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


def verification(iteration=1, *, decision="accepted", unmet=()):
    return {
        "verification_id": f"verify-{iteration}",
        "verifier_operation_identity": f"verifier-{iteration}",
        "decision": decision,
        "executor_identity": {"iteration": {"run_id": "run", "goal_iteration": iteration}},
        "unmet_obligations": list(unmet),
    }


def evidence():
    program = {
        "key": "root",
        "behavior": "goal_loop",
        "outputs": [{"name": "report", "enforcement": "required"}],
    }
    # Serialize the actual API's typed ResultEvidence/WorkflowResultRecord. No schema-slot
    # completion_validation exists for these manifests; verifier chronology lives here.
    record = WorkflowResultRecord(
        run_id="run",
        tenant_scope="tenant",
        request_scope="scope",
        blueprint_family="GoalDirected",
        terminal_outcome="completed",
        completed_at=datetime.now(UTC),
        family_result=GoalDirectedResultDetails(
            execution_epoch=1,
            stop_reason="accepted",
            final_verifier_action="accepted",
            goal_iterations=1,
            agent_runs=1,
            rollover_count=0,
            active_revision_id="revision",
            verification_results=(verification(),),
        ),
    )
    documents = {
        "inspection": {"run_id": "run", "lifecycle": "completed", "execution_outcome": "completed"},
        "outputs": {
            "accepted": [{"obligation_key": "root.report"}],
            "fulfillment": {
                "decisions": [
                    {
                        "obligation_key": "root.report",
                        "enforcement": "required",
                        "disposition": "fulfilled",
                    }
                ]
            },
        },
        "evidence": {
            "result": ResultEvidence(status="recorded", record=record).model_dump(mode="json")
        },
    }
    return program, documents


def family(docs):
    return docs["evidence"]["result"]["record"]["family_result"]


def test_terminal_success_is_not_acceptance():
    program, docs = evidence()
    docs["outputs"]["accepted"] = []
    assert driver.check_acceptance(program, docs)
    program, docs = evidence()
    family(docs)["verification_results"] = []
    assert driver.check_acceptance(program, docs)


def test_positive_requires_exact_fulfillment_and_minimum_iterations():
    program, docs = evidence()
    assert driver.check_acceptance(program, docs) == []
    assert driver.check_acceptance(program, docs, minimum_iterations=2)
    family(docs)["verification_results"].append(verification(2))
    assert driver.check_acceptance(program, docs, minimum_iterations=2) == []
    docs["inspection"]["execution_outcome"] = "failed"
    assert driver.check_acceptance(program, docs)


def test_negative_requires_specific_omission_and_refusal():
    program, docs = evidence()
    assert driver.check_acceptance(program, docs, expected_unfulfilled="root.report")
    docs["outputs"]["accepted"] = []
    docs["outputs"]["fulfillment"]["decisions"][0]["disposition"] = "unfulfilled"
    family(docs)["verification_results"] = [
        verification(decision="rejected", unmet=["output:root.report"])
    ]
    family(docs)["final_verifier_action"] = "rejected"
    assert driver.check_acceptance(program, docs, expected_unfulfilled="root.report") == []
    assert driver.check_acceptance(program, docs)


def test_missing_or_foreign_result_fails_closed():
    program, docs = evidence()
    docs["evidence"]["result"]["status"] = "missing_terminal_result"
    assert driver.check_acceptance(program, docs)
    program, docs = evidence()
    family(docs)["verification_results"][0]["executor_identity"]["iteration"]["run_id"] = "other"
    assert driver.check_acceptance(program, docs)


def test_consumer_placeholder_and_unknown_placeholder(tmp_path):
    manifest = tmp_path / "fixture.yml"
    manifest.write_text("producer: __PRODUCER__\nconsumer: __CONSUMER__\n")
    item = object.__new__(driver.Driver)
    item.evidence = tmp_path
    item.options = argparse.Namespace(
        manifest=manifest, producer="producer.default", consumer="producer.fallback"
    )
    assert "consumer: producer.fallback" in item.rendered()
    manifest.write_text("unknown: __UNBOUND__")
    with pytest.raises(ValueError, match="unresolved"):
        item.rendered()


def test_collection_http_failure_is_not_success(tmp_path):
    item = object.__new__(driver.Driver)
    item.evidence = tmp_path
    item.client = httpx.Client(
        base_url="http://local",
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={})),
    )
    assert item.collect("run") == 1


def test_wait_http_failure_is_not_terminal_success(tmp_path):
    item = object.__new__(driver.Driver)
    item.call = lambda *args, **kwargs: (503, {"run_id": "run", "lifecycle": "completed"})
    item.evidence = tmp_path
    item.client = httpx.Client(
        base_url="http://local",
        transport=httpx.MockTransport(lambda request: httpx.Response(503, json={})),
    )
    assert item.wait("run", 1) == 1


def test_request_exception_is_recorded_without_secret_text(tmp_path):
    def fail(request):
        raise httpx.ConnectError("secret-bearing URL must not be recorded", request=request)

    item = object.__new__(driver.Driver)
    item.evidence = tmp_path
    item.client = httpx.Client(
        transport=httpx.MockTransport(fail), base_url="https://example.invalid"
    )
    status, body = item.call("GET", "/run", "error")
    assert status == 0 and body == {"transport_error": "ConnectError"}
    assert "secret-bearing" not in (tmp_path / "error.json").read_text()


def test_w2_requires_selected_revision_and_delivery():
    program = {
        "behavior": "stage_graph",
        "nodes": [
            {"key": "produce", "outputs": [{"name": "report", "enforcement": "required"}]},
            {"key": "consume", "outputs": [{"name": "comparison", "enforcement": "required"}]},
        ],
    }
    docs = {
        "inspection": {"lifecycle": "completed", "execution_outcome": "completed"},
        "outputs": {
            "accepted": [
                {"obligation_key": "produce.report", "revision": {"revision_id": "exact"}},
                {"obligation_key": "consume.comparison"},
            ],
            "fulfillment": {
                "decisions": [
                    {"obligation_key": key, "disposition": "fulfilled"}
                    for key in ("produce.report", "consume.comparison")
                ]
            },
        },
        "completion-evidence": {
            "status": "recorded",
            "decisions": [{"validation": {"status": "satisfied"}}],
        },
        "consumer_plans": [
            {
                "plan": {
                    "exact_sources": [
                        {
                            "source_kind": "produced_output",
                            "binding": "report",
                            "source_ref": "exact",
                            "admission": "accepted",
                        }
                    ]
                },
                "receipts": [{"result": "ready"}],
            }
        ],
    }
    assert driver.check_acceptance(program, docs) == []
    docs["consumer_plans"][0]["plan"]["exact_sources"][0]["source_ref"] = "sibling"
    assert driver.check_acceptance(program, docs)
