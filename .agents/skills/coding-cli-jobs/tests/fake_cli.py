"""Synthetic fixture player. Never invokes an actual coding CLI."""
import json
from pathlib import Path
import sys
import time

prompt = sys.stdin.read()
code = 0
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    event = json.loads(line)
    directive = event.get("__fake__")
    if directive is None:
        print(line, flush=True)
    else:
        if "expect_stdin_contains" in directive:
            assert directive["expect_stdin_contains"] in prompt
        if "stderr" in directive:
            print(directive["stderr"], file=sys.stderr, flush=True)
        if "exit" in directive:
            code = directive["exit"]
        if directive.get("hang"):
            time.sleep(60)
sys.exit(code)
