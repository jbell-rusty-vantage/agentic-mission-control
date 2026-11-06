"""Bounded documentation discovery, independent of runtime/provider fixtures."""

from pathlib import Path

from docs.tools import agents_docs_index, okf_search


def test_subsystem_discovery_prunes_before_descent(tmp_path: Path, monkeypatch) -> None:
    """Filtering returned AGENTS paths would still scan these forbidden descendants."""
    excluded = {".claude", ".venv", "node_modules", "app", "fixtures"}
    for name in [*excluded, "src", "tests"]:
        folder = tmp_path / name / "nested"
        folder.mkdir(parents=True)
        (folder / "AGENTS.md").write_text("# Guidance\n", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# Root\n", encoding="utf-8")
    scandir = agents_docs_index.os.scandir
    visited = []

    def bounded_scandir(path):
        relative = Path(path).relative_to(tmp_path)
        assert not excluded.intersection(relative.parts), f"descended into {relative}"
        visited.append(relative.as_posix())
        return scandir(path)

    monkeypatch.setattr(agents_docs_index.os, "scandir", bounded_scandir)
    actual = agents_docs_index.subsystem_guides(tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in actual] == [
        "AGENTS.md",
        "src/nested/AGENTS.md",
        "tests/nested/AGENTS.md",
    ]
    assert set(visited) == {".", "src", "src/nested", "tests", "tests/nested"}


def test_default_search_routes_current_state_ownership_and_transfer() -> None:
    docs = okf_search.load_corpus(okf_search.DEFAULT_ROOTS)
    sprint = "docs/specs/provider-consolidation-2026-10/sprint-oc/"
    questions = [
        ("What is current Sprint OC status and next resume action?", sprint + "NEXT-SESSION.md"),
        (
            "Who owns operational reports versus native AI Engineer and Biotech knowledge?",
            sprint + "APPLICATION-PORTS.md",
        ),
        (
            "What is the exact sealed transfer plan and attempt delivery receipt contract?",
            "docs/adr/0061-one-sealed-transfer-plan-and-attempt-receipts.md",
        ),
    ]
    for question, target in questions:
        results = okf_search.bm25(docs, okf_search.tokenize(question))[:3]
        assert target in [doc.path for _, doc in results], (question, [d.path for _, d in results])
    # The accepted transfer decision must route onward to the typed canonical contract.
    transfer_decision = okf_search.REPO_ROOT / questions[-1][1]
    assert "../knowledge/output-contracts.md" in (transfer_decision.read_text(encoding="utf-8"))
    # The route must not silently grow to include historical audits or kickoff instructions.
    sprint_paths = {doc.path for doc in docs if doc.path.startswith(sprint)}
    assert sprint_paths == {
        sprint + "NEXT-SESSION.md",
        sprint + "APPLICATION-PORTS.md",
    }
