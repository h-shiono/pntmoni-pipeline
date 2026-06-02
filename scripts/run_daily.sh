#!/bin/sh
# Nightly PNT Moni daily-pipeline run, invoked by launchd.
#
# Wrapped in `caffeinate -i` so the machine does not idle-sleep mid-run
# (launchd does NOT fire jobs while the Mac is asleep — see
# configs/launchd/README.md for the pmset wake companion).
#
# Any extra args are passed through to `pntmoni-pipeline daily`
# (e.g. --date 2026-04-01, --skip-acquire).
set -eu

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Credentials for unattended acquisition (GSI FTP, Earthdata) are expected
# in the environment / ~/.netrc; launchd loads a minimal env, so source a
# local env file if present.
if [ -f "$REPO_DIR/.env" ]; then
    set -a
    . "$REPO_DIR/.env"
    set +a
fi

exec caffeinate -i uv run pntmoni-pipeline daily "$@"
