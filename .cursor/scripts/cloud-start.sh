#!/usr/bin/env bash
# Runs at every Cursor Cloud agent start (Mission Control kit envkit.mission-control-dev@1).
# 1. Start the Docker daemon so the `infra` terminal and tests can use Compose.
# 2. Bootstrap entrypoint (SPEC-01 section 1): run the mission layer `.mission/setup/run`
#    when the mission branch carries one. It writes `.mission/setup/receipt.json`; a failure
#    is reported there and on stderr but does not block the agent (readiness stays unproven).
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if ! docker info >/dev/null 2>&1; then
    if ! sudo service docker start >/dev/null 2>&1; then
        sudo sh -c "nohup dockerd > /tmp/cursor-cloud-dockerd.log 2>&1 &"
    fi
fi

for _ in {1..30}; do
    if docker info >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon did not become ready within 30 seconds." >&2
fi

if [[ -f .mission/setup/run ]]; then
    if ! timeout 600 bash .mission/setup/run --phase start; then
        echo "Mission setup (.mission/setup/run --phase start) failed; see .mission/setup/receipt.json." >&2
    fi
fi
