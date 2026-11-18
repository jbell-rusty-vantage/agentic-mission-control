"""Builders, constants and fakes that other test files import.

Moved from tests/unit/chains/test_chain_reducer.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from mission_control.application.chains.reducer import ChainReducer, ChainSnapshot, MemberRun
from mission_control.domain.authoring.manifest import load_manifest_yaml, parse_manifest
from mission_control.domain.composition.chain import (
    ChainLink,
    ChainLinkState,
    ChainScope,
    ChainTransition,
    MissionChain,
    build_mission_chain,
    compile_chain,
)
from mission_control.domain.policies.contracts import RunOutcome, RunPhase

ROOT = Path(__file__).resolve().parents[4]
FIXTURE = ROOT / "tests/fixtures/manifests/two-mission-chain.yml"
NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
CHAIN_ID = UUID("01920000-0000-7000-8000-000000000101")
SCOPE = ChainScope(
    installation_id=UUID("01920000-0000-7000-8000-0000000000aa"),
    application_id="biotech",
    tenant_id=UUID("01920000-0000-7000-8000-0000000000bb"),
)


CAUSE = UUID("01920000-0000-7000-8000-0000000000cc")
reducer = ChainReducer()


def mission_id(key: str) -> UUID:
    return uuid5(CHAIN_ID, f"mission:{key}")


def document() -> dict[str, Any]:
    return load_manifest_yaml(FIXTURE.read_text(encoding="utf-8"))


def build(doc: dict[str, Any]) -> MissionChain:
    compilation = compile_chain(parse_manifest(doc))
    assert compilation.ok, compilation.blockers
    assert compilation.resolution is not None
    return build_mission_chain(
        resolution=compilation.resolution,
        chain_id=CHAIN_ID,
        scope=SCOPE,
        chain_key="chain",
        title="Chain",
        manifest_digest="sha256:" + "a" * 64,
        members={
            key: (mission_id(key), uuid5(CHAIN_ID, f"revision:{key}"))
            for key in compilation.resolution.order
        },
        created_at=NOW,
        created_by_actor_ref="actor:owner",
    )


def run(
    key: str,
    *,
    phase: RunPhase = RunPhase.ACTIVE,
    outcome: RunOutcome | None = None,
    obligations: frozenset[str] = frozenset(),
    required: frozenset[str] = frozenset(),
    outputs: tuple[str, ...] = (),
) -> MemberRun:
    return MemberRun(
        mission_id=mission_id(key),
        run_id=uuid5(CHAIN_ID, f"run:{key}"),
        run_key=f"run-{key}",
        phase=phase,
        terminal_outcome=outcome,
        required_obligations=required,
        accepted_obligations=obligations,
        accepted_outputs=outputs,
        evidence_frontier_digest="sha256:" + "f" * 64,
    )


def accepted(key: str, goal: str, *, outputs: tuple[str, ...] = ("artifact://x/evidence_map",)):
    return run(
        key,
        phase=RunPhase.TERMINAL,
        outcome=RunOutcome.COMPLETED,
        obligations=frozenset({goal}),
        required=frozenset({goal}),
        outputs=outputs,
    )


def snapshot(chain: MissionChain, *runs: MemberRun) -> ChainSnapshot:
    return ChainSnapshot(
        chain=chain,
        link_versions={link.link_id: 1 for link in chain.links},
        runs={item.mission_id: item for item in runs},
    )


def reduce(chain: MissionChain, trigger: str, *runs: MemberRun) -> ChainTransition:
    return reducer.on_events(
        snapshot(chain, *runs),
        cause_event_id=CAUSE,
        trigger_mission_id=mission_id(trigger),
        occurred_at=NOW,
    )


def apply(chain: MissionChain, transition: ChainTransition) -> MissionChain:
    """Fold a transition into the chain the way the store persists it."""

    links = []
    by_id = {update.link_id: update for update in transition.link_updates}
    for link in chain.links:
        update = by_id.get(link.link_id)
        if update is None:
            links.append(link)
            continue
        links.append(
            link.model_copy(
                update={
                    "state": update.state,
                    "blocked_reason": update.blocked_reason,
                    "released_at": NOW if update.state is ChainLinkState.RELEASED else None,
                }
            )
        )
    values: dict[str, Any] = {"links": tuple(links)}
    for update in transition.chain_updates:
        values.update(
            lifecycle=update.lifecycle,
            phase=update.phase,
            terminal_outcome=update.terminal_outcome,
            version=chain.version + 1,
        )
    return MissionChain.model_validate({**chain.model_dump(), **values})


def link(chain: MissionChain, key: str) -> ChainLink:
    return next(item for item in chain.links if item.link_key == key)
