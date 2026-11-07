from supabase import AsyncClient, acreate_client

from mission_control.bootstrap.settings import IntegrationConfigurationError, Settings


async def create_supabase(settings: Settings, *, privileged: bool = False) -> AsyncClient:
    """Create an async Supabase client; default to the publishable key for least privilege."""
    db = settings.db
    key = db.secret_key if privileged else db.publishable_key
    if not db.url or key is None:
        key_role = "secret_key" if privileged else "publishable_key"
        raise IntegrationConfigurationError(
            f"{db.env_name('url')} and {db.env_name(key_role)} are required for Supabase"
        )
    return await acreate_client(db.url, key.get_secret_value())
