"""Kill only an explicitly owned child tree, including the Windows venv launcher child."""

import ctypes
import os
import subprocess
from ctypes import wintypes


class OwnedProcess:
    def __init__(self, args, **kwargs):
        if os.name == "nt":
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x4  # CREATE_SUSPENDED
        self.process = subprocess.Popen(args, **kwargs)
        self.job = None
        if os.name == "nt":
            # Windows Python venv launchers have a second interpreter PID. Assign
            # their entire descendant tree before this fixture submits any work.
            class Basic(ctypes.Structure):
                _fields_ = [
                    ("per_process", ctypes.c_int64),
                    ("per_job", ctypes.c_int64),
                    ("flags", wintypes.DWORD),
                    ("min_ws", ctypes.c_size_t),
                    ("max_ws", ctypes.c_size_t),
                    ("active", wintypes.DWORD),
                    ("affinity", ctypes.c_size_t),
                    ("priority", wintypes.DWORD),
                    ("scheduling", wintypes.DWORD),
                ]

            class Extended(ctypes.Structure):
                _fields_ = [
                    ("basic", Basic),
                    ("io", ctypes.c_uint64 * 6),
                    ("process_memory", ctypes.c_size_t),
                    ("job_memory", ctypes.c_size_t),
                    ("peak_process", ctypes.c_size_t),
                    ("peak_job", ctypes.c_size_t),
                ]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            kernel.CreateJobObjectW.restype = wintypes.HANDLE
            kernel.SetInformationJobObject.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
            ]
            kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel = kernel
            job = kernel.CreateJobObjectW(None, None)
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not job or not kernel.SetInformationJobObject(
                job, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ):
                self.process.kill()
                self.process.wait(timeout=10)
                if job:
                    kernel.CloseHandle(job)
                raise OSError("cannot create isolated worker job")
            if not kernel.AssignProcessToJobObject(job, int(self.process._handle)):
                kernel.CloseHandle(job)
                self.process.kill()
                self.process.wait(timeout=10)
                raise OSError("cannot assign fixture worker to isolated job")
            self.job = job
            native = ctypes.WinDLL("ntdll")
            native.NtResumeProcess.argtypes = [wintypes.HANDLE]
            native.NtResumeProcess.restype = ctypes.c_long
            if native.NtResumeProcess(int(self.process._handle)) != 0:
                self.kill()
                raise OSError("cannot resume isolated fixture worker")

    def poll(self):
        return self.process.poll()

    def kill(self):
        if self.job is not None:
            self.kernel.TerminateJobObject(self.job, 1)
            self.kernel.CloseHandle(self.job)
            self.job = None
        elif self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=10)
