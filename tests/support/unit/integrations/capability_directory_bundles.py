"""Builders, constants and fakes that other test files import.

Moved from tests/unit/integrations/test_capability_directory_bundles.py.
"""

from pathlib import Path


def source(tmp_path: Path) -> Path:
    path = tmp_path / "source"
    path.mkdir()
    (path / "SKILL.md").write_bytes(b"---\nname: fixture\ndescription: test\n---\n")
    (path / ".config").write_bytes(b"complete hidden file")
    (path / "assets").mkdir()
    (path / "assets" / "image.bin").write_bytes(b"\x00\xff\x01")
    return path
