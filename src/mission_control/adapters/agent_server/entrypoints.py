"""Bounded graph entrypoints; Temporal alone schedules missions."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from mission_control.adapters.agent_server.deployment import (
    CHILD_GRAPH,
    SEALED_CHILD_GRAPH,
    require_graph,
)
from mission_control.adapters.agent_server.hosting import hosted_graph


async def child(config: RunnableConfig) -> Any:
    require_graph(CHILD_GRAPH)
    return await hosted_graph().factory(config)


async def sealed_child(config: RunnableConfig) -> Any:
    """OVE-184: the run's own sealed child binding, fetched, verified and compiled."""

    require_graph(SEALED_CHILD_GRAPH)
    from mission_control.adapters.agent_server.async_subagents.sealed import (
        default_sealed_child_factory,
    )

    return await default_sealed_child_factory()(config)


def qualification(config: RunnableConfig) -> Any:
    del config
    require_graph("block_c_qualification")
    from mission_control.adapters.agent_server.block_c_qualification.graph import graph

    return graph


def qualification_n1(config: RunnableConfig) -> Any:
    del config
    require_graph("block_c_qualification_n1")
    from mission_control.adapters.agent_server.block_c_qualification.graph_n1 import graph

    return graph


def wait(config: RunnableConfig) -> Any:
    del config
    require_graph("block_c_wait")
    from mission_control.adapters.agent_server.block_c_qualification.wait_graph import graph

    return graph
