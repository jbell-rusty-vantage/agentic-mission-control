"""The 1.10.0 release preserves every applied 1.9.0 migration byte."""

from pathlib import Path


def test_1100_is_exact_190_prefix_plus_0068() -> None:
    root = Path(__file__).resolve().parents[3]
    package = root / "packages/mission-control-db-contract/releases"
    previous = package / "1.9.0/component/migrations"
    current = package / "1.10.0/component/migrations"
    assert sorted(x.name for x in current.iterdir()) == sorted(
        x.name for x in previous.iterdir()
    ) + ["0068_exact_linked_exports.sql"]
    for path in previous.iterdir():
        assert (current / path.name).read_bytes() == path.read_bytes()
    assert (current / "0068_exact_linked_exports.sql").read_bytes() == (
        root / "scripts/release_1100/0068_exact_linked_exports.sql"
    ).read_bytes()
