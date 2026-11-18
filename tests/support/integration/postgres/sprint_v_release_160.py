"""Builders, constants and fakes that other test files import.

Moved from tests/integration/postgres/test_sprint_v_release_160.py.
"""

from __future__ import annotations

import json
from uuid import uuid4

RUN_ID = uuid4()
MISSION_ID = uuid4()
HANDLE_INSERT = (
    "INSERT INTO mission_control.knowledge_operation_handle (installation_id,application_id,"
    "tenant_id,handle_id,binding_id,operation,request_id,remote_operation_id,protocol_version,"
    "handle,effect_key,mission_id,run_id,operation_ref,operation_attempt,execution_generation,"
    "invocation_ref,caller_origin,state,remote_revision,version,recorded_at,updated_at,"
    "created_at,created_by_actor_ref) VALUES ($1::uuid,$2,$3,$4,'aiengineer-postgres',$5,$6,$7,"
    "'ks.knowledge_operation.v2',$8::jsonb,$9,$10,$11,'stage:draft',1,1,'invocation:1',"
    "'{\"kind\":\"mission_invocation\"}'::jsonb,$12,$13,1,now(),now(),now(),'fixture:sprint-v') "
    "RETURNING handle_id"
)


def wire_handle(operation_id: str) -> str:
    return json.dumps(
        {
            "protocolVersion": "ks.knowledge_operation.v2",
            "tenant": "t",
            "application": "biotech",
            "binding": "aiengineer-postgres",
            "operationId": operation_id,
        }
    )
