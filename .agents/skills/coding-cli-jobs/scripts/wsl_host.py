"""Explicit WSL custody. Commands use positional arguments, never shell interpolation."""
import os
from pathlib import PurePosixPath
import subprocess
import uuid


class WslHost:
    def __init__(self, configuration, cli):
        self.config = configuration
        self.cli = cli
        for name in ("repo", "worktree_root", "home", "binary"):
            path = configuration[name]
            if not path.startswith("/") or path.startswith("/mnt/") or ".." in PurePosixPath(path).parts:
                raise ValueError(f"WSL {name} must be an absolute Linux/ext4 path")

    def command(self, argv, cwd=None):
        c = self.config
        env = ["env", "-i", "HOME=" + c["home"], "PATH=" + c["path"], "LANG=C.UTF-8"]
        return ["wsl.exe", "-d", c["distro"], "-e", *env, "sh", "-c",
                'cd "$1" && shift && exec "$@"', "agentjob", cwd or c["repo"], *argv]

    def run(self, argv, cwd=None, text=None):
        result = subprocess.run(self.command(argv, cwd), input=text, stdin=subprocess.DEVNULL if text is None else None,
                                capture_output=True, encoding="utf-8", timeout=15, check=False,
                                env={k: v for k, v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}})
        if result.returncode:
            raise ValueError("WSL command refused: " + result.stderr[-1000:])
        return (result.stdout + result.stderr).strip()

    def git(self, cwd, *args):
        return self.run(["git", "-C", cwd, *args])

    def write(self, path, text):
        self.run(["sh", "-c", 'umask 077; cat > "$1"', "agentjob", path], text=text)

    def launch(self, argv, cwd):
        pidfile = self.config["worktree_root"] + "/.agentjob-pgid-" + uuid.uuid4().hex
        command = self.command(["setsid", "--wait", "sh", "-c",
                                'umask 077; echo $$ > "$1"; shift; exec "$@"', "agentjob", pidfile, *argv], cwd)
        cancelled = False
        def cancel():
            nonlocal cancelled
            if cancelled:
                return
            self.run(["sh", "-c", 'n=0; while ! test -f "$1" && test "$n" -lt 20; do sleep 0.1; n=$((n+1)); done; if test -f "$1"; then p=$(cat "$1"); case "$p" in ""|*[!0-9]*) exit 2;; esac; /bin/kill -KILL -- -"$p" 2>/dev/null || true; rm -f -- "$1"; fi', "agentjob", pidfile])
            cancelled = True
        def cleanup():
            cancel()
        return command, cancel, cleanup
