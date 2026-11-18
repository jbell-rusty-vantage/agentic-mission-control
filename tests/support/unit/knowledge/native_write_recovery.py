"""Builders, constants and fakes that other test files import.

Moved from tests/unit/knowledge/test_native_write_recovery.py.
"""

from mission_control.application.knowledge.native_write import NativePlanDigest
from mission_control.contracts.knowledge_protocol import digest_canonical
from tests.support.unit.knowledge.native_write import Preview
from tests.unit.outputs.scenario import digest_of


class IntentPreview(Preview):
    async def preview(self, plan, *, effect_key, access):
        self.calls.append((dict(plan), effect_key))
        return NativePlanDigest(
            digest_of("payload"),
            digest_canonical(dict(plan)),
            normalized_values_digest=digest_canonical({}),
            processed_epoch=1,
        )
