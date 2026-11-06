from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aioboto3
from aiobotocore.config import AioConfig
from aiobotocore.session import AioSession

from mission_control.bootstrap.settings import Settings


def s3_region(settings: Settings) -> str:
    """The S3 signing region: ``S3_REGION``, else ``AWS_REGION``."""
    return settings.s3_region or settings.aws_region


def create_aws_session(settings: Settings) -> aioboto3.Session:
    """Use the normal AWS credential chain, including the user's authenticated CLI profile.

    Explicit S3 keys (``S3_ACCESS_KEY_ID`` / ``S3_SECRET_ACCESS_KEY``, an S3-compatible store
    such as Supabase Storage) take precedence over the profile and the chain.
    """
    kwargs: dict[str, Any] = {"region_name": s3_region(settings)}
    key_id, secret = settings.s3_access_key_id, settings.s3_secret_access_key
    explicit = key_id is not None and secret is not None
    if key_id is not None and secret is not None:
        # No profile is selected or required: the keys sign every request.
        kwargs["aws_access_key_id"] = key_id.get_secret_value()
        kwargs["aws_secret_access_key"] = secret.get_secret_value()
    if settings.aws_profile and not explicit:
        kwargs["profile_name"] = settings.aws_profile
    else:
        # A blank AWS_PROFILE is an explicit (invalid) profile to botocore.
        # Ignore only empty profile variables in this session, preserving the
        # SDK's precedence and all other credential providers without changing
        # the process environment.
        config_name, env_names, default, conversion = AioSession.SESSION_VARIABLES["profile"]
        names = [env_names] if isinstance(env_names, str) else (env_names or [])
        profile_env = [name for name in names if os.environ.get(name) != ""]
        kwargs["botocore_session"] = AioSession(
            session_vars={"profile": (config_name, profile_env, default, conversion)}
        )
    return aioboto3.Session(**kwargs)


def s3_client_config(settings: Settings) -> AioConfig:
    """SigV4; path-style when the endpoint needs it. Checksums only when an operation requires
    them: botocore 1.36+ sends CRC32 trailers by default, which S3-compatible stores (Supabase
    Storage) reject or do not return."""
    return AioConfig(
        signature_version="s3v4",
        s3={"addressing_style": "path"} if settings.s3_force_path_style else None,
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )


@asynccontextmanager
async def s3_client(settings: Settings) -> AsyncIterator[Any]:
    """Yield an async S3 client and always close its underlying HTTP session.

    The single choke point for every S3 call: the endpoint (``S3_ENDPOINT_URL``, unset for AWS),
    the signing region and the client configuration all apply here.
    """
    session = create_aws_session(settings)
    async with session.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=s3_region(settings),
        config=s3_client_config(settings),
    ) as client:
        yield client
