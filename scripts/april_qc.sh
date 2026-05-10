#!/usr/bin/env bash
# Acquire RINEX (GEONET) + run QC (teqc + summarize) for 2026-04-02..2026-04-30.
# 2026-04-01 already done. Logs to data/metadata/april_qc_run.log.
set -u
LOG=data/metadata/april_qc_run.log
mkdir -p "$(dirname "$LOG")"

# Resolve repo root from this script's location, then load GSI FTP credentials.
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
if [ -f "$REPO_ROOT/.gsi" ]; then
    set -a
    . "$REPO_ROOT/.gsi"
    set +a
fi

date -Iseconds >> "$LOG"
echo "BEGIN april_qc" >> "$LOG"

for d in $(seq -w 3 30); do
    target="2026-04-${d}"
    echo "=== ${target} === $(date -Iseconds)" >> "$LOG"

    if ! uv run pntmoni-pipeline acquire rinex --date "${target}" >> "$LOG" 2>&1; then
        echo "ACQUIRE FAILED ${target}" >> "$LOG"
        continue
    fi

    if ! uv run pntmoni-pipeline qc teqc --date "${target}" >> "$LOG" 2>&1; then
        echo "QC TEQC FAILED ${target}" >> "$LOG"
        continue
    fi

    if ! uv run pntmoni-pipeline qc summarize --date "${target}" >> "$LOG" 2>&1; then
        echo "QC SUMMARIZE FAILED ${target}" >> "$LOG"
        continue
    fi

    # All QC succeeded → drop the day's raw RINEX (re-acquirable from GSI FTP).
    # qc_teqc/.S26 and qc_summary/.parquet are kept for downstream stats.
    doy=$(date -j -f '%Y-%m-%d' "${target}" +%j)
    raw_dir="data/raw/rinex/2026/${doy}"
    if [ -d "${raw_dir}" ]; then
        size=$(du -sh "${raw_dir}" | cut -f1)
        rm -rf "${raw_dir}"
        echo "CLEANED raw ${raw_dir} (${size})" >> "$LOG"
    fi

    echo "DONE ${target} $(date -Iseconds)" >> "$LOG"
done

echo "END april_qc $(date -Iseconds)" >> "$LOG"
