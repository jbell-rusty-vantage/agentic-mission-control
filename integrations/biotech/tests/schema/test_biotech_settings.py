import pytest
from pydantic import SecretStr

from biotech_mission_adapters.adapters.infrastructure.neo4j import create_neo4j
from biotech_mission_adapters.bootstrap.settings import BiotechSettings
from mission_control.bootstrap.settings import IntegrationConfigurationError


@pytest.fixture
def core_settings(monkeypatch):
    for name in BiotechSettings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    return BiotechSettings(_env_file=None)


@pytest.mark.asyncio
async def test_neo4j_missing_config_fails_before_driver_creation(core_settings, monkeypatch):
    monkeypatch.setattr(
        "biotech_mission_adapters.adapters.infrastructure.neo4j.AsyncGraphDatabase.driver",
        lambda *args, **kwargs: pytest.fail("driver must not be created"),
    )
    with pytest.raises(IntegrationConfigurationError, match="MC_BIOTECH_GRAPH_URI"):
        await create_neo4j(core_settings)


@pytest.mark.asyncio
async def test_blank_neo4j_secret_is_not_configuration(core_settings):
    settings = core_settings.model_copy(
        update={
            "mc_biotech_graph_uri": "neo4j://offline.invalid",
            "mc_biotech_graph_username": "operator",
            "mc_biotech_graph_password": SecretStr("   "),
        }
    )
    with pytest.raises(IntegrationConfigurationError):
        await create_neo4j(settings)
