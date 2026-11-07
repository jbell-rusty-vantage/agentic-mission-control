from neo4j import AsyncDriver, AsyncGraphDatabase

from biotech_mission_adapters.bootstrap.settings import BiotechSettings
from mission_control.bootstrap.settings import IntegrationConfigurationError


async def create_neo4j(settings: BiotechSettings) -> AsyncDriver:
    """PRE-EMPTIVE SETUP: create and verify the official Neo4j async driver."""
    if (
        not settings.mc_biotech_graph_uri
        or not settings.mc_biotech_graph_uri.strip()
        or not settings.mc_biotech_graph_username
        or not settings.mc_biotech_graph_username.strip()
        or settings.mc_biotech_graph_password is None
        or not settings.mc_biotech_graph_password.get_secret_value().strip()
    ):
        raise IntegrationConfigurationError(
            "MC_BIOTECH_GRAPH_URI, MC_BIOTECH_GRAPH_USERNAME and MC_BIOTECH_GRAPH_PASSWORD"
            " are required for Neo4j"
        )
    driver = AsyncGraphDatabase.driver(
        settings.mc_biotech_graph_uri,
        auth=(
            settings.mc_biotech_graph_username,
            settings.mc_biotech_graph_password.get_secret_value(),
        ),
    )
    try:
        await driver.verify_connectivity()
    except BaseException:
        await driver.close()
        raise
    return driver
