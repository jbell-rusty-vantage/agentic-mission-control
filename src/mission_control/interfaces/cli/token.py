"""Local token helper. Credentials are written to a new file, never standard output."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

from mission_control.adapters.auth.jwt import ApplicationAuthentication
from mission_control.adapters.auth.operator_token import mint_operator_token


def add_token_parser(groups: argparse._SubParsersAction) -> None:
    group = groups.add_parser("token", help="mint an operator-scoped token locally")
    actions = group.add_subparsers(dest="action", required=True)
    mint = actions.add_parser("mint")
    mint.add_argument("--auth-config", required=True, type=Path)
    mint.add_argument("--private-key-file", required=True, type=Path)
    mint.add_argument("--key-id", required=True)
    mint.add_argument("--subject", required=True)
    mint.add_argument("--tenant", required=True, type=UUID)
    mint.add_argument("--scope", required=True, action="append")
    mint.add_argument("--expires-in", type=int, default=900)
    mint.add_argument("--algorithm", choices=("RS256", "ES256", "EdDSA"), default="RS256")
    mint.add_argument("--out", required=True, type=Path)


def run_token(args: argparse.Namespace) -> int:
    try:
        config = ApplicationAuthentication.model_validate_json(args.auth_config.read_bytes())
        if not config.public_jwks_file.is_absolute():
            config = config.model_copy(
                update={
                    "public_jwks_file": args.auth_config.resolve().parent / config.public_jwks_file
                }
            )
        token = mint_operator_token(
            config,
            private_key_file=args.private_key_file,
            key_id=args.key_id,
            subject=args.subject,
            tenant_id=args.tenant,
            scopes=frozenset(args.scope),
            expires_in=args.expires_in,
            algorithm=args.algorithm,
        )
        # O_EXCL preserves an existing credential; restrictive mode on POSIX.
        descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(token + "\n")
    except Exception:
        # Validation and cryptography errors can include private input. Do not echo them.
        print(json.dumps({"code": "TOKEN_MINT_REFUSED"}))
        return 2
    print(json.dumps({"out": str(args.out), "expires_in": args.expires_in}))
    return 0
