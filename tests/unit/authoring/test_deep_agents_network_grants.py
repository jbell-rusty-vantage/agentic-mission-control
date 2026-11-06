"""Authored Deep Agents network authority survives compile, template sealing and role narrowing."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import yaml

from mission_control.adapters.deep_agents.binding import execution_binding
from mission_control.application.authoring.manifest_launch_inputs import ManifestLaunchBindingError
from mission_control.domain.authoring.manifest import canonical_manifest_bytes
from tests.unit.authoring.test_manifest_launch_inputs import (
    MINIMAL,
    admitted,
    compile_programs,
    pubmed_resolver,
)

HOSTS = ["www.qualialife.com", "www.mdpi.com"]


def _document() -> dict[str, Any]:
    document = yaml.safe_load(MINIMAL.read_text(encoding="utf-8"))
    document["manifest"] = "mission/v2"
    document["mission"]["environment"]["network"] = {
        "mode": "allowlist",
        "allow": HOSTS,
        "include_kit": False,
    }
    return document


def _templates(document: dict[str, Any], *, goal: bool = False) -> dict[str, Any]:
    definitions, programs = asyncio.run(
        compile_programs(canonical_manifest_bytes(document).decode())
    )
    definition, program = definitions[0], programs[0]
    resolver = pubmed_resolver(definition)
    method = resolver.goal_templates if goal else resolver.stage_templates
    return method(definition, admitted(program))


def _assert_exact(template: Any, hosts: frozenset[str], policy: str) -> None:
    assert template.capability_grant.network_hosts == hosts
    assert template.workspace.network_policy == policy
    sealed = execution_binding(template)
    assert sealed.capability_grant.network_hosts == hosts
    assert sealed.workspace.network_policy == policy
    sealed.verify_operation_envelope(template)


def test_stage_network_allowlist_reaches_exact_binding_and_child_none_is_narrowed() -> None:
    document = _document()
    document["mission"]["program"]["nodes"][1]["environment"]["network"] = {"mode": "none"}
    templates = _templates(document)
    _assert_exact(templates["collect/execute/default"], frozenset(HOSTS), "allowlisted")
    _assert_exact(templates["synthesize/execute/default"], frozenset(), "none")


def test_goal_executor_and_verifier_keep_their_distinct_authored_network_scopes() -> None:
    document = _document()
    document["mission"]["program"] = {
        "key": "root",
        "behavior": "goal_loop",
        "objective": "evidence_map",
        "action_space": ["pubmed"],
        "verifier": {"independent": True, "environment": {"network": {"mode": "none"}}},
        "outputs": [{"name": "claims", "schema": "claim_table@1"}],
    }
    templates = _templates(document, goal=True)
    _assert_exact(templates["executor"], frozenset(HOSTS), "allowlisted")
    _assert_exact(templates["verifier"], frozenset(), "none")


def test_unrepresentable_unrestricted_network_refuses_instead_of_dropping_authority() -> None:
    document = _document()
    document["mission"]["environment"]["network"] = {"mode": "allow_all", "include_kit": False}
    with pytest.raises(ManifestLaunchBindingError, match="finite network allowlists") as error:
        _templates(document)
    assert error.value.pointer == "/mission/environment/network"


def test_omitted_network_keeps_legacy_empty_grant() -> None:
    document = _document()
    del document["mission"]["environment"]["network"]
    for template in _templates(document).values():
        assert not template.capability_grant.network_hosts


def test_wildcard_network_hosts_refuse_at_the_authored_allowlist() -> None:
    document = _document()
    document["mission"]["environment"]["network"]["allow"] = ["*.qualialife.com"]
    with pytest.raises(ManifestLaunchBindingError, match="exact network hosts") as error:
        _templates(document)
    assert error.value.pointer == "/mission/environment/network/allow"


def test_goal_executor_objective_names_the_exact_required_output_contracts() -> None:
    # W1 D35 (run af51473c): the prompt named only the objective contract, the model cited it as
    # output_contract_ref, and the reconciler admits only `output:<name>` refs.
    document = _document()
    document["mission"]["program"] = {
        "key": "root",
        "behavior": "goal_loop",
        "objective": "evidence_map",
        "action_space": ["pubmed"],
        "verifier": {"independent": True},
        "outputs": [{"name": "claims", "schema": "claim_table@1"}],
    }
    templates = _templates(document, goal=True)
    # L1-06: the verifier's verdict contract names them for its own observation.
    expected = {
        "executor": "output_contract_ref to exactly one of: output:claims",
        "verifier": "output_contract_ref: exactly one of output:claims",
    }
    for role, line in expected.items():
        prompt = " ".join(item.content for item in templates[role].prompt_segments)
        assert line in prompt
