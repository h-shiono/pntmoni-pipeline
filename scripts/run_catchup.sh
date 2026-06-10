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

# launchd hands us a minimal PATH that omits ~/.local/bin (where uv lives).
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# data/ is a symlink to the 4TB volume. If it is not mounted, refuse to run
# with a clear message (to the internal launchd log) rather than failing deep
# in acquisition/processing. EX_TEMPFAIL (75) marks it transient.
if [ ! -d "/Volumes/pntmoni" ] || [ ! -e "$REPO_DIR/data/processed" ]; then
    echo "ERROR: 4TB volume /Volumes/pntmoni not mounted; aborting catchup." >&2
    exit 75
fi

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
