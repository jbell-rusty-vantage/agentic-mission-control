"""Builders, constants and fakes that other test files import.

Moved from tests/unit/knowledge/test_submission_assessment.py.
"""

from __future__ import annotations

from mission_control.application.outputs.submission_service import OutputSelection, SelectedItem
from tests.fixtures.knowledge_binding import report_package
from tests.support.knowledge import TENANT


def report_selection(report_id: str = "report-7") -> OutputSelection:
    package = report_package(report_id, "1", tenant=TENANT)
    report = package.report
    return OutputSelection(
        items=(
            SelectedItem(
                kind="handle",
                ref=f"kh:{report.binding}/report/{report.id}@{report.version}",
                digest=report.digest,
            ),
        )
    )
