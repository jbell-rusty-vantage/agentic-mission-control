"""Shared port contract scenarios: one module per application port (OVE-238 G3).

Each module exports ``SCENARIOS``, async functions that drive a port through its public methods
and assert only what a caller can observe: return values, refusals (error type and code),
idempotent replays, ordering and scoping by tenant and installation. Two thin runners execute
every scenario: a unit test over the ``src`` ``InMemory*`` fake and a ``common_db`` test over
the PostgreSQL adapter. When the two disagree, PostgreSQL is the authority and the fake is fixed
in ``src``; a PostgreSQL defect keeps the documented assertion and its runner is marked
``xfail(strict=True)`` with the file and line of the defect.
"""
