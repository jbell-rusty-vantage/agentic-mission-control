"""Stage dependency closure over a Stage Graph blueprint (1.4.4, TR-D12).

Pure helpers lifted from `interpreter._descendants`: the interpreter's cycle invalidation
and the fork's frontier closure (`SemanticForkService.prepare`) compute the same set, so a
fork can never leave a consumer of an invalidated stage outside its frontier.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable

from mission_control.domain.authoring.contracts import StageGraphBlueprint


def descendants_by_stage(blueprint: StageGraphBlueprint) -> dict[str, frozenset[str]]:
    """Every stage's transitive consumers, keyed by stage id (every stage present)."""

    direct: dict[str, set[str]] = defaultdict(set)
    for dependency in blueprint.dependencies:
        direct[dependency.producer_stage_id].add(dependency.consumer_stage_id)
    # OVE-171: a route's targets consume the facts of the stages that decide it.
    for route in blueprint.routes:
        for source in route.fact_stage_ids:
            direct[source] |= route.target_stage_ids
    result: dict[str, frozenset[str]] = {}
    for stage in blueprint.stages:
        descendants: set[str] = set()
        queue = deque(direct[stage.stage_id])
        while queue:
            stage_id = queue.popleft()
            if stage_id in descendants:
                continue
            descendants.add(stage_id)
            queue.extend(direct[stage_id])
        result[stage.stage_id] = frozenset(descendants)
    return result


def stage_descendants(blueprint: StageGraphBlueprint, stage_ids: Iterable[str]) -> frozenset[str]:
    """The transitive consumers of the given stages (the stages themselves excluded)."""

    by_stage = descendants_by_stage(blueprint)
    return frozenset(
        descendant for stage_id in stage_ids for descendant in by_stage.get(stage_id, ())
    )


def closed_frontier(blueprint: StageGraphBlueprint, stage_ids: Iterable[str]) -> frozenset[str]:
    """`frontier | descendants(frontier)`: the invalidation set a fork at those stages needs."""

    frontier = frozenset(stage_ids)
    return frontier | stage_descendants(blueprint, frontier)


__all__ = ["closed_frontier", "descendants_by_stage", "stage_descendants"]
