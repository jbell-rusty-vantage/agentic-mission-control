"""MO46 standard watcher templates; additive catalog seeds and executable examples."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

SEED_TIME = datetime(2026, 10, 14, tzinfo=UTC)
SEED_VERSION = "1.0.0"
APPS = ("biotech", "ai-engineer")
APP_KEYS = {app: f"mc.app.{app}.watchers" for app in APPS}

SPECS: dict[str, dict[str, Any]] = {
    "stall-detector": {
        "on": {
            "absence": {"of": ["frame", "signal"], "for": "20m"},
            "while": "run.phase == 'active'",
        },
        "then": [
            {"notify": {"kind": "blocked", "text": "No progress for 20 minutes"}},
            {"probe": {}},
        ],
        "limits": {"max_fires": 2, "min_interval": "20m"},
    },
    "result-marker-stop": {
        "on": {"signal": "worker.log", "where": "event.matched == true"},
        "then": [
            {"notify": {"kind": "progress", "text": "Result marker observed"}},
            {"command": {"kind": "cancel"}},
        ],
        "limits": {"max_fires": 1, "min_trust": "provider_signed"},
    },
    "ci-watch": {
        "on": {"signal": "github.check_suite.completed", "where": "event.conclusion == 'failure'"},
        "then": [
            {
                "instruct": {
                    "text": "Inspect the failing checks and repair within the admitted scope."
                }
            }
        ],
        "limits": {"max_fires": 3, "min_interval": "10m", "budget": {"tokens": 50000}},
    },
    "pr-merged-release-wait": {
        "on": {"signal": "github.pull_request.merged", "where": "event.merged == true"},
        "then": [{"satisfy_wait": {"node": "await-merge"}}],
        "limits": {"max_fires": 1, "min_trust": "provider_signed"},
    },
    "artifact-pipeline": {
        "on": {"signal": "artifact.ready", "where": "event.media_type == 'application/pdf'"},
        "then": [
            {"notify": {"kind": "progress", "text": "Artifact ready for governed ingestion"}},
            {
                "instruct": {
                    "text": "Inspect the declared artifact; continue the admitted ingestion stage.",
                    "include": ["event.artifact_ref"],
                }
            },
        ],
        "limits": {"max_fires": 10, "rate": "10/h", "budget": {"tokens": 100000}},
    },
    "budget-guard": {
        "on": {"signal": "budget.threshold", "where": "event.exhausted == true"},
        "then": [
            {"notify": {"kind": "blocked", "text": "Reported budget threshold reached"}},
            {"command": {"kind": "pause"}},
        ],
        "limits": {"max_fires": 1, "min_trust": "provider_signed"},
    },
    "heartbeat-progress": {
        "on": {"signal": "progress"},
        "then": [{"notify": {"kind": "progress", "text": "Progress evidence received"}}],
        "limits": {"max_fires": 24, "min_interval": "5m"},
    },
}


def definitions() -> list[Any]:
    from mission_control.domain.authoring.contracts import WatcherDefinition

    return [
        WatcherDefinition.model_validate(
            {
                "logical_id": f"watcher.{name}",
                "title": name.replace("-", " ").title(),
                "description": "Bounded standard watcher; reactions use admitted command paths.",
                "spec": spec,
            }
        )
        for name, spec in SPECS.items()
    ]


def bundles(
    published_records: Any, seed_format: str, compatibility: str, actor: str
) -> dict[str, Any]:
    result = {}
    for app in APPS:
        records = []
        for definition in definitions():
            records += published_records(
                definition,
                "standard-watcher",
                [
                    "packages/mission-control-db-contract/seeds/watcher_library.py",
                    "tests/fixtures/manifests/watchers/",
                ],
            )
        result[f"{app}/{APP_KEYS[app]}-{SEED_VERSION}.json"] = {
            "format": seed_format,
            "seed_key": APP_KEYS[app],
            "seed_version": SEED_VERSION,
            "component_compatibility": compatibility,
            "depends_on": [],
            "actor_ref": actor,
            "description": (
                "Seven bounded standard watcher templates; "
                "no direct effects or lifecycle settlement."
            ),
            "records": records,
        }
    return result
