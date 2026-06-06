#!/bin/sh
# Nightly PNT Moni operational run, invoked by launchd.
#
# Runs the current day's `daily` (today - lag) and then backfills up to N
# still-incomplete historical days. Wrapped in `caffeinate -i` so the
# machine does not idle-sleep mid-run (see configs/launchd/README.md for the
# pmset wake companion and the data-volume mount requirement).
#
# Operational defaults (per 2026-06-07 decision): backfill toward 2026-01-01,
# 2 gap days per night, newest-first. Override by passing flags through, e.g.
#   scripts/run_catchup.sh --backfill-days 3
set -eu

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

# Credentials / config for unattended acquisition. GSI FTP creds live in
# .gsi (FTP_USER/FTP_PASSWORD); .env may hold extras (e.g. PNTMONI_NTFY_URL).
# Earthdata login (for BRDC) is in ~/.netrc.
set -a
[ -f "$REPO_DIR/.gsi" ] && . "$REPO_DIR/.gsi"
[ -f "$REPO_DIR/.env" ] && . "$REPO_DIR/.env"
set +a

exec caffeinate -i uv run pntmoni-pipeline catchup \
    --backfill-start 2026-01-01 \
    --backfill-days 2 \
    --order newest \
    "$@"
