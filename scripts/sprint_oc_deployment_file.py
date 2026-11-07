"""Write the operator ``MissionDeployment`` of one application for the local W1 topology (OVE-169).

``scripts/sprint_oc_runtime_env.py --deployment-file`` consumes the file. Everything it holds is
derived, never a secret:

* the sealed ``ApplicationBinding`` (``bootstrap/api.py``): ``deployments/<app>/target.toml``'s
  ``installation_id`` and ``project_ref``, ``database_secret_ref = MC_<APP>_RUNTIME_DSN``,
  ``family_writer_secret_ref = MC_<APP>_FAMILY_WRITER_DSN`` (the generator fills both names from
  the integrator's restricted logins), the operator issuer and audience, and the installed common
  component version (``--component-version``);
* the operator's own EdDSA issuer: a minted Ed25519 key whose private JWK stays owner-only in the
  ignored runtime directory and whose public JWKS the deployment names; one ``ActorGrant`` for the
  operator subject on the knowledge-verification tenant of ``minted.env`` (W1 grants must use
  that tenant, RUNTIME-ENVIRONMENT section 6), including ``knowledge.review`` (W1 D2: the
  operator review route; the actor is never the run's producer or evaluators);
* Temporal: ``127.0.0.1:7233``, the profile's queue base (``application.toml``
  ``temporal_task_queue``) and a per-application namespace (default ``mc-<app>``). Both profiles
  name the queue ``biotech-research-ingestion``; distinct namespaces keep the two worker sets
  apart. Create the namespace and register the Search Attributes before the worker starts.

A second grant names the separate reviewer principal (``sprint-oc-reviewer``, actor
``reviewer:sprint-oc``: ``knowledge.review``, ``reviewer:owner`` for the human gates and reads, no
launch): the launcher never reviews its
own run's KS decision (W1 review S4); ``reviewer-grant`` prints (``--run``: executes) the KS
``knowledge-verify grant-reviewer`` command that gives it the live KS reviewer grant (without it KS
refuses ``reviewer_not_qualified``). ``token`` mints a short-lived operator bearer into
``<out>/operator-token.txt``; ``token --role reviewer`` the reviewer's into
``<out>/reviewer-token.txt`` (both owner-only). Output
is names, paths and digests only; exit 0 = written, 2 = refused.

    uv run --no-sync python scripts/sprint_oc_deployment_file.py --app biotech \
      --component-version 1.7.0
    uv run --no-sync python scripts/sprint_oc_deployment_file.py --app biotech token
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import secrets
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

MC_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "mc.operator_deployment.v1"
TEMPORAL_ADDRESS = "127.0.0.1:7233"
OPERATOR_SUBJECT = "sprint-oc-operator"
OPERATOR_ACTOR = "operator:sprint-oc"
OPERATOR_KEY = "operator-issuer.jwk.json"
OPERATOR_JWKS = "operator-jwks.json"
DEPLOYMENT = "deployment.json"
TOKEN = "operator-token.txt"  # noqa: S105 (a file name)
# W1 review S4: the launcher never approves its own run's KS decision, so a review is made by a
# second principal: knowledge.review and reads only, never launch or run control.
REVIEWER_SUBJECT = "sprint-oc-reviewer"
REVIEWER_ACTOR = "reviewer:sprint-oc"
REVIEWER_TOKEN = "reviewer-token.txt"  # noqa: S105 (a file name)
# Loop iter-1 L1-04: the loop fixtures' human gates name `reviewers: [owner]`; `is_reviewer`
# (domain/programs/human_gate.py) admits the actor `owner` or the permission `reviewer:owner`.
REVIEWER_PERMISSIONS = frozenset(
    {"knowledge.review", "workflow_run.read", "mission.read", "reviewer:owner"}
)
ROLES = {"operator": (OPERATOR_SUBJECT, TOKEN), "reviewer": (REVIEWER_SUBJECT, REVIEWER_TOKEN)}
# Launch, inspection, transcript bodies, checkpoint summaries and run controls for one operator.
EXTRA_PERMISSIONS = frozenset(
    {
        "workflow.launch",
        "workflow.prepare",
        "workflow.design.validate",
        "workflow.result.read",
        "workflow_run.control",
        "mission.read",
        "catalog.read",
        "capability.inspect",
        "capability.discover",
        # W1 D2: the operator reviews an exact KS use decision (`knowledge-reviews` route).
        # KS still requires a live reviewer grant for this actor (the reviewer qualification).
        "knowledge.review",
        # W1 stuck cancels: an immediate cancel of active or cancelling work requires
        # `workflow_run.admin` (`domain/policies/stop_fence.immediate_cancel_permissions`).
        # This is the disposable sprint's only operator, so it holds it.
        "workflow_run.admin",
        # Loop iter-3 F1: snapshot, fork and the derived run's admission (`run fork --point`,
        # application/recovery/run_forks.py FORK/SNAPSHOT/ADMIT_PERMISSION).
        "workflow_run.snapshot",
        "workflow_run.fork",
        "workflow_run.admit",
    }
)


def _generator() -> ModuleType:
    """The runtime-env generator (shared refusals, ignore guard and owner-only writer)."""

    name = "sprint_oc_runtime_env"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gen = _generator()
Refused = gen.Refused


def issuer(app: str) -> str:
    return f"mission-control-operator/{app}"


def audience(app: str) -> str:
    return f"mission-control/{app}"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Refused("PROFILE_INVALID", f"{path} is not readable TOML") from error


def ensure_operator_key(out: Path) -> tuple[str, dict[str, Any]]:
    """Reuse the operator's private JWK, or mint one; return (kid, public JWKS)."""

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    path = out / OPERATOR_KEY
    if path.is_file():
        # Review N5: a reused private key must still be ignored and owner-only.
        gen.assert_ignored(path)
        gen._harden(path)
        try:
            private = json.loads(path.read_text(encoding="utf-8"))
            kid, x = private["kid"], private["x"]
        except (OSError, ValueError, KeyError) as error:
            raise Refused("OPERATOR_KEY_INVALID", f"{path} is not an OKP JWK") from error
    else:
        key = Ed25519PrivateKey.generate()
        raw_private = key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )
        raw_public = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        kid = f"mc-operator-{secrets.token_hex(4)}"
        x = _b64url(raw_public)
        document = {"kty": "OKP", "crv": "Ed25519", "x": x, "d": _b64url(raw_private), "kid": kid}
        gen.write_text(path, json.dumps(document, sort_keys=True) + "\n", secret=True)
    public = {"kty": "OKP", "crv": "Ed25519", "x": x, "kid": kid, "alg": "EdDSA", "use": "sig"}
    return kid, {"keys": [public]}


def tenant_from(out: Path, explicit: str | None) -> str:
    tenant = explicit or gen.read_env(out / "minted.env").get("KNOWLEDGE_VERIFICATION_TENANT_ID")
    if not tenant or not gen.UUID.match(tenant):
        raise Refused(
            "TENANT_MISSING",
            "no tenant: run sprint_oc_runtime_env.py first (minted.env) or pass --tenant",
        )
    return tenant


def deployment_document(
    mc_root: Path,
    app: str,
    *,
    component_version: str,
    namespace: str,
    tenant: str,
    max_request_bytes: int = 1_000_000,
    signal_ingress: bool = False,
) -> dict[str, Any]:
    from mission_control.adapters.temporal.coordinator_runtime import coordinator_task_queues
    from mission_control.application.installations.registry import ApplicationBinding
    from mission_control.interfaces.http.run_control import ROLE_PERMISSIONS

    target = _toml(mc_root / "deployments" / app / "target.toml")["target"]
    profile = _toml(mc_root / "deployments" / app / "application.toml")["installation"]
    upper = app.upper().replace("-", "_")
    binding = ApplicationBinding.seal(
        application_id=app,
        installation_id=target["installation_id"],
        binding_version=f"sprint-oc-w1/{component_version}",
        supabase_project_ref=target["project_ref"],
        database_secret_ref=f"MC_{upper}_RUNTIME_DSN",
        accepted_issuers={issuer(app)},
        accepted_audiences={audience(app)},
        required_component_version=component_version,
    )
    queues = coordinator_task_queues(profile["temporal_task_queue"])
    permissions = sorted(
        ROLE_PERMISSIONS["operator"] | ROLE_PERMISSIONS["state_inspector"] | EXTRA_PERMISSIONS
    )
    return {
        "storage_mode": "production_common",
        "max_request_bytes": max_request_bytes,
        "applications": [
            {
                "authentication": {
                    "binding": binding.model_dump(mode="json"),
                    "issuer": issuer(app),
                    "audience": audience(app),
                    "public_jwks_file": OPERATOR_JWKS,
                    "algorithms": ["EdDSA"],
                    "grants": [
                        {
                            "subject": OPERATOR_SUBJECT,
                            "actor_id": OPERATOR_ACTOR,
                            "tenant_ids": [tenant],
                            "permissions": permissions,
                            "authority_refs": ["authority:lifecycle"],
                            "sponsorship_refs": ["sponsorship:sprint-oc-w1"],
                            "approval_refs": ["approval:sprint-oc-w1"],
                        },
                        {
                            "subject": REVIEWER_SUBJECT,
                            "actor_id": REVIEWER_ACTOR,
                            "tenant_ids": [tenant],
                            "permissions": sorted(REVIEWER_PERMISSIONS),
                        },
                    ],
                },
                "family_writer_secret_ref": f"MC_{upper}_FAMILY_WRITER_DSN",
                # Loop iter-3: the restricted signal-ingress login (mission-db login-apply
                # `MC_INGRESS_DSN`) the worker needs to compose the hosted lanes.
                **(
                    {"signal_ingress_secret_ref": f"MC_{upper}_INGRESS_DSN"}
                    if signal_ingress
                    else {}
                ),
                "temporal": {
                    "address": TEMPORAL_ADDRESS,
                    "namespace": namespace,
                    "root_task_queue": queues.stagegraph,
                    "stagegraph_task_queue": queues.stagegraph,
                    "goal_directed_task_queue": queues.goal_directed,
                },
            }
        ],
    }


def mint_token(
    out: Path,
    app: str,
    *,
    tenant: str,
    ttl_minutes: int,
    now: int | None = None,
    subject: str = OPERATOR_SUBJECT,
) -> str:
    """An EdDSA bearer for ``subject`` (the operator, or the separate reviewer) on ``app`` and
    ``tenant``, signed by the operator issuer's private JWK."""

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    path = out / OPERATOR_KEY
    try:
        private = json.loads(path.read_text(encoding="utf-8"))
        raw = base64.urlsafe_b64decode(private["d"] + "=" * (-len(private["d"]) % 4))
        key, kid = Ed25519PrivateKey.from_private_bytes(raw), private["kid"]
    except (OSError, ValueError, KeyError) as error:
        raise Refused("OPERATOR_KEY_INVALID", "write the deployment file first") from error
    issued = int(time.time()) if now is None else now
    header = {"alg": "EdDSA", "kid": kid, "typ": "JWT"}
    claims = {
        "iss": issuer(app),
        "aud": audience(app),
        "sub": subject,
        "iat": issued,
        "exp": issued + ttl_minutes * 60,
        "app_metadata": {"application_id": app, "tenant_id": tenant},
    }
    signing_input = ".".join(
        _b64url(json.dumps(part, separators=(",", ":"), sort_keys=True).encode())
        for part in (header, claims)
    )
    return f"{signing_input}.{_b64url(key.sign(signing_input.encode('ascii')))}"


# Least privilege (W1 round 3): the reviewer's KS grant covers exactly the W1 fixtures' task use,
# audience and report kind (the frozen pack `scripts/sprint_oc_w1_pack.mjs` FIXTURES and the
# fixture missions' registration kind), never `*`. `--pack <frozen pack.json>` reads the task's
# exact use and audience from the pack the run registers instead.
W1_REVIEW_SCOPE = {
    "ai-engineer": ("engineering_reference.model_facts", "internal", "evidence_report"),
    "biotech": ("label_reference.ingredients", "internal", "evidence_report"),
}


def review_scope(app: str, pack: Path | None) -> tuple[str, str, str]:
    """(use, audience, report kind) of the W1 fixture task: the frozen pack's, else the defaults."""

    use, audience, kind = W1_REVIEW_SCOPE[app]
    if pack is None:
        return use, audience, kind
    try:
        task = json.loads(pack.read_text(encoding="utf-8"))["task"]
        use, audience = task["use"], task["audience"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Refused("PACK_INVALID", f"{pack} names no task use and audience") from error
    if not all(isinstance(value, str) and value and value != "*" for value in (use, audience)):
        raise Refused("PACK_INVALID", f"{pack} names no exact task use and audience")
    return use, audience, kind


def reviewer_grant_command(
    mc_root: Path,
    out: Path,
    app: str,
    *,
    tenant: str,
    uses: str,
    audiences: str,
    report_kinds: str,
    ks_root: Path | None = None,
    allow_wildcard: bool = False,
) -> list[str]:
    """The KS ``knowledge-verify grant-reviewer`` argv provisioning the reviewer's live KS grant.

    Without it ``report.review`` fails closed (``reviewer_not_qualified``). The DSN stays in
    ``ks-executor.env`` (the binding's component DSN variable, read by node ``--env-file``);
    the argv names the variable, never its value. KS writes the grant under the bounded
    ``knowledge_verification_reviewer`` role in the tenant's RLS context, idempotently.
    """

    ks = (ks_root or mc_root.parents[0] / "knowledge-services").resolve()
    dsn_env = gen.COMPONENT_DSN[app][0]
    return [
        "node",
        f"--env-file={(out / 'ks-executor.env').as_posix()}",
        (ks / "apps" / "verification-executor" / "dist" / "index.js").as_posix(),
        "grant-reviewer",
        "--database-url-env",
        dsn_env,
        "--tenant",
        tenant,
        "--reviewer",
        REVIEWER_ACTOR,
        "--granted-by",
        OPERATOR_ACTOR,
        "--uses",
        uses,
        "--audiences",
        audiences,
        "--report-kinds",
        report_kinds,
        *(["--allow-wildcard"] if allow_wildcard else []),
    ]


def run(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app", choices=("biotech", "ai-engineer"), required=True)
    parser.add_argument("--mc-root", type=Path, default=MC_ROOT)
    parser.add_argument(
        "--out", type=Path, help="default <mc-root>/.scratch/sprint-oc/runtime/<app>"
    )
    parser.add_argument("--tenant", help="default minted.env KNOWLEDGE_VERIFICATION_TENANT_ID")
    sub = parser.add_subparsers(dest="command")
    parser.add_argument("--component-version", help="the installed MC common release (1.7.0)")
    parser.add_argument("--temporal-namespace", help="default mc-<app>")
    parser.add_argument("--max-request-bytes", type=int, default=1_000_000)
    token = sub.add_parser(
        "token", help="mint a bearer into <out>/operator-token.txt (or reviewer-token.txt)"
    )
    token.add_argument("--ttl-minutes", type=int, default=120)
    token.add_argument(
        "--role",
        choices=sorted(ROLES),
        default="operator",
        help="reviewer: the separate knowledge.review principal (never the launcher)",
    )
    grant = sub.add_parser(
        "reviewer-grant",
        help="print (or --run) the KS command that grants reviewer:sprint-oc a live KS grant",
    )
    # Least privilege: default to the W1 fixture task's exact use, audience and report kind.
    grant.add_argument("--pack", type=Path, help="frozen W1 pack.json: its task use and audience")
    grant.add_argument("--uses", help="override the use (comma list)")
    grant.add_argument("--audiences", help="override the audience (comma list)")
    grant.add_argument("--report-kinds", dest="report_kinds", help="override the report kind")
    grant.add_argument(
        "--allow-wildcard", action="store_true", help="permit * (KS refuses it otherwise)"
    )
    grant.add_argument("--ks-root", type=Path, help="default <mc-root>/../knowledge-services")
    grant.add_argument("--run", action="store_true", help="execute it (integrator only: remote)")
    args = parser.parse_args(argv)
    mc_root = args.mc_root.resolve()
    out = (args.out or mc_root / ".scratch" / "sprint-oc" / "runtime" / args.app).resolve()
    try:
        tenant = tenant_from(out, args.tenant)
        if args.command == "token":
            if not 1 <= args.ttl_minutes <= 24 * 60:
                raise Refused("TTL_INVALID", "--ttl-minutes must be between 1 and 1440")
            subject, name = ROLES[args.role]
            path = out / name
            gen.assert_ignored(path)
            bearer = mint_token(
                out, args.app, tenant=tenant, ttl_minutes=args.ttl_minutes, subject=subject
            )
            gen.write_text(path, bearer + "\n", secret=True)
            return 0, {
                "status": "written",
                "token_file": path.as_posix(),
                "subject": subject,
                "role": args.role,
            }
        if args.command == "reviewer-grant":
            scope = review_scope(args.app, args.pack)
            given = [args.uses, args.audiences, args.report_kinds]
            if not args.allow_wildcard and any("*" in (item or "") for item in given):
                raise Refused("SCOPE_WILDCARD_REFUSED", "* needs --allow-wildcard")
            command = reviewer_grant_command(
                mc_root,
                out,
                args.app,
                tenant=tenant,
                uses=args.uses or scope[0],
                audiences=args.audiences or scope[1],
                report_kinds=args.report_kinds or scope[2],
                ks_root=args.ks_root,
                allow_wildcard=args.allow_wildcard,
            )
            if not args.run:
                return 0, {"status": "command", "argv": command, "reviewer": REVIEWER_ACTOR}
            done = subprocess.run(command, capture_output=True, text=True, check=False)
            if done.returncode != 0:
                raise Refused("REVIEWER_GRANT_REFUSED", done.stderr.strip()[-2000:])
            return 0, {"status": "granted", "result": json.loads(done.stdout)}
        if not args.component_version:
            raise Refused(
                "COMPONENT_VERSION_REQUIRED", "pass --component-version (installed release)"
            )
        namespace = args.temporal_namespace or f"mc-{args.app}"
        for name in (OPERATOR_KEY, OPERATOR_JWKS, DEPLOYMENT):
            gen.assert_ignored(out / name)
        kid, jwks = ensure_operator_key(out)
        gen.write_text(out / OPERATOR_JWKS, json.dumps(jwks, indent=2) + "\n", secret=False)
        document = deployment_document(
            mc_root,
            args.app,
            component_version=args.component_version,
            namespace=namespace,
            tenant=tenant,
            max_request_bytes=args.max_request_bytes,
            # The ingress ref is named only when the runtime env holds that login's DSN.
            signal_ingress=(
                f"MC_{args.app.upper().replace('-', '_')}_INGRESS_DSN"
                in gen.read_env(out / "mission-control.env")
            ),
        )
        gen.write_text(out / DEPLOYMENT, json.dumps(document, indent=2) + "\n", secret=False)
        binding = document["applications"][0]["authentication"]["binding"]
        return 0, {
            "status": "written",
            "deployment_file": (out / DEPLOYMENT).as_posix(),
            "binding_digest": binding["binding_digest"],
            "installation_id": binding["installation_id"],
            "database_secret_ref": binding["database_secret_ref"],
            "family_writer_secret_ref": document["applications"][0]["family_writer_secret_ref"],
            "temporal": document["applications"][0]["temporal"],
            "operator": {"issuer": issuer(args.app), "audience": audience(args.app), "kid": kid},
            "tenant": tenant,
        }
    except Refused as refused:
        return 2, {"status": "refused", "code": refused.code, "error": str(refused)}


def main() -> None:
    code, document = run()
    sys.stdout.write(json.dumps(document, indent=2, sort_keys=True) + "\n")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
