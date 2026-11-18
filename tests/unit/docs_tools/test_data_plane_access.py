"""scripts/dev/planes.py: the plane registry and the refusals of `./dev db`, local by default.

No test reaches a remote database: refusals happen before any connection, and the connection
tests point at a closed loopback port, so the driver fails fast and nothing leaves the machine.
"""

from __future__ import annotations

import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "scripts" / "dev" / "planes.py"
SECRET = "s3cret-Value-4242"

spec = importlib.util.spec_from_file_location("dev_planes", MODULE)
assert spec is not None and spec.loader is not None
planes = importlib.util.module_from_spec(spec)
sys.modules["dev_planes"] = planes
spec.loader.exec_module(planes)


def closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


REGISTRY = """
[registry]
workspace = "../ws"
audit_log = ".scratch/planes/audit.jsonl"
installer = "the-installer --apply"
connect_timeout_s = 2

[plane.remote-db]
kind = "postgres"
location = "remote"
posture = "disposable"
project_ref = "abcdefghijklmnopqrst"
[plane.remote-db.roles]
reader = {{ secrets = "remote.env", name = "REMOTE_READER_DSN", missing = "J4: create a reader" }}
admin = {{ secrets = "remote.env", name = "REMOTE_ADMIN_DSN" }}

[plane.kept-db]
kind = "postgres"
location = "remote"
posture = "protected"
project_ref = "keptkeptkeptkeptkept"
[plane.kept-db.roles]
admin = {{ secrets = "remote.env", name = "REMOTE_ADMIN_DSN" }}

[plane.old-graph]
kind = "neo4j"
location = "remote"
posture = "retired"
aura_instance_id = "0000dead"

[plane.local-db]
kind = "postgres"
location = "local"
posture = "disposable"
port = {port}
[plane.local-db.roles]
admin = {{ file = ".env", name = "LOCAL_ADMIN_DSN" }}
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with config/planes.toml, a repo .env and a sibling workspace .secrets."""
    port = closed_port()
    root = tmp_path / "repo"
    (root / "config").mkdir(parents=True)
    (root / "config" / "planes.toml").write_text(REGISTRY.format(port=port), encoding="utf-8")
    (root / ".env").write_text(
        f"LOCAL_ADMIN_DSN=postgresql://admin:{SECRET}@127.0.0.1:{port}/postgres\n",
        encoding="utf-8",
    )
    secrets = tmp_path / "ws" / ".secrets"
    secrets.mkdir(parents=True)
    # The remote admin login carries the project ref in its user name but points at a closed
    # loopback port: the identity guard passes and the connection fails locally.
    (secrets / "remote.env").write_text(
        "REMOTE_ADMIN_DSN="
        f"postgresql://postgres.abcdefghijklmnopqrst:{SECRET}@127.0.0.1:{port}/postgres"
        "?sslmode=require\n",
        encoding="utf-8",
    )
    return root


def run(repo: Path, *args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = planes.main(["--registry", str(repo / "config" / "planes.toml"), *args])
    out, err = capsys.readouterr()
    return code, out, err


# ---------------------------------------------------------------------------------- registry


def test_the_repository_registry_passes_its_check() -> None:
    reg = planes.load()
    assert planes.check(reg) == []
    assert reg.planes["aieng-graph"]["posture"] == "retired"
    assert reg.planes["aieng-graph"]["aura_instance_id"] == "4773dc72"
    assert reg.planes["aieng-db"]["project_ref"] == "wkythqbofmckbuoothhn"
    assert all(p["posture"] in planes.POSTURES for p in reg.planes.values())


def test_check_reports_bad_postures_values_and_disagreements(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "deploy.toml").write_text('[target]\nproject_ref = "other"\n', encoding="utf-8")
    path = tmp_path / "config" / "planes.toml"
    path.write_text(
        "[[registry.agree]]\n"
        'file = "deploy.toml"\nplane = "a"\npairs = { "target.project_ref" = "project_ref" }\n'
        '[plane.a]\nkind = "postgres"\nlocation = "remote"\nposture = "fragile"\n'
        'project_ref = "mine"\npassword = "hunter2"\n'
        'note = "postgresql://u:pw@db.example.com/x"\n'
        '[plane.b]\nkind = "postgres"\nlocation = "local"\nport = 1\n',
        encoding="utf-8",
    )
    problems = planes.check(planes.load(path))
    joined = "\n".join(problems)
    assert "a: posture 'fragile'" in joined
    assert "b: posture None" in joined
    assert "a.password holds a value" in joined
    assert "a URL with an embedded password" in joined
    assert "a.project_ref disagrees with deploy.toml" in joined


def test_list_and_check_run_from_the_registry(repo: Path, capsys) -> None:
    code, out, _ = run(repo, "planes", "list", capsys=capsys)
    assert code == 0
    names = {p["name"] for p in json.loads(out)["planes"]}
    assert names == {"remote-db", "kept-db", "old-graph", "local-db"}
    code, out, _ = run(repo, "planes", "check", capsys=capsys)
    assert code == 0 and json.loads(out)["ok"] is True


def test_show_names_credentials_without_their_values(repo: Path, capsys) -> None:
    code, out, _ = run(repo, "planes", "show", "remote-db", capsys=capsys)
    assert code == 0
    assert SECRET not in out
    roles = json.loads(out)["roles"]
    assert roles["admin"]["names"] == {"REMOTE_ADMIN_DSN": True}
    assert roles["reader"]["names"] == {"REMOTE_READER_DSN": False}
    assert roles["reader"]["owner_todo"] == "J4: create a reader"


# ---------------------------------------------------------------------------------- refusals


def test_no_plane_is_a_usage_error(repo: Path, capsys) -> None:
    with pytest.raises(SystemExit) as stop:
        run(repo, "db", "status", capsys=capsys)
    assert stop.value.code == 2
    assert "--plane" in capsys.readouterr().err


def test_an_unknown_plane_names_the_choices(repo: Path, capsys) -> None:
    code, _, err = run(repo, "db", "status", "--plane", "aieng-db", capsys=capsys)
    assert code == 2 and "UNKNOWN_PLANE" in err and "local-db" in err


@pytest.mark.parametrize(
    "args",
    [
        ("db", "status", "--plane", "old-graph"),
        ("db", "schema", "--plane", "old-graph"),
        ("db", "query", "--plane", "old-graph", "--sql", "match (n) return n"),
    ],
)
def test_a_retired_plane_is_refused_by_every_access_command(repo: Path, capsys, args) -> None:
    code, _, err = run(repo, *args, capsys=capsys)
    assert code == 4 and "PLANE_RETIRED" in err


def test_a_write_on_a_protected_plane_is_refused(repo: Path, capsys) -> None:
    code, _, err = run(
        repo, "db", "query", "--plane", "kept-db", "--sql", "update t set a = 1",
        "--write", "--confirm", "keptkeptkeptkeptkept", "--yes-remote", capsys=capsys,
    )  # fmt: skip
    assert code == 4 and "PLANE_PROTECTED" in err


@pytest.mark.parametrize(
    "sql",
    [
        "create table t (a int)",
        "DROP TABLE public.t",
        "alter table t add column b int",
        "truncate t",
        "grant select on t to anon",
        "do $$ begin perform 1; end $$",
        "select * into t2 from t",
    ],
)
def test_ddl_is_refused_even_with_write_and_points_at_the_installer(
    repo: Path, capsys, sql: str
) -> None:
    code, _, err = run(
        repo, "db", "query", "--plane", "local-db", "--sql", sql,
        "--write", "--confirm", "local-db", capsys=capsys,
    )  # fmt: skip
    assert code == 4 and "DDL_REFUSED" in err and "the-installer --apply" in err


def test_a_remote_read_without_a_reader_needs_yes_remote(repo: Path, capsys) -> None:
    code, _, err = run(repo, "db", "status", "--plane", "remote-db", capsys=capsys)
    assert code == 4
    assert "REMOTE_READ_NEEDS_READER" in err and "J4: create a reader" in err
    assert "--yes-remote" in err
    assert not (repo / ".scratch").exists()


def test_a_remote_write_needs_confirm_and_yes_remote(repo: Path, capsys) -> None:
    base = ("db", "query", "--plane", "remote-db", "--sql", "delete from t", "--write")
    code, _, err = run(repo, *base, capsys=capsys)
    assert code == 4 and "--confirm abcdefghijklmnopqrst" in err
    code, _, err = run(repo, *base, "--confirm", "abcdefghijklmnopqrst", capsys=capsys)
    assert code == 4 and "REMOTE_WRITE" in err


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("insert into t values (1)", "WRITE_NEEDS_FLAG"),
        ("with gone as (delete from t returning *) select * from gone", "WRITE_NEEDS_FLAG"),
        ("select 1; select 2", "ONE_STATEMENT"),
        ("commit", "CONTROL_REFUSED"),
        ("set default_transaction_read_only = off", "CONTROL_REFUSED"),
        ("select pg_terminate_backend(42)", "FUNCTION_REFUSED"),
    ],
)
def test_reads_refuse_writes_control_and_server_calls(
    repo: Path, capsys, sql: str, reason: str
) -> None:
    code, _, err = run(repo, "db", "query", "--plane", "local-db", "--sql", sql, capsys=capsys)
    assert code == 4 and reason in err


def test_quoted_text_and_comments_do_not_change_the_classification() -> None:
    sql = "/* drop table t; */ select 'a; drop table t', $q$delete from t$q$ -- create\n"
    assert planes.classify(sql, write=False, installer="i") == "read"


def test_a_remote_read_prefers_the_reader_when_it_exists(repo: Path) -> None:
    secrets = repo.parent / "ws" / ".secrets" / "remote.env"
    secrets.write_text(
        secrets.read_text(encoding="utf-8") + "REMOTE_READER_DSN=postgresql://r@h/x\n",
        encoding="utf-8",
    )
    reg = planes.load(repo / "config" / "planes.toml")
    role, notice = planes.choose_role(reg, "remote-db", write=False, role=None, yes_remote=False)
    assert (role, notice) == ("reader", None)


# ------------------------------------------------------------------- connections and secrets


def test_a_local_connection_failure_names_no_credential_value(repo: Path, capsys) -> None:
    code, out, err = run(repo, "db", "status", "--plane", "local-db", capsys=capsys)
    assert code == 3 and "CONNECT_FAILED" in err
    assert SECRET not in out + err
    assert not (repo / ".scratch").exists(), "local calls are not audited"


def test_a_local_login_off_loopback_is_refused(repo: Path, capsys) -> None:
    (repo / ".env").write_text(
        f"LOCAL_ADMIN_DSN=postgresql://admin:{SECRET}@db.example.com:5432/postgres\n",
        encoding="utf-8",
    )
    code, out, err = run(repo, "db", "status", "--plane", "local-db", capsys=capsys)
    assert code == 4 and "NOT_LOOPBACK" in err and SECRET not in out + err


def test_a_remote_call_is_audited_by_digest_without_values(repo: Path, capsys) -> None:
    sql = "select 'needle' as probe"
    code, out, err = run(
        repo, "db", "query", "--plane", "remote-db", "--sql", sql, "--yes-remote", capsys=capsys
    )
    assert code == 3 and "CONNECT_FAILED" in err
    assert "no reader login on remote-db" in err
    assert SECRET not in out + err
    lines = (repo / ".scratch" / "planes" / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert {"time", "command", "plane", "role", "mode", "sql_sha256", "rows", "outcome"} <= set(
        entry
    )
    assert (entry["plane"], entry["role"], entry["mode"]) == ("remote-db", "admin", "read")
    assert "needle" not in lines[0] and SECRET not in lines[0]


def test_dev_front_door_delegates_planes_and_db() -> None:
    def dev(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(ROOT / "scripts" / "dev" / "dev_cli.py"), *args],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        )  # fmt: skip

    done = dev("planes", "check")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["ok"] is True
    assert dev("db", "status", "--plane", "aieng-graph").returncode == 4
