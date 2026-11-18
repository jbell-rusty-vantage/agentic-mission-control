"""Builders, constants and fakes that other test files import.

Moved from tests/unit/domain/knowledge/test_knowledge_identities.py.
"""

from __future__ import annotations

from mission_control.domain.knowledge.effects import EffectIdentity
from mission_control.domain.knowledge.origin import InvocationOrigin

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def origin(**updates: object) -> InvocationOrigin:
    values: dict[str, object] = {
        "issuer": "mc-installation",
        "installation_id": "inst-1",
        "application_id": "ai-engineer",
        "tenant_id": "tenant-1",
        "mission_id": "mission-1",
        "run_id": "run-1",
        "activation_id": "activation-1",
        "operation_id": "goal-iteration/1/executor",
        "attempt": 1,
        "generation": 1,
        "lane": "deep_agents",
        **updates,
    }
    return InvocationOrigin.model_validate(values)


def effect(**updates: object) -> EffectIdentity:
    return EffectIdentity.prepare(
        origin(**updates),
        capability_pin="ai-engineer.research@1:report.publish",
        semantic_payload_digest=DIGEST_A,
        native_payload_digest=DIGEST_B,
    )
