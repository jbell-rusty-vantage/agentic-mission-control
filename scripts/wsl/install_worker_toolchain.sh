#!/usr/bin/env bash
# Install the WSL2 worker toolchain for the local claude_agent_sdk and codex lanes (MO-08).
#
# Runs inside WSL2 Ubuntu as the owner (never root). Idempotent. Installs uv (self-updated),
# Python 3.12 (uv-managed), Node LTS (nvm), the pinned Codex CLI (npm) and the Claude Code CLI
# (native installer), puts the Linux binaries ahead of the Windows PATH that WSL appends, makes
# the lease and fixture directories on the Linux filesystem and syncs a separate Linux venv
# for the checkout (never the Windows .venv). It performs no login and no model call.
#
# Usage (from the Windows checkout mounted under /mnt/c):
#   bash scripts/wsl/install_worker_toolchain.sh [--skip-sync]
# Environment overrides: CODEX_VERSION (default 0.162.1, DECISIONS R21), NVM_VERSION,
# UV_PROJECT_ENVIRONMENT (default $HOME/.venvs/mission-control).
# Then: `docs/MISSION_CONTROL_LOCAL_API.md`, "WSL2 worker for the local Claude and Codex lanes".

set -euo pipefail

CODEX_VERSION="${CODEX_VERSION:-0.162.1}"
NVM_VERSION="${NVM_VERSION:-v0.40.3}"
VENV="${UV_PROJECT_ENVIRONMENT:-$HOME/.venvs/mission-control}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROFILE_FILE="$HOME/.profile"
BLOCK_BEGIN="# >>> mission-control worker toolchain >>>"
BLOCK_END="# <<< mission-control worker toolchain <<<"
SYNC=1

for arg in "$@"; do
  case "$arg" in
    --skip-sync) SYNC=0 ;;
    *) echo "unknown argument: $arg" >&2; exit 64 ;;
  esac
done

step() { printf '\n== %s\n' "$*"; }
fail() { echo "error: $*" >&2; exit 1; }

[[ "$(uname -s)" == "Linux" ]] || fail "run this inside WSL2 (or Linux), not on Windows"
[[ "$(id -u)" -ne 0 ]] || fail "run as the worker user, not root"
case "$VENV" in
  /mnt/*) fail "UV_PROJECT_ENVIRONMENT must be on the Linux filesystem, not $VENV" ;;
esac

step "PATH order: Linux tool directories before the appended Windows PATH"
if ! grep -qF "$BLOCK_BEGIN" "$PROFILE_FILE" 2>/dev/null; then
  cat >>"$PROFILE_FILE" <<EOF

$BLOCK_BEGIN
export NVM_DIR="\$HOME/.nvm"
if [ -s "\$NVM_DIR/nvm.sh" ]; then
  . "\$NVM_DIR/nvm.sh" --no-use && nvm use --silent default >/dev/null 2>&1 || true
fi
export PATH="\$HOME/.local/bin:\$PATH"
$BLOCK_END
EOF
fi
export PATH="$HOME/.local/bin:$PATH"

step "uv (self-updated) and Python 3.12"
# `self update` works only for the standalone install; anything else (pip --user) is replaced.
if ! { [[ -x "$HOME/.local/bin/uv" ]] && "$HOME/.local/bin/uv" self update; }; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh
fi
uv --version
uv python install 3.12

step "Node LTS (nvm $NVM_VERSION)"
export NVM_DIR="$HOME/.nvm"
if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
  curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_VERSION/install.sh" | PROFILE=/dev/null bash
fi
set +u
# shellcheck source=/dev/null
. "$NVM_DIR/nvm.sh"
nvm install --lts
nvm alias default 'lts/*'
nvm use --silent default
set -u
node --version

step "Codex CLI $CODEX_VERSION"
npm install --global "@openai/codex@$CODEX_VERSION"
codex_version="$(codex --version)"
[[ "$codex_version" == "codex-cli $CODEX_VERSION" ]] || fail "codex reports '$codex_version'"
echo "$codex_version ($(command -v codex))"

step "Claude Code CLI"
if ! command -v claude >/dev/null || [[ "$(command -v claude)" == /mnt/* ]]; then
  curl -fsSL https://claude.ai/install.sh | bash
fi
claude --version

step "Lease and fixture roots on the Linux filesystem"
mkdir -p "$HOME/mc-leases/claude" "$HOME/mc-leases/codex" "$HOME/mc-leases/cursor" \
  "$HOME/mc-fixtures" "$(dirname "$VENV")"

if [[ "$SYNC" -eq 1 ]]; then
  step "Linux venv $VENV for $REPO"
  (cd "$REPO" && UV_PROJECT_ENVIRONMENT="$VENV" uv sync --frozen --group dbcontract --group biotech)
fi

if grep -qsE '^[[:space:]]*appendWindowsPath[[:space:]]*=[[:space:]]*false' /etc/wsl.conf; then
  echo "appendWindowsPath=false is set"
else
  cat <<'EOF'

note: WSL still appends the Windows PATH. The Linux tools above now resolve first; to remove
the Windows shims entirely (owner, needs sudo), add to /etc/wsl.conf and run `wsl --shutdown`:
  [interop]
  appendWindowsPath=false
EOF
fi

step "Done. Check the host from $REPO (no login, no model call):"
echo "  UV_PROJECT_ENVIRONMENT=$VENV uv run --no-sync python -m mission_control.bootstrap.preflight host \\"
echo "    --auth-profiles <mc.auth_profile.v1 file> \\"
echo "    --auth-profile claude_agent_sdk=<profile id> --auth-profile codex=<profile id>"
