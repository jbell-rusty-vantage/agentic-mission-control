"""Deterministic admission, expiry and owned-lock regressions; no providers."""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from resource_admission import (  # noqa: E402
    ACTIVE_FLOOR_BYTES,
    DEFAULT_START_BYTES,
    MIB,
    AdmissionTimeout,
    FileMutex,
    JobIdentity,
    MeasuredReservation,
    MemorySample,
    active_memory_safe,
    requirement,
    wait_for_admission,
)

JOB = JobIdentity("owned-check", "sha256:" + "a" * 64)


class Clock:
    now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Mutex:
    def __init__(self, busy=0):
        self.busy = busy
        self.held = False
        self.released = 0

    def try_acquire(self):
        if self.held:
            raise AssertionError("overlapping job admission")
        if self.busy:
            self.busy -= 1
            return False
        self.held = True
        return True

    def release(self):
        if not self.held:
            raise AssertionError("unowned lock release")
        self.held = False
        self.released += 1


def sample(available=2048 * MIB, commit=4096 * MIB, peak=None):
    return MemorySample(available, 8192 * MIB, 8192 * MIB - commit, peak)


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.mutex = Mutex()
        self.events = []

    def admit(self, reader=lambda: sample(), **options):
        return wait_for_admission(
            JOB,
            self.mutex,
            reader,
            monotonic=self.clock.time,
            wall_time=self.clock.time,
            sleep=self.clock.sleep,
            emit=self.events.append,
            **options,
        )

    def test_waits_for_headroom_and_holds_lease_through_caller_cleanup(self):
        observations = iter([sample(1200 * MIB), sample(1400 * MIB), sample()])
        with self.admit(lambda: next(observations), wait_seconds=3) as lease:
            self.assertEqual(self.clock.now, 2)
            self.assertTrue(self.mutex.held)
            self.assertEqual(lease.event.sample.commit_headroom_bytes, 4096 * MIB)
        self.assertEqual(self.mutex.released, 1)

    def test_busy_job_serializes_without_sampling_or_clearing_other_lock(self):
        self.mutex.busy = 2
        reads = []
        with self.admit(lambda: reads.append(1) or sample(), wait_seconds=3):
            self.assertEqual(reads, [1])
            self.assertEqual(self.clock.now, 2)
        self.assertEqual(self.mutex.released, 1)

    def test_busy_timeout_never_releases_another_job(self):
        self.mutex.busy = 100
        with self.assertRaises(AdmissionTimeout):
            self.admit(wait_seconds=2)
        self.assertEqual(self.clock.now, 2)
        self.assertEqual(self.mutex.released, 0)

    def test_capacity_timeout_is_bounded_and_releases_own_lock(self):
        with self.assertRaises(AdmissionTimeout) as error:
            self.admit(lambda: sample(1000 * MIB), wait_seconds=2.5)
        self.assertEqual(self.clock.now, 2.5)
        self.assertEqual(error.exception.event.reason, "available-memory")
        self.assertFalse(self.mutex.held)

    def test_commit_exhaustion_refuses_despite_physical_availability(self):
        with self.assertRaises(AdmissionTimeout) as error:
            self.admit(lambda: sample(commit=256 * MIB), wait_seconds=0)
        self.assertEqual(error.exception.event.reason, "commit-headroom")

    def test_unknown_commit_refuses_and_observed_peak_cannot_lower_defaults(self):
        observed = MemorySample(1400 * MIB, None, None, 10 * MIB)
        self.assertEqual(requirement(JOB).start_bytes, DEFAULT_START_BYTES)
        with self.assertRaises(AdmissionTimeout):
            self.admit(lambda: observed, wait_seconds=0)
        observed = replace(observed, available_bytes=2048 * MIB)
        with self.assertRaises(AdmissionTimeout) as error:
            self.admit(lambda: observed, wait_seconds=0)
        self.assertEqual(error.exception.event.reason, "commit-headroom-unknown")

    def test_verified_measurement_requires_exact_job_scope_and_reserve(self):
        measured = MeasuredReservation(JOB, "trusted-receipt", 128 * MIB, 128 * MIB)
        expected = ACTIVE_FLOOR_BYTES + 256 * MIB
        self.assertEqual(requirement(JOB, measured, lambda _: True).start_bytes, expected)
        for bad in (
            replace(measured, reserve_bytes=0),
            replace(measured, scope="single-process"),
            replace(measured, job=JobIdentity("other", JOB.fingerprint)),
        ):
            with self.assertRaises(ValueError):
                requirement(JOB, bad, lambda _: True)
        with self.assertRaises(ValueError):
            requirement(JOB, measured)
        with self.assertRaises(ValueError):
            requirement(JOB, measured, lambda _: False)

    def test_measured_admission_keeps_full_active_floor_and_records_basis(self):
        measured = MeasuredReservation(JOB, "reviewed-whole-job", 128 * MIB, 128 * MIB)
        with self.admit(
            lambda: sample(1300 * MIB), measurement=measured, verify_measurement=lambda _: True
        ) as lease:
            self.assertEqual(lease.event.requirement.start_bytes, 1280 * MIB)
            self.assertIn("reviewed-whole-job", lease.event.requirement.basis)
        self.assertFalse(active_memory_safe(sample(ACTIVE_FLOOR_BYTES - 1)))
        self.assertTrue(active_memory_safe(sample(ACTIVE_FLOOR_BYTES)))

    def test_action_expiry_reserves_original_full_execution_and_cleanup(self):
        with self.assertRaises(AdmissionTimeout) as error:
            self.admit(
                lambda: sample(1000 * MIB),
                wait_seconds=20,
                action_expires_at=12,
                execution_reserve_seconds=10,
            )
        self.assertEqual(self.clock.now, 2)
        self.assertEqual(error.exception.event.reason, "action-window-insufficient")
        self.assertEqual(self.mutex.released, 1)

    def test_measurement_verification_counts_toward_admission_deadline(self):
        measured = MeasuredReservation(JOB, "reviewed-whole-job", 128 * MIB, 128 * MIB)

        def verify(_):
            self.clock.sleep(2)
            return True

        with self.assertRaises(AdmissionTimeout):
            self.admit(wait_seconds=1, measurement=measured, verify_measurement=verify)
        self.assertFalse(self.mutex.held)
        self.assertEqual(self.mutex.released, 0)

    def test_slow_reader_cannot_admit_after_deadline(self):
        def slow():
            self.clock.sleep(2)
            return sample()

        with self.assertRaises(AdmissionTimeout):
            self.admit(slow, wait_seconds=1)
        self.assertEqual(self.mutex.released, 1)

    def test_reader_and_telemetry_errors_fail_closed_release_owned_mutex(self):
        def fail():
            raise OSError("counter unavailable")

        with self.assertRaises(OSError):
            self.admit(fail)
        self.assertEqual(self.mutex.released, 1)
        with self.assertRaises(RuntimeError):
            wait_for_admission(
                JOB,
                self.mutex,
                lambda: sample(),
                monotonic=self.clock.time,
                wall_time=self.clock.time,
                sleep=self.clock.sleep,
                emit=lambda _: (_ for _ in ()).throw(RuntimeError("telemetry")),
            )
        self.assertFalse(self.mutex.held)

    def test_slow_telemetry_cannot_return_a_lease_after_deadline(self):
        def emit(event):
            if event.disposition == "admitted":
                self.clock.sleep(2)

        with self.assertRaises(AdmissionTimeout) as error:
            wait_for_admission(
                JOB,
                self.mutex,
                lambda: sample(),
                wait_seconds=1,
                monotonic=self.clock.time,
                wall_time=self.clock.time,
                sleep=self.clock.sleep,
                emit=emit,
            )
        self.assertEqual(error.exception.event.reason, "telemetry-consumed-admission-window")
        self.assertEqual(self.mutex.released, 1)

    def test_real_mutex_serializes_handles_without_deleting_lock_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "owned-jobs.lock"
            first, second = FileMutex(path), FileMutex(path)
            try:
                self.assertTrue(first.try_acquire())
                self.assertFalse(second.try_acquire())
                first.release()
                self.assertTrue(second.try_acquire())
            finally:
                first.release()
                second.release()
            self.assertTrue(path.exists())

    def test_invalid_bounds_and_invalid_counters_refuse_before_lock(self):
        for options in (
            {"wait_seconds": float("inf")},
            {"wait_seconds": -1},
            {"poll_seconds": 0},
            {"poll_seconds": 2},
            {"action_expires_at": 10},
        ):
            with self.assertRaises(ValueError):
                self.admit(**options)
        with self.assertRaises(ValueError):
            MemorySample(1, 10, 11)
        self.assertEqual(self.mutex.released, 0)


if __name__ == "__main__":
    unittest.main()
