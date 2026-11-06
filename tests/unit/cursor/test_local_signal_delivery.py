"""The Cursor bridge receives only its attempt's delivered signal credential."""

from pathlib import Path

from mission_control.application.secrets.delivery import DeliveredEnvironment
from tests.fixtures.cursor_controls import started_session
from tests.fixtures.cursor_local import local_stack


async def test_the_bridge_receives_per_attempt_signal_values(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MC_SIGNAL_TOKEN", "worker-token-must-not-be-inherited")
    monkeypatch.setenv("MC_PRIVATE_DATABASE", "worker-only")
    stack = local_stack(tmp_path)
    calls = []

    class Delivery:
        async def environment(self, environment, identity):
            calls.append(identity)
            return DeliveredEnvironment(
                values={
                    "MC_SIGNAL_TOKEN": "attempt-token",
                    "MC_SIGNAL_URL": "http://127.0.0.1/signals",
                }
            )

    stack.harness._secrets = Delivery()
    await started_session(stack)
    assert len(calls) == 1
    delivered = stack.launcher.environments[-1]
    assert delivered["MC_SIGNAL_TOKEN"] == "attempt-token"
    assert delivered["MC_SIGNAL_URL"] == "http://127.0.0.1/signals"
    assert "MC_PRIVATE_DATABASE" not in delivered
