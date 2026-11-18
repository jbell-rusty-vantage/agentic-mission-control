"""Builders, constants and fakes that other test files import.

Moved from tests/acceptance/mission_control/test_overnight_linked.py.
"""

from __future__ import annotations

from typing import Any

from mission_control.domain.authoring.manifest import canonical_manifest_bytes, load_manifest_yaml
from tests.support.acceptance.mission_control.overnight_goal_directed import goal_manifest
from tests.support.acceptance.mission_control.overnight_stagegraph import stagegraph_manifest


def linked_manifest(pack: dict[str, Any], *, scenario: str = "positive") -> str:
    source = load_manifest_yaml(goal_manifest(pack))["mission"]
    source["key"] = "source"
    source["title"] = "Grounded report accepted by independent verifier and review"
    source["environment"]["governors"].update(iterations=1, patience=1)
    source["environment"]["budget"]["usd"] = 3
    source["environment"]["budget"]["tool_calls"] = 12
    consumer = load_manifest_yaml(stagegraph_manifest(pack))["mission"]
    consumer["key"] = "consumer"
    consumer["title"] = "Independent mission summarizes one accepted linked report"
    consumer["goals"] = [consumer["goals"][1]]
    consumer["program"]["objectives"] = [consumer["goals"][0]["key"]]
    consumer["environment"]["budget"]["usd"] = 2
    consumer["environment"]["budget"]["tool_calls"] = 12
    consume, review = consumer["program"]["nodes"][2:]
    consume["depends_on"] = []
    consume["inputs"] = [{"name": "report", "from": "source.report", "expand": "reference"}]
    consume["instruction"] = (
        "Read /.mission/transfer.json and use knowledge_read on its exact report access_ref. "
        "Submit consume.comparison as a short attributed summary of the actual source bytes."
    )
    review["task"]["packet"] = ["consume.comparison"]
    consumer["program"]["nodes"] = [consume, review]
    if scenario == "held-repair":
        from copy import deepcopy

        source["title"] = "Bounded unsupported source retained for explicit repair"
        consumer["title"] = "Repair exact held report using full source findings"
        consume["outputs"].extend(
            deepcopy(item)
            for item in source["program"]["outputs"]
            if item["name"] in {"report", "progress_note"}
        )
        consume["instruction"] = (
            "Read the exact held report and full findings from /.mission/transfer.json. "
            "These are repair subjects, not accepted evidence. Propose a grounded successor "
            "with supersedes bound to the actual source receipt; submit consume.report, "
            "consume.progress_note and consume.comparison for normal checks and review."
        )
        review["task"]["packet"].extend(["consume.report", "consume.progress_note"])
    if scenario == "adoption":
        from copy import deepcopy

        promised = deepcopy(
            next(item for item in source["program"]["outputs"] if item["name"] == "report")
        )
        promised["name"] = "adopted_report"
        consume["outputs"].append(promised)
        review["task"]["packet"].append("consume.adopted_report")
    return canonical_manifest_bytes(
        {
            "manifest": "mission/v1",
            "missions": [source, consumer],
            "links": [
                {
                    "from": "source",
                    "to": "consumer",
                    "kind": "supplies",
                    "outputs": ["report"],
                    "on": (
                        {"goal_accepted": {"goal_key": source["goals"][0]["key"]}}
                        if scenario.startswith("cancel-")
                        else "execution_complete"
                        if scenario == "held-repair"
                        else "mission_accepted"
                    ),
                    "on_upstream_cancel": (
                        "cancel_downstream" if scenario == "cancel-propagate" else "continue"
                    ),
                    "receiving_purpose": "repair"
                    if scenario == "held-repair"
                    else "dependent_input",
                    "selector": "finalized_snapshot"
                    if scenario == "held-repair"
                    else "accepted_snapshot",
                    "placement": "handle",
                    "alternatives": ["file"],
                }
            ],
        }
    ).decode()
