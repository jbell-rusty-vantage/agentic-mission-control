"""Deployment tenants (``tenant-plan`` / ``tenant-apply``), Sprint OC W1 defect D8.

Every tenant-scoped Mission Control row references ``mission_control.tenant``. ``mission-db apply``
creates the installation identity but no tenant, seed bundles allocate their own UUIDv7 tenant ids
(``seed_identity``), and the runtime never inserts one: it authorizes a principal from the operator
``MissionDeployment`` file (``applications[].authentication.grants[].tenant_ids``) and writes rows
under that tenant id. Without the row, every submit failed on the ``mission`` foreign key.

``tenant-plan`` (read-only) and ``tenant-apply`` provision exactly the tenant ids the deployment
file grants for the target's application, nothing else. The deployment's sealed binding must name
the target's ``application_id``, ``installation_id`` and ``project_ref``. Each row is ``active``,
``qualification_fixture = false``, ``external_tenant_ref = deployment:<application>:<tenant>`` and
``created_by_actor_ref = mission-db:tenant-apply``. No actor binding or grant row is written: the
runtime reads neither (authorization comes from the deployment file); the seed kinds
``actor_binding``/``actor_grant`` remain the route for those records.

Gates are the ones of ``runtime-apply`` and ``login-apply``: the common component must verify
against the lock (identity, fingerprint, receipts), apply needs the exact
``<project_ref>:<installation_id>`` confirmation, one transaction holds a transaction-scoped
advisory lock and re-inspects before writing, and a tenant row that is not ``active`` is reported
as drift and never revived. A rerun changes nothing and reports ``verified``. The receipt carries
names, ids and digests only.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from .errors import ContractError, sqlstate
from .integrity import Release
from .runtime import _verified_common
from .target import close_quietly, connect, public_identity

RECEIPT_FORMAT = "mission-control-tenant-receipt/v1"
CREATED_BY = "mission-db:tenant-apply"
XACT_LOCK_SQL = (
    "SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended("
    "'mission_control_tenants.provision', 0))"
)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# The sealed `ApplicationBinding` content (MC `application/installations/registry.py`): the
# digest covers the fields that are set, encoded as MC `contracts/canonical.py` does (sorted
# keys, compact separators, NFC strings, set-typed fields sorted by their encoding). This
# package never imports the runtime; `tests/unit/operations/test_tenant_binding_digest.py`
# pins the parity against `ApplicationBinding.seal`.
_BINDING_FIELDS = (
    "application_id",
    "installation_id",
    "binding_version",
    "supabase_project_ref",
    "database_secret_ref",
    "accepted_issuers",
    "accepted_audiences",
    "required_component_version",
    "hosted_agent_apis",
)
_BINDING_SETS = ("accepted_issuers", "accepted_audiences")


def _encode(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def _nfc(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {unicodedata.normalize("NFC", key): _nfc(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_nfc(item) for item in value]
    return value


def _as_set(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(
            "deployment binding set field is not a list", code="TENANT_DEPLOYMENT_INVALID"
        )
    return sorted((_nfc(item) for item in value), key=_encode)


def binding_digest(binding: dict[str, Any]) -> str:
    """Recompute the sealed binding digest of a deployment file's binding JSON."""

    unknown = set(binding) - {*_BINDING_FIELDS, "binding_digest"}
    if unknown:
        raise ContractError(
            f"deployment binding has unknown fields {sorted(unknown)}",
            code="TENANT_DEPLOYMENT_INVALID",
        )
    content: dict[str, Any] = {}
    for name in _BINDING_FIELDS:
        value = binding.get(name)
        if value is None:
            continue
        if name in _BINDING_SETS:
            value = _as_set(value)
        elif name == "hosted_agent_apis":
            if not isinstance(value, dict):
                raise ContractError(
                    "deployment binding hosted_agent_apis is not an object",
                    code="TENANT_DEPLOYMENT_INVALID",
                )
            classes = value.get("widened_data_classes") or {}
            if not isinstance(classes, dict):
                raise ContractError(
                    "deployment binding widened_data_classes is not an object",
                    code="TENANT_DEPLOYMENT_INVALID",
                )
            value = {
                **_nfc(value),
                "widened_data_classes": {
                    unicodedata.normalize("NFC", key): _as_set(item)
                    for key, item in classes.items()
                },
            }
        else:
            value = _nfc(value)
        content[name] = value
    return "sha256:" + hashlib.sha256(_encode(content).encode("utf-8")).hexdigest()


_CONTEXT_SQL = (
    "SELECT set_config('mc.installation_id',$1,true), set_config('mc.application_id',$2,true), "
    "set_config('mc.tenant_id',$3,true)"
)
_ROW_SQL = (
    "SELECT state, external_tenant_ref, qualification_fixture FROM mission_control.tenant "
    "WHERE installation_id=$1::uuid AND application_id=$2 AND tenant_id=$3::uuid"
)


def external_ref(application_id: str, tenant: str) -> str:
    return f"deployment:{application_id}:{tenant}"


def deployment_tenants(path: Path, target: dict[str, str]) -> dict[str, Any]:
    """The tenant ids the deployment file grants for the target's application.

    Reads only the sealed binding identity and the grants' ``tenant_ids``; every other field of
    the file is ignored and never echoed. The binding digest is recomputed and must equal the
    sealed one, so a hand-edited binding (another installation, project or tenant scope) refuses.
    """

    raw = path.read_bytes()
    try:
        document = json.loads(raw)
    except ValueError:
        raise ContractError(
            "deployment file is not JSON", code="TENANT_DEPLOYMENT_INVALID"
        ) from None
    applications = document.get("applications") if isinstance(document, dict) else None
    if not isinstance(applications, list):
        raise ContractError(
            "deployment file names no applications", code="TENANT_DEPLOYMENT_INVALID"
        )
    matches = []
    for item in applications:
        authentication = item.get("authentication") if isinstance(item, dict) else None
        binding = authentication.get("binding") if isinstance(authentication, dict) else None
        if isinstance(binding, dict) and binding.get("application_id") == target["application_id"]:
            matches.append((authentication, binding))
    if len(matches) != 1:
        raise ContractError(
            f"deployment file must hold exactly one application {target['application_id']}",
            code="TENANT_DEPLOYMENT_MISMATCH",
        )
    authentication, binding = matches[0]
    sealed = binding.get("binding_digest")
    if not isinstance(sealed, str) or binding_digest(binding) != sealed:
        raise ContractError(
            "deployment binding digest does not match its sealed content",
            code="TENANT_BINDING_DIGEST_MISMATCH",
        )
    if str(binding.get("installation_id", "")).lower() != target["installation_id"].lower():
        raise ContractError(
            "deployment binding names another installation than the target",
            code="TENANT_DEPLOYMENT_MISMATCH",
        )
    if binding.get("supabase_project_ref") != target["project_ref"]:
        raise ContractError(
            "deployment binding names another project than the target",
            code="TENANT_DEPLOYMENT_MISMATCH",
        )
    tenants: set[str] = set()
    grants = authentication.get("grants")
    for grant in grants if isinstance(grants, list) else ():
        values = grant.get("tenant_ids") if isinstance(grant, dict) else None
        for value in values if isinstance(values, list) else ():
            text = str(value).lower()
            if not _UUID.fullmatch(text):
                raise ContractError(
                    "deployment grant names a malformed tenant id",
                    code="TENANT_DEPLOYMENT_INVALID",
                )
            tenants.add(str(UUID(text)))
    if not tenants:
        raise ContractError(
            "deployment grants name no tenant for this application",
            code="TENANT_DEPLOYMENT_INVALID",
        )
    return {
        "tenants": sorted(tenants),
        "deployment_digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "binding_digest": binding.get("binding_digest"),
    }


async def _inspect(
    connection: Any, target: dict[str, str], tenants: list[str]
) -> list[dict[str, Any]]:
    """Per tenant: ``absent``, ``present`` (active) or ``drift`` (suspended/retired)."""

    entries = []
    for tenant in tenants:
        async with connection.transaction():
            await connection.execute(
                _CONTEXT_SQL, target["installation_id"], target["application_id"], tenant
            )
            row = await connection.fetchrow(
                _ROW_SQL, target["installation_id"], target["application_id"], tenant
            )
        entry: dict[str, Any] = {"tenant_id": tenant}
        if row is None:
            entry["status"] = "absent"
        else:
            entry["external_tenant_ref"] = row["external_tenant_ref"]
            entry["state"] = row["state"]
            entry["status"] = "present" if row["state"] == "active" else "drift"
        entries.append(entry)
    return entries


def _holds(entries: list[dict[str, Any]]) -> list[str]:
    return [
        f"tenant {entry['tenant_id']} exists in state {entry['state']}; it is never revived"
        for entry in entries
        if entry["status"] == "drift"
    ]


async def tenant_plan(
    target: dict[str, str],
    release: Release,
    deployment_file: Path,
    *,
    reader_version: str,
    writer_version: str,
) -> dict[str, Any]:
    """Read-only: which of the deployment's tenants are absent, present or drifted."""

    wanted = deployment_tenants(deployment_file, target)
    connection = await connect(target, readonly=True)
    try:
        await _verified_common(connection, target, release, reader_version, writer_version)
        entries = await _inspect(connection, target, wanted["tenants"])
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError(f"Tenant planning failed (SQLSTATE {sqlstate(exc)})") from None
    finally:
        await close_quietly(connection)
    holds = _holds(entries)
    complete = all(entry["status"] == "present" for entry in entries)
    return {
        "status": "hold" if holds else ("complete" if complete else "pending"),
        "target": public_identity(target),
        "deployment_digest": wanted["deployment_digest"],
        "binding_digest": wanted["binding_digest"],
        "tenants": entries,
        "holds": holds,
        "mutations": [
            f"insert active tenant {entry['tenant_id']}"
            for entry in entries
            if entry["status"] == "absent"
        ],
    }


async def tenant_apply(
    target: dict[str, str],
    release: Release,
    deployment_file: Path,
    *,
    confirmation: str,
    reader_version: str,
    writer_version: str,
) -> dict[str, Any]:
    """Insert the deployment's absent tenants in one locked, re-inspected transaction."""

    if confirmation != f"{target['project_ref']}:{target['installation_id']}":
        raise ContractError(
            "Tenant apply requires exact project-ref:installation-UUID confirmation"
        )
    wanted = deployment_tenants(deployment_file, target)
    connection = await connect(target, readonly=False, statement_timeout_ms=60000)
    actions: dict[str, str] = {}
    refs: dict[str, str] = {}
    try:
        await _verified_common(connection, target, release, reader_version, writer_version)
        before = await _inspect(connection, target, wanted["tenants"])
        holds = _holds(before)
        if holds:
            raise ContractError("; ".join(holds), code="TENANT_HOLD")
        async with connection.transaction():
            await connection.execute(XACT_LOCK_SQL)
            again = await _inspect(connection, target, wanted["tenants"])
            if [e["status"] for e in again] != [e["status"] for e in before]:
                raise ContractError("tenants changed concurrently; rerun", code="TENANT_CONCURRENT")
            for entry in again:
                tenant = entry["tenant_id"]
                if entry["status"] == "present":
                    actions[tenant] = "verified"
                    continue
                await connection.execute(
                    _CONTEXT_SQL, target["installation_id"], target["application_id"], tenant
                )
                try:
                    async with connection.transaction():  # savepoint: name the conflict
                        await connection.execute(
                            "INSERT INTO mission_control.tenant (installation_id, application_id, "
                            "tenant_id, external_tenant_ref, state, qualification_fixture, "
                            "created_at, created_by_actor_ref) VALUES ($1::uuid, $2, $3::uuid, $4, "
                            "'active', false, clock_timestamp(), $5)",
                            target["installation_id"],
                            target["application_id"],
                            tenant,
                            external_ref(target["application_id"], tenant),
                            CREATED_BY,
                        )
                except Exception as exc:
                    if sqlstate(exc) == "23505":
                        raise ContractError(
                            f"tenant {tenant} or its external reference already exists outside "
                            "this installation scope",
                            code="TENANT_CONFLICT",
                        ) from None
                    raise
                actions[tenant] = "created"
            after = await _inspect(connection, target, wanted["tenants"])
            if any(entry["status"] != "present" for entry in after):
                raise ContractError(
                    "a tenant does not verify after apply", code="TENANT_UNVERIFIED"
                )
            refs = {entry["tenant_id"]: entry["external_tenant_ref"] for entry in after}
    except ContractError:
        raise
    except Exception as exc:
        raise ContractError(f"Tenant apply failed (SQLSTATE {sqlstate(exc)})") from None
    finally:
        await close_quietly(connection)
    return {
        "format": RECEIPT_FORMAT,
        "status": "complete",
        "target": public_identity(target),
        "deployment_digest": wanted["deployment_digest"],
        "binding_digest": wanted["binding_digest"],
        "tenants": [
            {
                "tenant_id": tenant,
                "action": actions[tenant],
                "external_tenant_ref": refs[tenant],
            }
            for tenant in wanted["tenants"]
        ],
        "changed": any(action == "created" for action in actions.values()),
        "finished_at": datetime.now(UTC).isoformat(),
    }


__all__ = ["binding_digest", "deployment_tenants", "external_ref", "tenant_apply", "tenant_plan"]
