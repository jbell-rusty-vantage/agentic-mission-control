"""The Workspace Closure release never rewrites the previously built family-writer release."""

from pathlib import Path


def test_1120_retains_exact_1110_prefix() -> None:
    root = Path(__file__).resolve().parents[3]
    releases = root / "packages/mission-control-db-contract/releases"
    old = releases / "1.11.0/component/migrations"
    new = releases / "1.12.0/component/migrations"
    assert sorted(path.name for path in new.iterdir()) == sorted(
        path.name for path in old.iterdir()
    ) + ["0070_workspace_closure.sql"]
    for path in old.iterdir():
        assert (new / path.name).read_bytes() == path.read_bytes()
    assert (new / "0070_workspace_closure.sql").read_bytes() == (
        root / "scripts/release_1120/0070_workspace_closure.sql"
    ).read_bytes()
