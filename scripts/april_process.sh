#!/usr/bin/env bash
# Acquire RINEX/BRDC/L6, run CLASLIB processing for kinematic_p30_verify
# and kinematic_p30_ttff_verify, then drop the day's RINEX + per-mode
# workspace. RINEX is the bulky artefact (~7 GB/day) and is re-acquirable
# from GSI FTP; the .pos outputs are kept under data/processed.
#
# Default range: 2026-04-02..2026-04-30 (2026-04-01 already done).
# Override with: START_DAY=15 END_DAY=20 ./scripts/april_process.sh
#
# Logs to data/metadata/april_process_run.log.

set -u

START_DAY=${START_DAY:-2}
END_DAY=${END_DAY:-30}
YEAR=${YEAR:-2026}
MONTH=${MONTH:-04}
MODES=(kinematic_p30_verify kinematic_p30_ttff_verify)

LOG=data/metadata/april_process_run.log
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
    local label="$1"
    shift
    log "BEGIN ${label}: $*"
    if ! "$@" >> "$LOG" 2>&1; then
        log "FAILED ${label}"
        return 1
    fi
    log "OK ${label}"
    return 0
}

log "BEGIN april_process START_DAY=${START_DAY} END_DAY=${END_DAY}"

# Minimum free space required before starting a day. Each day's working
# set peaks at ~14 GB during processing (7 GB RINEX + ~4 GB workspace
# gunzipped obs + ~2.6 GB .pos × 2 modes), so 15 GB is the floor.
MIN_FREE_GB=${MIN_FREE_GB:-15}

free_gb_under() {
    df -g "$1" 2>/dev/null | awk 'NR==2 {print $4}'
}

for d in $(seq -w "${START_DAY}" "${END_DAY}"); do
    target="${YEAR}-${MONTH}-${d}"
    doy=$(date -j -f '%Y-%m-%d' "${target}" +%j)

    log "=== ${target} (DOY ${doy}) ==="

    # 0. Pre-flight disk-free gate.
    free_gb=$(free_gb_under "${REPO_ROOT}")
    if [ -z "${free_gb}" ] || [ "${free_gb}" -lt "${MIN_FREE_GB}" ]; then
        log "ABORT ${target} disk free ${free_gb}GB < ${MIN_FREE_GB}GB — halting batch"
        exit 1
    fi
    log "preflight ${target} disk_free=${free_gb}GB"

    # 1. RINEX OBS for the day
    if ! run_step "acquire-rinex ${target}" uv run pntmoni-pipeline acquire rinex --date "${target}"; then
        log "SKIP ${target} (acquire-rinex failed)"
        continue
    fi

    # 2. BRDC for D and D+1 (rnx2rtkp needs both)
    if ! run_step "acquire-brdc ${target}" uv run pntmoni-pipeline acquire brdc --date "${target}"; then
        log "SKIP ${target} (acquire-brdc D failed)"
        continue
    fi
    next_target=$(date -j -v+1d -f '%Y-%m-%d' "${target}" +%Y-%m-%d)
    if ! run_step "acquire-brdc ${next_target}" uv run pntmoni-pipeline acquire brdc --date "${next_target}"; then
        log "SKIP ${target} (acquire-brdc D+1 failed)"
        continue
    fi

    # 3. L6 for the day
    if ! run_step "acquire-l6 ${target}" uv run pntmoni-pipeline acquire l6 --date "${target}"; then
        log "SKIP ${target} (acquire-l6 failed)"
        continue
    fi

    # 4. Processing — both modes back-to-back so we re-use the acquired RINEX
    process_ok=true
    for mode in "${MODES[@]}"; do
        if ! run_step "process ${mode} ${target}" \
                uv run pntmoni-pipeline process claslib \
                --date "${target}" --mode "${mode}" \
                --data-dir configs/aux_data; then
            log "MODE FAILED ${target} ${mode}"
            process_ok=false
            break
        fi
    done
    if ! $process_ok; then
        log "SKIP cleanup for ${target} (processing failed — keep RINEX for triage)"
        continue
    fi

    # 5. Cleanup: drop the day's RINEX + per-mode workspace
    raw_dir="data/raw/rinex/${YEAR}/${doy}"
    if [ -d "${raw_dir}" ]; then
        size=$(du -sh "${raw_dir}" | cut -f1)
        rm -rf "${raw_dir}"
        log "CLEANED ${raw_dir} (${size})"
    fi
    for mode in "${MODES[@]}"; do
        ws="data/work/${mode}/${YEAR}/${doy}"
        if [ -d "${ws}" ]; then
            rm -rf "${ws}"
            log "CLEANED ${ws}"
        fi
    done

    log "DONE ${target}"
done

log "END april_process"
