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

# launchd hands us a minimal PATH that omits ~/.local/bin (where uv lives).
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# data/ is a symlink to the 4TB volume; refuse to run if it is not mounted.
if [ ! -d "/Volumes/pntmoni" ] || [ ! -e "$REPO_DIR/data/processed" ]; then
    echo "ERROR: 4TB volume /Volumes/pntmoni not mounted; aborting daily." >&2
    exit 75
fi

# Credentials for unattended acquisition: GSI FTP creds in .gsi, extras in
# .env, Earthdata login in ~/.netrc.
set -a
[ -f "$REPO_DIR/.gsi" ] && . "$REPO_DIR/.gsi"
[ -f "$REPO_DIR/.env" ] && . "$REPO_DIR/.env"
set +a

exec caffeinate -i uv run pntmoni-pipeline daily "$@"
