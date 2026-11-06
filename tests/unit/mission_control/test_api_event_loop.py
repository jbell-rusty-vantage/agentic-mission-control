"""W1 D3: the API process runs a selector loop on Windows, as the worker does.

psycopg's async adapter (the LangGraph saver behind time travel) refuses uvicorn's default
Windows ``ProactorEventLoop``; ``api_loop_factory`` is the uvicorn ``--loop`` the Makefile and
operator guide pass, and a Proactor loop leaves time travel unset with a log naming the fix.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from uvicorn.config import Config

from mission_control.bootstrap import api

ROOT = Path(__file__).resolve().parents[3]
LOOP = "mission_control.bootstrap.api:api_loop_factory"


def test_windows_gets_a_selector_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api.sys, "platform", "win32")
    loop = api.api_loop_factory()
    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


def test_other_platforms_keep_uvicorns_auto_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api.sys, "platform", "linux")
    loop = api.api_loop_factory()
    try:
        assert isinstance(loop, asyncio.AbstractEventLoop)
        proactor = getattr(asyncio, "ProactorEventLoop", None)
        assert proactor is None or not isinstance(loop, proactor)
    finally:
        loop.close()


def test_uvicorn_resolves_the_loop_flag_and_the_makefile_passes_it() -> None:
    config = Config(app="mission_control.bootstrap.api:create_app", factory=True, loop=LOOP)
    assert config.get_loop_factory() is api.api_loop_factory
    assert f"--loop {LOOP}" in (ROOT / "Makefile").read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform != "win32", reason="the Proactor loop exists on Windows only")
def test_a_proactor_loop_leaves_time_travel_unset_and_names_the_fix(
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = FastAPI()
    settings = SimpleNamespace(langgraph_checkpoint_dsn="postgresql://unused")

    async def compose() -> None:
        async with api.AsyncExitStack() as stack:
            await api.compose_time_travel(application, settings, stack)

    loop = asyncio.ProactorEventLoop()  # type: ignore[attr-defined]
    try:
        with caplog.at_level(logging.ERROR, logger=api.__name__):
            loop.run_until_complete(compose())
    finally:
        loop.close()
    assert getattr(application.state, "time_travel_registry", None) is None
    assert LOOP in caplog.text


def test_the_selector_loop_runs_the_time_travel_composition_past_the_guard() -> None:
    """Under the factory's loop the guard does not fire (the saver itself is not opened here)."""

    async def guarded() -> bool:
        return api._proactor_loop()

    loop = api.api_loop_factory()
    try:
        assert loop.run_until_complete(guarded()) is False
    finally:
        loop.close()
