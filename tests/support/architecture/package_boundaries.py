"""Builders, constants and fakes that other test files import.

Moved from tests/architecture/test_package_boundaries.py.
"""

from __future__ import annotations

# OC-R4 (design §1 application row; §4: nothing outside deployments/<app>/ and the KS binding
# package names an application): the kernel names no application, K01 binding or apply contract
# as a value. Docstrings and comments may cite them; the one place they are named as data is
# deployments/<app>/application.toml.
# Matched case-insensitively as substrings of every non-docstring string constant, f-string
# parts included (`ast.walk` visits a JoinedStr's Constant parts).
APPLICATION_NEEDLES = ("biotech", "ai-engineer", "ai_engineer", "aiengineer", "ingestion-intent")
