"""One bounded sample per watcher activity; Temporal owns all repetition.

Resource locations come only from operator registrations. A workflow cannot ask
the worker to execute commands or read an arbitrary path or URL.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator
from temporalio import activity

from mission_control.application.watchers.sources import SourceSignal


class WorkerWatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["file", "log", "process", "url"]
    resource: str = Field(min_length=1)
    pattern: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def validate_resource(self) -> WorkerWatch:
        if self.kind in {"file", "log"} and not Path(self.resource).is_absolute():
            raise ValueError("operator watch paths must be absolute")
        if self.kind == "url":
            url = httpx.URL(self.resource)
            if url.scheme != "https" or not url.host or url.username or url.password:
                raise ValueError("operator URL watches require credential-free HTTPS")
        if self.kind == "process" and (not self.resource.isdecimal() or int(self.resource) < 1):
            raise ValueError("process watch requires a positive PID")
        if self.kind == "log" and not self.pattern:
            raise ValueError("log watch requires a literal pattern")
        return self


async def sample_worker_watch(
    watch: WorkerWatch, *, registration_id: str, now: datetime, http: httpx.AsyncClient
) -> SourceSignal | None:
    if activity.in_activity():
        activity.heartbeat({"source": registration_id, "phase": "sampling"})
    if watch.kind == "url":
        async with http.stream(
            "GET", watch.resource, timeout=5, follow_redirects=False
        ) as response:
            data = {"healthy": 200 <= response.status_code < 300, "status": response.status_code}
        return _signal(watch, registration_id, now, data)
    return await asyncio.to_thread(_sample_local, watch, registration_id, now)


def _sample_local(watch: WorkerWatch, registration_id: str, now: datetime) -> SourceSignal | None:
    data: dict[str, str | bool | int] = {}
    if watch.kind == "file":
        path = Path(watch.resource)
        if not path.is_file():
            return None
        stat = path.stat()
        data = {"present": True, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    elif watch.kind == "log":
        path = Path(watch.resource)
        if not path.is_file():
            return None
        # Bounded tail; never persist log contents, which may contain secrets.
        assert watch.pattern is not None
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 65536))
            matched = watch.pattern.encode() in stream.read(65536)
        if not matched:
            return None
        data = {"matched": True}
    elif watch.kind == "process":
        if os.name == "nt":
            # os.kill(pid, 0) can terminate a Windows process; query only.
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            handle = kernel.OpenProcess(0x1000, False, int(watch.resource))
            if handle:
                try:
                    code = wintypes.DWORD()
                    if (
                        not kernel.GetExitCodeProcess(handle, ctypes.byref(code))
                        or code.value == 259
                    ):
                        return None
                finally:
                    kernel.CloseHandle(handle)
            elif ctypes.get_last_error() != 87:  # ERROR_INVALID_PARAMETER: no such PID
                return None
            data = {"exited": True}
        else:
            return _process_signal(watch, registration_id=registration_id, now=now)
    return _signal(watch, registration_id, now, data)


def _signal(
    watch: WorkerWatch, registration_id: str, now: datetime, data: Mapping[str, str | bool | int]
) -> SourceSignal:
    identity = hashlib.sha256(repr(sorted(data.items())).encode()).hexdigest()
    return SourceSignal(
        source="worker",
        signal_type=f"worker.{watch.kind}",
        delivery_id=f"{registration_id}:{identity}",
        observed_at=now,
        data=dict(data),
    )


def _process_signal(
    watch: WorkerWatch, *, registration_id: str, now: datetime
) -> SourceSignal | None:
    try:
        os.kill(int(watch.resource), 0)
    except ProcessLookupError:
        return SourceSignal(
            source="worker",
            signal_type="worker.process",
            delivery_id=f"{registration_id}:exited",
            observed_at=now,
            data={"exited": True},
        )
    except PermissionError:
        return None  # Lack of permission is not evidence of exit.
    else:
        return None
