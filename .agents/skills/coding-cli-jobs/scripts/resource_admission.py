"""Bounded admission for serial, task-owned qualification jobs; stdlib only.

This module never starts, retries, kills, or reconfigures a job. Keep the returned
lease until the caller has independently reaped its job and finished readback.
Use one shared mutex path for all qualification jobs owned by that coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass
import errno
import math
import os
from pathlib import Path
import re
import stat
import sys
import time
from typing import Callable, Protocol

MIB = 1024**2
DEFAULT_START_BYTES = 1536 * MIB
ACTIVE_FLOOR_BYTES = 1024 * MIB


@dataclass(frozen=True)
class MemorySample:
    available_bytes: int
    commit_limit_bytes: int | None
    committed_bytes: int | None
    # Telemetry only: never silently use an unverified observed peak as a policy.
    owned_peak_bytes: int | None = None

    def __post_init__(self) -> None:
        values = (
            self.available_bytes,
            self.commit_limit_bytes,
            self.committed_bytes,
            self.owned_peak_bytes,
        )
        if any(v is not None and (type(v) is not int or v < 0) for v in values):
            raise ValueError("memory counters must be nonnegative integers or unknown")
        if (
            self.commit_limit_bytes is not None
            and self.committed_bytes is not None
            and self.committed_bytes > self.commit_limit_bytes
        ):
            raise ValueError("committed memory exceeds reported commit limit")

    @property
    def commit_headroom_bytes(self) -> int | None:
        if self.commit_limit_bytes is None or self.committed_bytes is None:
            return None
        return self.commit_limit_bytes - self.committed_bytes


@dataclass(frozen=True)
class JobIdentity:
    name: str
    fingerprint: str

    def __post_init__(self) -> None:
        if not self.name or re.fullmatch(r"sha256:[0-9a-f]{64}", self.fingerprint) is None:
            raise ValueError("exact job name and reviewed fingerprint required")


@dataclass(frozen=True)
class MeasuredReservation:
    job: JobIdentity
    evidence_id: str
    peak_bytes: int
    reserve_bytes: int
    scope: str = "whole-owned-job-on-host"


@dataclass(frozen=True)
class Requirement:
    start_bytes: int
    commit_bytes: int
    basis: str


def requirement(
    job: JobIdentity,
    measurement: MeasuredReservation | None = None,
    verify: Callable[[MeasuredReservation], bool] | None = None,
) -> Requirement:
    """Only a caller's trusted evidence verifier can enable measured admission.

    A single Windows process peak cannot represent a WSL/descendant job. The
    verifier must check source/job identity, measurement scope/completeness,
    provenance, freshness/applicability and the explicitly reviewed reserve.
    This utility cannot establish those facts from a label or a numeric peak.
    """
    if measurement is None:
        return Requirement(DEFAULT_START_BYTES, DEFAULT_START_BYTES, "default-unmeasured")
    if (
        measurement.job != job
        or not measurement.evidence_id
        or measurement.scope != "whole-owned-job-on-host"
        or type(measurement.peak_bytes) is not int
        or measurement.peak_bytes <= 0
        or type(measurement.reserve_bytes) is not int
        or measurement.reserve_bytes <= 0
        or verify is None
        or verify(measurement) is not True
    ):
        raise ValueError("trusted exact-job whole-job measurement and explicit reserve required")
    # The full active floor remains free even after peak plus reserve is allocated.
    total = ACTIVE_FLOOR_BYTES + measurement.peak_bytes + measurement.reserve_bytes
    return Requirement(total, total, "verified-measurement:" + measurement.evidence_id)


class Mutex(Protocol):
    def try_acquire(self) -> bool: ...
    def release(self) -> None: ...


class FileMutex:
    """OS-released file lock; no stale-lock deletion or process termination.

    The caller supplies an existing private task-owned parent directory. Do not
    unlink this persistent file: replacing it would split the serialization domain.
    """

    def __init__(self, path: Path):
        self.path = path
        self._fd: int | None = None

    def try_acquire(self) -> bool:
        if self._fd is not None:
            raise RuntimeError("mutex instance already held")
        if self.path.is_symlink():
            raise ValueError("mutex symlink refused")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path, flags, 0o600)
        try:
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1:
                raise ValueError("mutex must be a single-link regular file")
            if sys.platform == "win32":
                import msvcrt

                if meta.st_size == 0:
                    os.write(fd, b"\0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            os.close(fd)
            if error.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise
        except BaseException:
            os.close(fd)
            raise
        self._fd = fd
        return True

    def release(self) -> None:
        if self._fd is not None:
            fd, self._fd = self._fd, None
            # Closing the descriptor releases the exact OS lock, including on exit.
            os.close(fd)


@dataclass(frozen=True)
class Event:
    disposition: str
    elapsed_seconds: float
    requirement: Requirement
    sample: MemorySample | None
    reason: str


class AdmissionTimeout(TimeoutError):
    def __init__(self, event: Event):
        super().__init__(event.reason)
        self.event = event


class Lease:
    def __init__(self, mutex: Mutex, event: Event):
        self._mutex: Mutex | None = mutex
        self.event = event

    def __enter__(self) -> Lease:
        return self

    def __exit__(self, *_: object) -> None:
        self.release()

    def release(self) -> None:
        if self._mutex is not None:
            mutex, self._mutex = self._mutex, None
            mutex.release()


def active_memory_safe(sample: MemorySample) -> bool:
    """Read-only decision for an existing owned guardian; never signals a process."""
    return sample.available_bytes >= ACTIVE_FLOOR_BYTES


def wait_for_admission(
    job: JobIdentity,
    mutex: Mutex,
    read_memory: Callable[[], MemorySample],
    *,
    wait_seconds: float = 30,
    poll_seconds: float = 1,
    action_expires_at: float | None = None,
    execution_reserve_seconds: float = 0,
    measurement: MeasuredReservation | None = None,
    verify_measurement: Callable[[MeasuredReservation], bool] | None = None,
    emit: Callable[[Event], None] = lambda event: None,
    monotonic: Callable[[], float] = time.monotonic,
    wall_time: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> Lease:
    """Wait only before dispatch; never invoke or retry a job.

    The wait budget is separate from and cannot extend a frozen action's limits.
    For a frozen action pass its unchanged expiry and reviewed full execution /
    readback / cleanup reserve. The caller must still run every existing host
    guard immediately before its single dispatch. Readers/verifiers/emitters must
    themselves be local and bounded; their exceptions fail closed and release.
    """
    numbers = (wait_seconds, poll_seconds, execution_reserve_seconds)
    if (
        not all(math.isfinite(v) for v in numbers)
        or not 0 <= wait_seconds <= 300
        or not 0 < poll_seconds <= 1
        or execution_reserve_seconds < 0
    ):
        raise ValueError("finite wait<=300s, polling<=1s and nonnegative reserve required")
    if action_expires_at is not None and (
        not math.isfinite(action_expires_at) or execution_reserve_seconds <= 0
    ):
        raise ValueError("an action expiry requires a positive reviewed execution reserve")
    begin = monotonic()
    deadline = begin + wait_seconds
    needed = requirement(job, measurement, verify_measurement)
    held = False
    last_sample = None
    reason = "owned-job-busy"
    try:
        while True:
            now = monotonic()
            expiry_left = (
                math.inf
                if action_expires_at is None
                else action_expires_at - wall_time() - execution_reserve_seconds
            )
            if now > deadline or expiry_left <= 0:
                reason = "action-window-insufficient" if expiry_left <= 0 else reason
                event = Event("refused", now - begin, needed, last_sample, reason)
                emit(event)
                raise AdmissionTimeout(event)
            if not held:
                held = mutex.try_acquire()
            if held:
                last_sample = read_memory()
                headroom = last_sample.commit_headroom_bytes
                if last_sample.available_bytes < needed.start_bytes:
                    reason = "available-memory"
                elif headroom is None:
                    reason = "commit-headroom-unknown"
                elif headroom < needed.commit_bytes:
                    reason = "commit-headroom"
                else:
                    # Slow readers/telemetry may consume the last permitted time.
                    now = monotonic()
                    if now > deadline or (
                        action_expires_at is not None
                        and wall_time() + execution_reserve_seconds >= action_expires_at
                    ):
                        reason = "admission-window-elapsed"
                    else:
                        event = Event(
                            "admitted", now - begin, needed, last_sample, "capacity-ready"
                        )
                        emit(event)
                        if monotonic() > deadline or (
                            action_expires_at is not None
                            and wall_time() + execution_reserve_seconds >= action_expires_at
                        ):
                            refused = Event(
                                "refused",
                                monotonic() - begin,
                                needed,
                                last_sample,
                                "telemetry-consumed-admission-window",
                            )
                            emit(refused)
                            raise AdmissionTimeout(refused)
                        lease = Lease(mutex, event)
                        held = False  # transfer ownership; every earlier exception releases
                        return lease
            event = Event("waiting", monotonic() - begin, needed, last_sample, reason)
            emit(event)
            expiry_left = (
                math.inf
                if action_expires_at is None
                else action_expires_at - wall_time() - execution_reserve_seconds
            )
            remaining = min(deadline - monotonic(), expiry_left)
            if remaining <= 0:
                event = Event("refused", monotonic() - begin, needed, last_sample, reason)
                emit(event)
                raise AdmissionTimeout(event)
            sleep(min(poll_seconds, remaining))
    finally:
        if held:
            mutex.release()


def read_windows_memory(owned_peak: Callable[[], int | None] | None = None) -> MemorySample:
    """Local counters only; no imports of Mission Control, WSL or ResourceCare.

    CommitTotal/CommitLimit are system commit pages from GetPerformanceInfo;
    do not mislabel GlobalMemoryStatusEx.AvailPageFile as system commit headroom.
    An optional caller-owned peak reader is telemetry, not trusted policy evidence.
    """
    if os.name != "nt":
        raise OSError("Windows memory reader requires Windows")
    import ctypes
    from ctypes import wintypes

    class Status(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong)
            for name in (
                "total",
                "available",
                "page_total",
                "page_available",
                "virtual_total",
                "virtual_available",
                "extended",
            )
        ]

    class Performance(ctypes.Structure):
        _fields_ = (
            [("cb", wintypes.DWORD)]
            + [
                (name, ctypes.c_size_t)
                for name in (
                    "commit_total",
                    "commit_limit",
                    "commit_peak",
                    "physical_total",
                    "physical_available",
                    "system_cache",
                    "kernel_total",
                    "kernel_paged",
                    "kernel_nonpaged",
                    "page_size",
                )
            ]
            + [(name, wintypes.DWORD) for name in ("handles", "processes", "threads")]
        )

    status = Status()
    status.length = ctypes.sizeof(status)
    performance = Performance()
    performance.cb = ctypes.sizeof(performance)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(Status)]
    kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL
    psapi.GetPerformanceInfo.argtypes = [ctypes.POINTER(Performance), wintypes.DWORD]
    psapi.GetPerformanceInfo.restype = wintypes.BOOL
    if not kernel.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not psapi.GetPerformanceInfo(ctypes.byref(performance), performance.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    if performance.page_size <= 0:
        raise ValueError("invalid system page size")
    peak = None
    if owned_peak is not None:
        try:
            peak = owned_peak()
        except OSError:
            # Optional telemetry unavailable; default policy is unchanged.
            pass
    return MemorySample(
        status.available,
        performance.commit_limit * performance.page_size,
        performance.commit_total * performance.page_size,
        peak,
    )
