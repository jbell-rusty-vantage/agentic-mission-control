"""HL-04 / ADR-0052: the Remote Session Lane base on its own, against scripted fake providers.

Nothing here calls a provider; `cursor_cloud` keeps its own suites (`tests/unit/cursor`,
`tests/unit/harness/test_cursor_cloud.py`), which run unchanged on top of this base.
"""
