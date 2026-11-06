"""``tenant-plan`` / ``tenant-apply`` (Sprint OC W1 defect D8) on a Supabase-like cluster B.

The installer is the NON-superuser CREATEROLE migration principal, as on Supabase. The tenant
ids come only from the operator deployment file's grants for the target's own binding.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from conftest import VERSIONS, run, write_target
from test_install import install

from mission_control_db_contract.cli import build_parser, main
from mission_control_db_contract.errors import ContractError
from mission_control_db_contract.target import load_target
from mission_control_db_contract.tenants import (
    binding_digest,
    deployment_tenants,
    external_ref,
    tenant_apply,
    tenant_plan,
)


def _confirm(target: dict[str, str]) -> str:
    return f"{target['project_ref']}:{target['installation_id']}"


def deployment(path: Path, target: dict[str, str], tenants: list[str], **binding: Any) -> Path:
    document = {
        "storage_mode": "production_common",
        "max_request_bytes": 1000,
        "applications": [
            {
                "authentication": {
                    "binding": {
                        "application_id": target["application_id"],
                        "installation_id": target["installation_id"],
                        "supabase_project_ref": target["project_ref"],
                        "database_secret_ref": "MC_RUNTIME_DSN",
                        "accepted_issuers": ["mission-control-operator/biotech"],
                        "accepted_audiences": ["mission-control/biotech"],
                        **binding,
                    },
                    "issuer": "mission-control-operator/biotech",
                    "grants": [
                        {"subject": "operator", "actor_id": "operator:x", "tenant_ids": tenants},
                        {"subject": "reader", "actor_id": "reader:x", "tenant_ids": tenants[:1]},
                    ],
                }
            },
            {
                "authentication": {
                    "binding": {
                        "application_id": "other-app",
                        "installation_id": str(uuid.uuid4()),
                    },
                    "grants": [{"tenant_ids": [str(uuid.uuid4())]}],
                }
            },
        ],
    }
    sealed = document["applications"][0]["authentication"]["binding"]
    sealed.setdefault("binding_digest", binding_digest(sealed))
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.fixture
def installed(make_db, release, tmp_path, monkeypatch):
    db = make_db("B")
    target = load_target(write_target(tmp_path, db, monkeypatch=monkeypatch))
    install(target, release)
    return db, target


async def _runtime_sees(db: Any, target: dict[str, str], tenant: str) -> list[Any]:
    connection = await db.connect()
    try:
        async with connection.transaction():
            await connection.execute("SET LOCAL ROLE mission_control_runtime")
            await connection.execute(
                "SELECT set_config('mc.installation_id',$1,true), "
                "set_config('mc.application_id',$2,true), set_config('mc.tenant_id',$3,true)",
                target["installation_id"],
                target["application_id"],
                tenant,
            )
            return list(
                await connection.fetch(
                    "SELECT tenant_id::text, state, external_tenant_ref, qualification_fixture, "
                    "created_by_actor_ref FROM mission_control.tenant"
                )
            )
    finally:
        await connection.close()


def test_plan_apply_repeat_and_receipt(installed, release, tmp_path):
    db, target = installed
    tenants = sorted([str(uuid.uuid4()), str(uuid.uuid4())])
    file = deployment(tmp_path / "deployment.json", target, [tenants[1], tenants[0].upper()])
    plan = run(tenant_plan(target, release, file, **VERSIONS))
    assert plan["status"] == "pending"
    assert [entry["status"] for entry in plan["tenants"]] == ["absent", "absent"]
    assert [entry["tenant_id"] for entry in plan["tenants"]] == tenants
    assert len(plan["mutations"]) == 2
    receipt = run(tenant_apply(target, release, file, confirmation=_confirm(target), **VERSIONS))
    assert receipt["format"] == "mission-control-tenant-receipt/v1"
    assert receipt["changed"] is True
    assert [entry["action"] for entry in receipt["tenants"]] == ["created", "created"]
    assert receipt["deployment_digest"].startswith("sha256:")
    assert "MC_RUNTIME_DSN" not in json.dumps(receipt)
    for tenant in tenants:
        rows = run(_runtime_sees(db, target, tenant))
        assert [tuple(row) for row in rows] == [
            (tenant, "active", external_ref("biotech", tenant), False, "mission-db:tenant-apply")
        ]
    again = run(tenant_plan(target, release, file, **VERSIONS))
    assert again["status"] == "complete" and again["mutations"] == []
    repeat = run(tenant_apply(target, release, file, confirmation=_confirm(target), **VERSIONS))
    assert repeat["changed"] is False
    assert [entry["action"] for entry in repeat["tenants"]] == ["verified", "verified"]
    # Exactly the deployment's tenants: the other application's grant was never read as ours.
    count = run(db.fetchval("SELECT count(*) FROM mission_control.tenant"))
    assert count == 2


def test_refusals_change_nothing(installed, release, tmp_path):
    db, target = installed
    tenant = str(uuid.uuid4())
    file = deployment(tmp_path / "deployment.json", target, [tenant])
    with pytest.raises(ContractError, match="confirmation"):
        run(tenant_apply(target, release, file, confirmation="x:y", **VERSIONS))
    wrong = deployment(tmp_path / "wrong.json", target, [tenant], installation_id=str(uuid.uuid4()))
    for call in (
        lambda: run(tenant_plan(target, release, wrong, **VERSIONS)),
        lambda: run(
            tenant_apply(target, release, wrong, confirmation=_confirm(target), **VERSIONS)
        ),
    ):
        with pytest.raises(ContractError) as refused:
            call()
        assert refused.value.code == "TENANT_DEPLOYMENT_MISMATCH"
    other_project = deployment(
        tmp_path / "project.json", target, [tenant], supabase_project_ref="another-project"
    )
    with pytest.raises(ContractError) as refused:
        deployment_tenants(other_project, target)
    assert refused.value.code == "TENANT_DEPLOYMENT_MISMATCH"
    empty = deployment(tmp_path / "empty.json", target, [])
    with pytest.raises(ContractError) as refused:
        deployment_tenants(empty, target)
    assert refused.value.code == "TENANT_DEPLOYMENT_INVALID"
    tampered = deployment(
        tmp_path / "tampered.json", target, [tenant], binding_digest="sha256:" + "b" * 64
    )
    with pytest.raises(ContractError) as refused:
        deployment_tenants(tampered, target)
    assert refused.value.code == "TENANT_BINDING_DIGEST_MISMATCH"
    edited = json.loads(file.read_text(encoding="utf-8"))
    edited["applications"][0]["authentication"]["binding"]["accepted_audiences"] = ["other"]
    (tmp_path / "edited.json").write_text(json.dumps(edited), encoding="utf-8")
    with pytest.raises(ContractError) as refused:
        deployment_tenants(tmp_path / "edited.json", target)
    assert refused.value.code == "TENANT_BINDING_DIGEST_MISMATCH"
    malformed = deployment(tmp_path / "bad.json", target, ["not-a-uuid"])
    with pytest.raises(ContractError) as refused:
        deployment_tenants(malformed, target)
    assert refused.value.code == "TENANT_DEPLOYMENT_INVALID"
    assert run(db.fetchval("SELECT count(*) FROM mission_control.tenant")) == 0


def test_a_retired_tenant_holds_and_is_never_revived(installed, release, tmp_path):
    db, target = installed
    tenant = str(uuid.uuid4())
    file = deployment(tmp_path / "deployment.json", target, [tenant])
    run(tenant_apply(target, release, file, confirmation=_confirm(target), **VERSIONS))

    async def retire() -> None:
        connection = await db.connect()
        try:
            await connection.execute(
                "UPDATE mission_control.tenant SET state='retired' WHERE tenant_id=$1::uuid",
                tenant,
            )
        finally:
            await connection.close()

    run(retire())
    plan = run(tenant_plan(target, release, file, **VERSIONS))
    assert plan["status"] == "hold" and plan["tenants"][0]["status"] == "drift"
    with pytest.raises(ContractError) as refused:
        run(tenant_apply(target, release, file, confirmation=_confirm(target), **VERSIONS))
    assert refused.value.code == "TENANT_HOLD"
    assert run(db.fetchval("SELECT state FROM mission_control.tenant")) == "retired"


def test_an_existing_row_of_the_scope_is_verified_with_its_own_reference(
    installed, release, tmp_path
):
    db, target = installed
    tenant = str(uuid.uuid4())

    async def existing() -> None:
        connection = await db.connect()
        try:
            await connection.execute(
                "INSERT INTO mission_control.tenant (installation_id, application_id, tenant_id, "
                "external_tenant_ref, state, qualification_fixture, created_at, "
                "created_by_actor_ref) VALUES ($1::uuid, $2, $3::uuid, 'elsewhere', 'active', "
                "true, now(), 'fixture')",
                target["installation_id"],
                target["application_id"],
                tenant,
            )
        finally:
            await connection.close()

    run(existing())
    file = deployment(tmp_path / "deployment.json", target, [tenant])
    plan = run(tenant_plan(target, release, file, **VERSIONS))
    assert plan["tenants"][0]["status"] == "present" and plan["status"] == "complete"
    receipt = run(tenant_apply(target, release, file, confirmation=_confirm(target), **VERSIONS))
    assert receipt["changed"] is False
    assert receipt["tenants"][0] == {
        "tenant_id": tenant,
        "action": "verified",
        "external_tenant_ref": "elsewhere",
    }
    assert run(db.fetchval("SELECT count(*) FROM mission_control.tenant")) == 1


def test_cli_parses_and_reports_tenant_commands(installed, release, release_work, tmp_path, capsys):
    _db, target = installed
    work, _component = release_work
    parser = build_parser()
    args = parser.parse_args(
        [
            "tenant-apply",
            "--target",
            "t.toml",
            "--lock",
            "l.json",
            "--reader-version",
            "r",
            "--writer-version",
            "w",
            "--deployment-file",
            "d.json",
            "--confirm-target",
            "p:i",
            "--receipt-out",
            "out.json",
        ]
    )
    assert args.command == "tenant-apply" and args.deployment_file == Path("d.json")
    with pytest.raises(SystemExit):
        parser.parse_args(["tenant-apply", "--deployment-file", "d.json"])
    file = deployment(tmp_path / "deployment.json", target, [str(uuid.uuid4())])
    target_file = next(tmp_path.glob("target-*.toml"))
    common = [
        "--target",
        str(target_file),
        "--lock",
        str(work / "deployments" / "biotech" / "release.lock.json"),
        "--release-root",
        str(release.release_root),
        "--reader-version",
        VERSIONS["reader_version"],
        "--writer-version",
        VERSIONS["writer_version"],
        "--deployment-file",
        str(file),
    ]
    assert main(["tenant-plan", *common]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "pending"
    receipt = tmp_path / "receipt.json"
    assert main(["tenant-apply", *common, "--confirm-target", "x:y"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    assert (
        main(
            [
                "tenant-apply",
                *common,
                "--confirm-target",
                _confirm(target),
                "--receipt-out",
                str(receipt),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["changed"] is True
    assert json.loads(receipt.read_text(encoding="utf-8"))["status"] == "complete"
    assert main(["tenant-plan", *common]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "complete"
