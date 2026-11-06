"""Generate a new Codex schema fixture without touching earlier pins or credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def generate(binary: str, output: Path, expected: str = "0.162.1") -> dict:
    if output.exists():
        raise ValueError("output must be a fresh versioned directory")
    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "HOME",
            "APPDATA",
            "LOCALAPPDATA",
        }
    }
    with tempfile.TemporaryDirectory(prefix="codex-schema-home-") as home:
        env["CODEX_HOME"] = home
        version = subprocess.check_output(
            [binary, "--version"], env=env, stdin=subprocess.DEVNULL, text=True, timeout=15
        ).strip()
        if version != f"codex-cli {expected}":
            raise ValueError(f"expected codex-cli {expected}; observed {version}")
        subprocess.run(
            [binary, "app-server", "generate-json-schema", "--out", str(output)],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=True,
            timeout=30,
        )
    generated = {
        str(p.relative_to(output)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*.json"))
    }
    methods = {}
    for key, definition in [
        ("client_requests", "ClientRequest"),
        ("server_requests", "ServerRequest"),
        ("server_notifications", "ServerNotification"),
        ("client_notifications", "ClientNotification"),
    ]:
        registry = json.loads((output / (definition + ".json")).read_text())
        methods[key] = [
            {
                "method": variant["properties"]["method"]["enum"][0],
                "params": variant["properties"].get("params", {}).get("$ref"),
            }
            for variant in registry["oneOf"]
        ]
    (output / "methods.json").write_text(json.dumps(methods, indent=2) + "\n", encoding="utf-8")
    files = {
        str(p.relative_to(output)).replace("\\", "/"): {
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "bytes": len(p.read_bytes()),
        }
        for p in sorted(output.rglob("*.json"))
    }
    pin = {
        "generator": "codex app-server generate-json-schema --out <dir> (no --experimental)",
        "codex_cli_version": expected,
        "generated_on_host": os.name,
        "app_server_protocol": "v2",
        "files": files,
        "generated_file_count": len(generated),
        "generated_files_sha256": generated,
    }
    (output / "PIN.json").write_text(json.dumps(pin, indent=2) + "\n", encoding="utf-8")
    return pin


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pin = generate(args.binary, args.out)
    print(
        json.dumps(
            {
                "codex_cli_version": pin["codex_cli_version"],
                "generated_file_count": pin["generated_file_count"],
            }
        )
    )
