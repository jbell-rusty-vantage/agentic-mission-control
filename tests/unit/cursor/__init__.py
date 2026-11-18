"""MP-09 / OVE-72: Cursor local/cloud parity and qualification gaps (FIXTURE suites).

Every provider here is a labelled fixture (`tests/support/providers/cursor.FakeCloudApi` behind
`httpx.MockTransport`, `tests/support/providers/cursor.ReplayBridgeLauncher`); nothing proves live
Cursor behaviour and nothing flips `qualified`.
"""
