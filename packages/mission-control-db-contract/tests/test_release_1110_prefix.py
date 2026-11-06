"""The writer-grant repair never rewrites the previously built exact-export release."""

from pathlib import Path


def test_1110_retains_exact_1100_prefix() -> None:
    root = Path(__file__).resolve().parents[3]
    releases = root / "packages/mission-control-db-contract/releases"
    old = releases / "1.10.0/component/migrations"
    new = releases / "1.11.0/component/migrations"
    assert sorted(path.name for path in new.iterdir()) == sorted(
        path.name for path in old.iterdir()
    ) + ["0069_linked_export_family_writer.sql"]
    for path in old.iterdir():
        assert (new / path.name).read_bytes() == path.read_bytes()
    assert (new / "0069_linked_export_family_writer.sql").read_bytes() == (
        root / "scripts/release_1110/0069_linked_export_family_writer.sql"
    ).read_bytes()
