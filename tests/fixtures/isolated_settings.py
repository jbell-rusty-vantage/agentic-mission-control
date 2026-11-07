"""Settings built only from explicit values, for tests that assert on configuration.

`get_settings()` and a bare `Settings()` read the developer `.env` and share an `lru_cache`
with every other test, so an assertion on a default value passes or fails with the machine
and the test order. These helpers skip the `.env` file and the process environment entirely:
a shell that exports the owner's `.env` (the run-1 `run1-env.sh` does) must not bind, for
example, `TEMPORAL_CLOUD_API_KEY` or `CURSOR_API_KEY` into a test's configuration.
"""

from __future__ import annotations

from typing import Any

from pydantic import SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from mission_control.bootstrap.settings import Settings

_REQUIRED: dict[str, Any] = {
    # Both Supabase planes carry fake project values, so any selected application resolves them.
    "mc_aieng_db_url": "https://settings.invalid",
    "mc_aieng_db_publishable_key": SecretStr("publishable"),
    "mc_aieng_db_secret_key": SecretStr("secret"),
    "mc_biotech_db_url": "https://settings.invalid",
    "mc_biotech_db_publishable_key": SecretStr("publishable"),
    "mc_biotech_db_secret_key": SecretStr("secret"),
    "openai_api_key": SecretStr("sk-test"),
}


class _ExplicitSettings(Settings):
    """`Settings` whose only source is the constructor's values."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def isolated_settings(**overrides: Any) -> Settings:
    """Settings from the required fields plus `overrides`, never from a `.env` file or the
    process environment."""

    return _ExplicitSettings(_env_file=None, **{**_REQUIRED, **overrides})
