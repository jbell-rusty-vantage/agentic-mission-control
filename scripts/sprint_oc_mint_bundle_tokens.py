"""Sprint OC W0 (WI-24, OVE-168): mint the capability-bundle custody credentials offline.

Two Supabase Auth JWTs for one application's project, the shape the storage policies of seed
`common/mc.storage.capability-bundles-1.0.0.json` admit (`mission_control_db_contract/storage.py`):
`role` and `aud` `authenticated`, a stable `sub` (`uuid5(NAMESPACE_URL,
"sprint-oc:<app>:<role>")`), `iss` `https://<project_ref>.supabase.co/auth/v1`,
`iat`, `exp` and the top-level claim `mc_capability_role`:

- `CAPABILITY_BUNDLE_PUBLISHER_TOKEN` (`publisher`: INSERT + SELECT on the application prefix)
- `CAPABILITY_BUNDLE_READER_TOKEN` (`reader`: SELECT only)

Signing material, one of:
- `--secret-env-file <dotenv> --secret-env <NAME>`: the project's legacy HS256 JWT secret
  (AI Engineer: `aiengineer/.env` `SUPABASE_JWT_SECRET`);
- `--es256-key-file <PKCS#8 PEM> --kid <kid>`: a P-256 key imported into the project as a standby
  signing key (Biotech has no usable signing material yet: ESCALATION H2).

The project is proven, not assumed: `SUPABASE_URL` (`--url-env`) in the env file (`--url-env-file`,
default the secret env file) must be exactly `https://<project_ref>.supabase.co` of
`deployments/<app>/target.toml`, or the script refuses. Nothing goes on the network.

Output: `<out-dir>/<app>/bundle-custody.env` (default `.scratch/sprint-oc/runtime/<app>/`), ignored
and owner-only exactly like the runtime env files (`sprint_oc_runtime_env.py` reads it into
`mission-control.env`). stdout carries names, `exp` and the unsigned header and claims only.

  uv run --no-sync python scripts/sprint_oc_mint_bundle_tokens.py --app ai-engineer \\
    --secret-env-file ../../aiengineer/.env --secret-env SUPABASE_JWT_SECRET \\
    [--publisher-ttl 24h] [--reader-ttl 7d] [--mc-root <dir>] [--out-dir <dir>]

Exit: 0 written, 2 refused (nothing written).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import tomllib
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import ECKey, OctKey

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sprint_oc_runtime_env as runtime  # type: ignore[import-not-found]

Refused = runtime.Refused
CLAIM = "mc_capability_role"
TOKENS = {
    "publisher": "CAPABILITY_BUNDLE_PUBLISHER_TOKEN",
    "reader": "CAPABILITY_BUNDLE_READER_TOKEN",
}
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
MAX_TTL_SECONDS = 30 * 86400


def parse_ttl(text: str) -> int:
    match = re.fullmatch(r"([1-9][0-9]*)([smhd])", text.strip())
    if not match:
        raise Refused("TTL_INVALID", f"{text!r} is not <n>s|m|h|d")
    seconds = int(match.group(1)) * UNITS[match.group(2)]
    if seconds > MAX_TTL_SECONDS:
        raise Refused("TTL_TOO_LONG", f"{text} exceeds 30d")
    return seconds


def project_url_ref(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    match = re.fullmatch(r"([a-z0-9]{20})\.supabase\.co", host)
    if not match or parts.scheme != "https" or parts.path not in {"", "/"} or parts.query:
        return None
    return match.group(1)


def read_secret(path: Path, name: str) -> str:
    """One value of a dotenv file, literal: no `${...}` interpolation (a secret may contain it)."""

    if not path.is_file():
        return ""
    return dotenv_values(path, encoding="utf-8-sig", interpolate=False).get(name) or ""


def signing_key(args: argparse.Namespace) -> tuple[Any, dict[str, str]]:
    hs256 = args.secret_env_file is not None or args.secret_env is not None
    es256 = args.es256_key_file is not None or args.kid is not None
    if hs256 == es256:
        raise Refused(
            "SIGNING_MATERIAL_REQUIRED",
            "exactly one of --secret-env-file/--secret-env or --es256-key-file/--kid",
        )
    if hs256:
        if args.secret_env_file is None or args.secret_env is None:
            raise Refused("SIGNING_MATERIAL_REQUIRED", "--secret-env-file and --secret-env")
        secret = read_secret(args.secret_env_file, args.secret_env)
        if len(secret.strip()) < 32:
            raise Refused("SECRET_MISSING", f"{args.secret_env} is absent or shorter than 32 bytes")
        return OctKey.import_key(secret), {"alg": "HS256", "typ": "JWT"}
    if args.es256_key_file is None or not args.kid:
        raise Refused("SIGNING_MATERIAL_REQUIRED", "--es256-key-file and --kid")
    try:
        key = ECKey.import_key(args.es256_key_file.read_bytes())
    except (OSError, ValueError, JoseError) as error:
        raise Refused("KEY_INVALID", f"{args.es256_key_file} is not a readable EC key") from error
    if key.as_dict(private=False).get("crv") != "P-256" or not key.is_private:
        raise Refused("KEY_INVALID", "--es256-key-file must hold a P-256 private key")
    return key, {"alg": "ES256", "typ": "JWT", "kid": args.kid}


def mint(args: argparse.Namespace, now: int | None = None) -> tuple[dict[str, str], dict[str, Any]]:
    mc_root = (args.mc_root or runtime.MC_ROOT).resolve()
    target_file = mc_root / "deployments" / args.app / "target.toml"
    if not target_file.is_file():
        raise Refused("MC_ROOT_INVALID", f"{mc_root} is not a Mission Control checkout")
    ref = tomllib.loads(target_file.read_text(encoding="utf-8"))["target"]["project_ref"]
    url_file = args.url_env_file or args.secret_env_file
    if url_file is None:
        raise Refused("PROJECT_URL_REQUIRED", "--url-env-file naming SUPABASE_URL")
    url = runtime.read_env(url_file).get(args.url_env, "")
    if project_url_ref(url) != ref:
        raise Refused(
            "PROJECT_REF_MISMATCH", f"{args.url_env} is not https://{ref}.supabase.co ({args.app})"
        )
    key, header = signing_key(args)
    issued = int(time.time()) if now is None else now
    ttls = {"publisher": parse_ttl(args.publisher_ttl), "reader": parse_ttl(args.reader_ttl)}
    tokens: dict[str, str] = {}
    report: dict[str, Any] = {}
    for role, name in TOKENS.items():
        expires = issued + ttls[role]
        claims: dict[str, Any] = {
            "iss": f"https://{ref}.supabase.co/auth/v1",
            # Stable per application and role (no `auth.users` row exists for it).
            "sub": str(uuid.uuid5(uuid.NAMESPACE_URL, f"sprint-oc:{args.app}:{role}")),
            "aud": "authenticated",
            "role": "authenticated",
            "iat": issued,
            "exp": expires,
            CLAIM: role,
        }
        tokens[name] = jwt.encode(header, claims, key)
        report[name] = {
            "exp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires)),
            "header": header,
            "claims": claims,
        }
    return tokens, report


def run(argv: list[str] | None = None) -> tuple[int, dict[str, Any]]:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--app", required=True, choices=sorted(runtime.PORTS))
    parser.add_argument("--secret-env-file", type=Path)
    parser.add_argument("--secret-env")
    parser.add_argument("--es256-key-file", type=Path)
    parser.add_argument("--kid")
    parser.add_argument("--url-env-file", type=Path)
    parser.add_argument("--url-env", default="SUPABASE_URL")
    parser.add_argument("--publisher-ttl", default="24h")
    parser.add_argument("--reader-ttl", default="7d")
    parser.add_argument("--mc-root", type=Path)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        mc_root = (args.mc_root or runtime.MC_ROOT).resolve()
        out_root = (args.out_dir or mc_root / ".scratch" / "sprint-oc" / "runtime").resolve()
        target = out_root / args.app / "bundle-custody.env"
        runtime.assert_ignored(target)
        tokens, report = mint(args)
        text = runtime.render(
            [runtime.Entry(name, value, "minted") for name, value in tokens.items()],
            f"{args.app} bundle-custody.env",
        )
        runtime.write_text(target, text, secret=True)
    except Refused as refusal:
        return 2, {"status": "refused", "code": refusal.code, "detail": refusal.detail}
    return 0, {"status": "written", "app": args.app, "file": str(target), "tokens": report}


def main() -> None:
    code, summary = run()
    print(json.dumps(summary, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
