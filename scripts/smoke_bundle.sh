#!/bin/bash
# Smoke test of the BUILT .app bundle — the layer pytest cannot see.
#
# Every tester-build regression so far (excluded package, pip-in-bundle,
# NSWindow crash at startup, stale-build confusion) was invisible to the venv
# test suite because it only exists in the py2app bundle. This script runs the
# actual bundle binary under a throwaway $HOME (fresh-install simulation — the
# app resolves all its paths through Path.home()) and asserts the log, so those
# classes of bug surface on the dev Mac without a single DMG install.
#
# Usage:
#   make smoke-bundle                  # build tester bundle, then smoke it
#   SMOKE_SKIP_BUILD=1 make smoke-bundle   # smoke the existing dist/Timshel.app
#   SMOKE_WAIT=30 make smoke-bundle    # longer observation window (default 20s)
#
# NOTE: the app is a GUI menu-bar app — for ~20s a wizard window will appear
# and steal focus. That's the test working, not a bug.

set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP="$REPO/dist/Timshel.app"
BIN="$APP/Contents/MacOS/Timshel"
WAIT="${SMOKE_WAIT:-20}"

if [[ "${SMOKE_SKIP_BUILD:-0}" != "1" ]]; then
    echo "--- Building tester bundle ---"
    (cd "$REPO" && TESTER_BUILD=1 bash scripts/build_app.sh) || {
        echo "SMOKE FAIL: bundle build failed"; exit 1; }
fi

[[ -x "$BIN" ]] || { echo "SMOKE FAIL: no bundle binary at $BIN"; exit 1; }

SMOKE_HOME="$(mktemp -d /tmp/timshel-smoke.XXXXXX)"
LOG="$SMOKE_HOME/Library/Application Support/Timshel/logs/timshel.log"

echo "--- Launching bundle under fresh HOME=$SMOKE_HOME (${WAIT}s) ---"
HOME="$SMOKE_HOME" "$BIN" &
PID=$!
sleep "$WAIT"

FAIL=0
note_fail() { echo "SMOKE FAIL: $1"; FAIL=1; }

# 1. The process must survive the observation window (catches crash-at-start).
if kill -0 "$PID" 2>/dev/null; then
    echo "OK   process alive after ${WAIT}s"
else
    note_fail "process died within ${WAIT}s (crash at startup?)"
fi
kill "$PID" 2>/dev/null
wait "$PID" 2>/dev/null

# 2. The log must exist and show a clean startup.
if [[ ! -f "$LOG" ]]; then
    note_fail "no log file at $LOG"
else
    grep -q "Timshel Menu App starting" "$LOG" \
        && echo "OK   startup marker present" \
        || note_fail "startup marker missing from log"

    STAMP="$(grep -m1 "Build: " "$LOG" | sed 's/.*Build: //')"
    if [[ -n "$STAMP" && "$STAMP" != "dev (no bundle)" ]]; then
        echo "OK   build stamp: $STAMP"
    else
        note_fail "build stamp missing from log (Info.plist TimshelBuildStamp)"
    fi

    # 3. No errors or tracebacks during a fresh first launch.
    ERRORS="$(grep -E " - ERROR - |Traceback" "$LOG")"
    if [[ -n "$ERRORS" ]]; then
        note_fail "errors in fresh-install log:"
        echo "$ERRORS"
    else
        echo "OK   no ERROR/Traceback in log"
    fi
fi

# 4. No crash report written for this run.
CRASHES="$(find "$HOME/Library/Logs/DiagnosticReports" -name 'Timshel-*.ips' -newer "$SMOKE_HOME" 2>/dev/null)"
if [[ -n "$CRASHES" ]]; then
    note_fail "crash report(s) written: $CRASHES"
else
    echo "OK   no new crash reports"
fi

if [[ "$FAIL" == "0" ]]; then
    rm -rf "$SMOKE_HOME"
    echo "🎉 SMOKE PASS"
else
    echo "Kept smoke HOME for inspection: $SMOKE_HOME"
    exit 1
fi
