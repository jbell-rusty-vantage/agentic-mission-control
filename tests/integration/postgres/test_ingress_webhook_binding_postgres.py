# ruff: noqa: F811
"""A provider webhook is refused unless its session binding names this lane's live execution.

`ProductionIngressEffects` reads the session binding on the restricted runtime role: a binding
whose product is not the provider's lane is `webhook_product_version_unbound`; one naming a
harness execution that was never opened is `webhook_stale_generation`. The accepted path
(duplicate hint, owner wait, revoked binding) is in test_ingress_drainer_claims.py.
Moved from tests/unit/runtime/test_ingress_drainer_composition.py, which faked the asyncpg pool
and replaced the effects' private frame repository (OVE-238).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from mission_control.application.signals.contracts import TrustTier
from mission_control.application.signals.drainer import DrainRejected
from mission_control.application.signals.ports import SessionBinding
from mission_control.bootstrap.ingress_drainer import ProductionIngressEffects
from mission_control.contracts.identities import mission_operation_id
from tests.support.integration.postgres.signal_ingress_postgres import (
    Ingress,
    ingress,  # noqa: F401
)
from tests.support.unit.signals.drainer import item

pytestmark = pytest.mark.common_db

SESSION = "sesn_binding_fixture"


async def _bind(ingress: Ingress, *, product: str) -> None:
    await ingress.sessions.register(
        SessionBinding(
            request_scope=ingress.scope,
            tier=TrustTier.PROVIDER_OIDC,
            provider="anthropic",
            run_key=ingress.run_key,
            unit_key=ingress.unit_key,
            generation=1,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            session_id=SESSION,
            context={
                "product": product,
                "pins": {"schema": "fixture"},
                # No harness execution was opened for this id.
                "harness_execution_id": str(uuid4()),
                "operation_workflow_id": mission_operation_id(
                    ingress.scope, ingress.run_key, "attempt"
                ),
            },
        ),
        uuid4(),
    )


@pytest.mark.parametrize(
    ("product", "reason"),
    [
        ("wrong_api", "webhook_product_version_unbound"),
        ("claude_managed", "webhook_stale_generation"),
    ],
)
async def test_a_webhook_without_a_live_bound_execution_is_refused(
    ingress: Ingress,
    product: str,
    reason: str,
) -> None:
    await _bind(ingress, product=product)
    effects = ProductionIngressEffects(ingress.runtime, None, None, (ingress.scope,))  # type: ignore[arg-type]
    value = replace(
        item(),
        installation_id=ingress.db.installation_id,
        request_scope=ingress.scope,
        kind="webhook.anthropic",
        payload={"resource_ref": SESSION},
    )
    with pytest.raises(DrainRejected, match=reason):
        await effects.persist(value)
