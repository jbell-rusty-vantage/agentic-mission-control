"""Execute the actual operator module: discoverable CLI and sanitized refusal before I/O."""

import subprocess
import sys


def test_actual_bootstrap_module_help_is_available_without_provider_calls():
    result = subprocess.run(
        [sys.executable, "-m", "mission_control.bootstrap.owner_probe", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0
    assert "--describe" in result.stdout and "--execute" in result.stdout
    assert "--paid-budget-usd" in result.stdout


def test_actual_bootstrap_cli_refuses_private_malformed_config_without_disclosing_it(tmp_path):
    path = tmp_path / "private-binding.json"
    path.write_text("private-not-a-binding", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mission_control.bootstrap.owner_probe",
            "--application-binding",
            str(path),
            "--plan",
            str(path),
            "--execute",
            "--paid-budget-usd",
            "1",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert "ValidationError" in result.stderr
    assert "private-not-a-binding" not in result.stderr
    assert str(path) not in result.stderr
    assert result.stdout == ""
