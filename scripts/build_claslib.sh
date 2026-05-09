#!/usr/bin/env bash
# Build pntmoni-claslib's rnx2rtkp.
#
# The upstream Makefile uses `-ansi -pedantic` and `-llapack -lblas`, which
# do not work cleanly on macOS clang (POSIX functions like strtok_r are
# not declared, and Homebrew lapack/blas are not assumed installed).
# This script bypasses the Makefile and invokes the compiler directly with:
#   - LAPACK enabled via Apple Accelerate (built-in, hardware-optimized
#     on Apple Silicon — about 1.3× faster than CLASLIB's internal matrix
#     routines on a typical full-DOY run)
#   - Source list extracted from the Makefile's SRCS / RCV_SRCS variables
#
# Until the build hygiene fixes land in the fork as a MOD-NNN, this is the
# recommended way to build on macOS. On Linux, `make -C
# vendor/pntmoni-claslib/util/rnx2rtkp` should work directly with system
# liblapack + libblas.
#
# Usage:
#   scripts/build_claslib.sh                    # production (Accelerate + LAPACK)
#   scripts/build_claslib.sh --no-lapack        # debug build, internal matrix routines
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENGINE_DIR="$REPO_ROOT/vendor/pntmoni-claslib"
BUILD_DIR="$ENGINE_DIR/util/rnx2rtkp"

USE_LAPACK=1
if [[ "${1:-}" == "--no-lapack" ]]; then
    USE_LAPACK=0
fi

if [[ ! -d "$ENGINE_DIR" ]]; then
    echo "error: pntmoni-claslib submodule not initialised at $ENGINE_DIR" >&2
    echo "  hint: git submodule update --init vendor/pntmoni-claslib" >&2
    exit 1
fi

# Per upstream Makefile (vendor/pntmoni-claslib/util/rnx2rtkp/makefile)
SRCS=(
    rtkcmn rinex rtkpos postpos solution lambda geoid sbas preceph pntpos
    ephemeris options ppp ppp_ar rtcm rtcm2 rtcm3 rtcm3e ionex qzslex rcvraw
    stec isb grid cssr ppprtk cssr2osr rtkvrs
)
RCV=(binex novatel ublox)

FILES=("$BUILD_DIR/rnx2rtkp.c")
for s in "${SRCS[@]}"; do FILES+=("$ENGINE_DIR/src/$s.c"); done
for s in "${RCV[@]}";  do FILES+=("$ENGINE_DIR/src/rcv/$s.c"); done

CFLAGS=(
    -Wall -O3
    "-I$ENGINE_DIR/src"
    -DTRACE -DENAGAL -DENAQZS -DNFREQ=3 -DENA_PPP_RTK -DENA_REL_VRS
)

LDLIBS=(-lm)
if [[ "$USE_LAPACK" == "1" ]]; then
    CFLAGS+=(-DLAPACK)
    case "$(uname -s)" in
        Darwin)
            # Apple Silicon: Accelerate uses the AMX matrix coprocessor.
            LDLIBS+=(-framework Accelerate)
            CFLAGS+=(-Wno-deprecated-declarations)
            ;;
        Linux)
            LDLIBS+=(-llapack -lblas)
            ;;
        *)
            echo "warn: unknown OS, assuming reference LAPACK" >&2
            LDLIBS+=(-llapack -lblas)
            ;;
    esac
fi

OUT="$BUILD_DIR/rnx2rtkp"
echo "build → $OUT"
echo "  CFLAGS:  ${CFLAGS[*]}"
echo "  LDLIBS:  ${LDLIBS[*]}"
echo "  sources: ${#FILES[@]}"

gcc "${CFLAGS[@]}" "${FILES[@]}" "${LDLIBS[@]}" -o "$OUT"

echo
echo "built: $OUT"
ls -lh "$OUT"
file "$OUT"
