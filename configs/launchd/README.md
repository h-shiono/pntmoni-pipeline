# launchd scheduling — nightly `daily` run

`com.pntmoni.daily.plist` is a **template** that schedules
`scripts/run_daily.sh` (which runs `pntmoni-pipeline daily` under
`caffeinate`) every night at 03:00 local time.

## Install

```bash
REPO=/Users/hayato/dev/pntmoni-pipeline          # absolute repo path
PLIST=~/Library/LaunchAgents/com.pntmoni.daily.plist

# Substitute the repo path into the template and install it.
sed "s#__REPO__#$REPO#g" "$REPO/configs/launchd/com.pntmoni.daily.plist" > "$PLIST"

mkdir -p "$REPO/data/logs"
launchctl load "$PLIST"          # modern alternative: launchctl bootstrap gui/$(id -u) "$PLIST"
launchctl list | grep com.pntmoni.daily
```

To trigger a run immediately (smoke test):

```bash
launchctl start com.pntmoni.daily
```

To update after editing the template, `launchctl unload "$PLIST"`, re-run
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
- Per-run human log: `data/logs/daily_<timestamp>.log`
- launchd stdout/stderr: `data/logs/launchd.daily.{out,err}.log`
- Failure paging: set `PNTMONI_NTFY_URL` (an ntfy.sh topic URL) in `.env`
  to get a push notification when a run ends `partial`/`failed`.
