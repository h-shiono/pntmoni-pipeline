# launchd scheduling — nightly operational run

Two templates are provided; **install one**:

- `com.pntmoni.catchup.plist` → `scripts/run_catchup.sh` —
  **the operational job.** Runs the current day's `daily` (today − lag)
  then backfills up to N still-incomplete historical days
  (defaults: backfill toward 2026-01-01, N=2, newest-first). Use this to
  run steady-state operation that also catches up history.
- `com.pntmoni.daily.plist` → `scripts/run_daily.sh` — daily only
  (no backfill). Use if you don't want the catch-up behaviour.

Both run every night at 03:00 local time under `caffeinate`.

## Install (catchup — recommended)

```bash
REPO=/Users/hayato/dev/pntmoni-pipeline          # absolute repo path
PLIST=~/Library/LaunchAgents/com.pntmoni.catchup.plist

# Substitute the repo path into the template and install it.
sed "s#__REPO__#$REPO#g" "$REPO/configs/launchd/com.pntmoni.catchup.plist" > "$PLIST"

mkdir -p "$REPO/data/logs"
launchctl load "$PLIST"          # modern alternative: launchctl bootstrap gui/$(id -u) "$PLIST"
launchctl list | grep com.pntmoni.catchup
```

(For the daily-only variant, substitute `com.pntmoni.daily.plist` /
`com.pntmoni.daily` above.)

To trigger a run immediately (smoke test):

```bash
launchctl start com.pntmoni.catchup
```

To tune N or the backfill window, edit the flags in
`scripts/run_catchup.sh` (e.g. `--backfill-days 3`, `--max-hours 6`).

To update after editing a template, `launchctl unload "$PLIST"`, re-run
the `sed` step, then `launchctl load "$PLIST"`.

## Credentials

Unattended acquisition needs GSI FTP + Earthdata credentials. launchd
loads a minimal environment, so `run_daily.sh` sources `$REPO/.env` if it
exists. Put `GSI_FTP_USER` / `GSI_FTP_PASSWORD` there (and keep the
Earthdata login in `~/.netrc`). `.env` is gitignored.

## The data volume must be mounted

The repo's `data/` is a symlink to `/Volumes/pntmoni/pntmoni-pipeline-data`
(the local 4TB disk). If that volume is not mounted the symlink dangles
and every step fails. APFS volumes auto-mount at login; confirm with
`ls /Volumes/pntmoni` before relying on the nightly job.

## The machine must be awake

**launchd does not fire a `StartCalendarInterval` job while the Mac is
asleep.** Two mitigations:

1. **Wake the machine before the run** (recommended) so the 03:00 job
   actually fires:

   ```bash
   sudo pmset repeat wakeorpoweron MTWRFSU 02:55:00
   ```

2. `run_daily.sh` already wraps the run in `caffeinate -i`, which prevents
   *idle* sleep **once the job has started** — it does not wake a sleeping
   machine, hence the `pmset` companion above.

If the machine was off at 03:00, the job runs at next wake (launchd
coalesces missed calendar intervals). The `daily` default targets
`today − 2 days`, so a late run still picks a date whose data is
published.

## Logs and notifications

- Per-run structured record: `data/metadata/orchestration.jsonl`
- Per-run human log: `data/logs/{daily,catchup}_<timestamp>.log` (on the 4TB)
- launchd stdout/stderr: `logs/launchd.{catchup,daily}.{out,err}.log`
  — on the **internal** disk (not under `data/`, the 4TB symlink), so
  launchd can open them even if the volume is unmounted. (A stdout path
  under an unmounted-volume symlink makes launchd fail the job at spawn
  with `EX_CONFIG` / exit 78 and no logs.)
- Failure paging: set `PNTMONI_NTFY_URL` (an ntfy.sh topic URL) in `.env`
  to get a push notification when a run ends `partial`/`failed`.

## Gotchas this setup guards against

- **uv not on launchd's PATH**: `run_*.sh` prepend `~/.local/bin` (and
  `~/.cargo/bin`) so `uv` resolves under launchd's minimal PATH.
- **4TB not mounted at run time**: `run_*.sh` abort early (exit 75) with a
  clear message rather than failing deep in processing; the launchd logs
  live on internal disk so the message is captured.
