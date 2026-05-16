#!/usr/bin/env bash
# Acquire RINEX (GEONET) + run QC (teqc + summarize) for a whole month.
# Generic replacement for april_qc.sh — pass YEAR + MONTH to target any month.
#
# Usage:
#   YEAR=2026 MONTH=2  ./scripts/monthly_qc.sh                # 2026-02-01..2026-02-28
#   YEAR=2026 MONTH=3  ./scripts/monthly_qc.sh                # 2026-03-01..2026-03-31
#   YEAR=2026 MONTH=2 START_DAY=15 END_DAY=20 ./scripts/...   # 2026-02-15..2026-02-20
#
# Per-day flow: acquire rinex → qc teqc → qc summarize → drop the day's RINEX.
# A pre-flight ``df -g`` gate aborts if free space < MIN_FREE_GB (default 10 GB,
# lower than april_process.sh because QC's working set is smaller — ~8 GB peak
# RINEX with no .pos output growth).

set -u

YEAR=${YEAR:?YEAR=2026 required}
MONTH=${MONTH:?MONTH=2 required}
MONTH_PADDED=$(printf '%02d' "${MONTH}")

# Days-of-month lookup (2026 is not a leap year).
case "${MONTH}" in
    1|3|5|7|8|10|12) MAX_DAY=31 ;;
    4|6|9|11)        MAX_DAY=30 ;;
    2)               MAX_DAY=$(python3 -c "
import calendar
print(calendar.monthrange(${YEAR}, ${MONTH})[1])
") ;;
    *) echo "MONTH=${MONTH} invalid" >&2; exit 2 ;;
esac

START_DAY=${START_DAY:-1}
END_DAY=${END_DAY:-${MAX_DAY}}
MIN_FREE_GB=${MIN_FREE_GB:-10}

LOG=data/metadata/${YEAR}_${MONTH_PADDED}_qc_run.log
mkdir -p "$(dirname "$LOG")"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
if [ -f "$REPO_ROOT/.gsi" ]; then
    set -a
    . "$REPO_ROOT/.gsi"
    set +a
fi

log() {
    echo "$(date -Iseconds) $*" | tee -a "$LOG"
}

run_step() {
    local label="$1"; shift
    log "BEGIN ${label}: $*"
    if ! "$@" >> "$LOG" 2>&1; then
        log "FAILED ${label}"
        return 1
    fi
    log "OK ${label}"
    return 0
}

free_gb_under() {
    df -g "$1" 2>/dev/null | awk 'NR==2 {print $4}'
}

log "BEGIN monthly_qc YEAR=${YEAR} MONTH=${MONTH_PADDED} START_DAY=${START_DAY} END_DAY=${END_DAY}"

for d in $(seq -w "${START_DAY}" "${END_DAY}"); do
    target="${YEAR}-${MONTH_PADDED}-${d}"
    doy=$(date -j -f '%Y-%m-%d' "${target}" +%j)

    log "=== ${target} (DOY ${doy}) ==="

    # 0. Pre-flight disk-free gate.
    free_gb=$(free_gb_under "${REPO_ROOT}")
    if [ -z "${free_gb}" ] || [ "${free_gb}" -lt "${MIN_FREE_GB}" ]; then
        log "ABORT ${target} disk free ${free_gb}GB < ${MIN_FREE_GB}GB — halting batch"
        exit 1
    fi
    log "preflight ${target} disk_free=${free_gb}GB"

    # 1. RINEX OBS for the day.
    if ! run_step "acquire-rinex ${target}" uv run pntmoni-pipeline acquire rinex --date "${target}"; then
        log "SKIP ${target} (acquire-rinex failed)"
        # Clean any partial RINEX so the disk doesn't bleed across skips.
        raw_dir="data/raw/rinex/${YEAR}/${doy}"
        if [ -d "${raw_dir}" ]; then
            size=$(du -sh "${raw_dir}" | cut -f1)
            rm -rf "${raw_dir}"
            log "CLEANED partial ${raw_dir} (${size})"
        fi
        continue
    fi

    # 2. QC teqc (Stage 1).
    if ! run_step "qc-teqc ${target}" uv run pntmoni-pipeline qc teqc --date "${target}"; then
        log "SKIP ${target} (qc teqc failed)"
        continue
    fi

    # 3. QC summarize (Stage 2 → Parquet).
    if ! run_step "qc-summarize ${target}" uv run pntmoni-pipeline qc summarize --date "${target}"; then
        log "SKIP ${target} (qc summarize failed)"
        continue
    fi

    # 4. Cleanup: drop the day's RINEX (qc_teqc/.S26 + qc_summary/.parquet retained).
    raw_dir="data/raw/rinex/${YEAR}/${doy}"
    if [ -d "${raw_dir}" ]; then
        size=$(du -sh "${raw_dir}" | cut -f1)
        rm -rf "${raw_dir}"
        log "CLEANED ${raw_dir} (${size})"
    fi

    log "DONE ${target}"
done

log "END monthly_qc"
