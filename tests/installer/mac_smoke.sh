#!/bin/bash
# Fresh-install test for the macOS build: install from the .dmg into a scratch folder, check the signature and the
# engine's self-test, start Jervis, check the engine comes up, quit, check nothing is left running, remove the app.
#     bash tests/installer/mac_smoke.sh path/to/Jervis-x.y.z-arm64.dmg
set -euo pipefail
DMG="$1"
WORK="$(mktemp -d)"
MOUNT="$WORK/mnt"; APPS="$WORK/Applications"; mkdir -p "$MOUNT" "$APPS"
DATA="$HOME/Library/Application Support/Jervis"
LOG="$DATA/logs/jervis.log"
ENGINE="Jervis.app/Contents/Resources/backend/jervis-backend"

hdiutil attach "$DMG" -nobrowse -readonly -mountpoint "$MOUNT" >/dev/null
cp -R "$MOUNT/Jervis.app" "$APPS/"
hdiutil detach "$MOUNT" >/dev/null
APP="$APPS/Jervis.app"
echo "installed to $APP ($(du -sh "$APP" | cut -f1))"

codesign --verify --deep --strict "$APP" && echo "signature: consistent (ad-hoc)"
JERVIS_DATA_DIR="$WORK/selftest" "$APP/Contents/Resources/backend/jervis-backend" --selftest | grep '^SELFTEST' | grep -q '"ok": true' \
  && echo "engine self-test: passed"

# Start the app the way a user would (hidden in the tray, as at sign-in), without the microphone or the AI download.
export JERVIS_NO_AI_SETUP=1 JERVIS_AUDIO=off
: > "$WORK/window.out"
START=$(date +%s)
"$APP/Contents/MacOS/Jervis" --hidden >> "$WORK/window.out" 2>&1 &
PID=$!
for _ in $(seq 1 120); do
  grep -q "listener is ready" "$LOG" 2>/dev/null && break
  sleep 1
done
if ! grep -q "listener is ready" "$LOG" 2>/dev/null; then
  echo "FAIL: the engine did not start"; cat "$WORK/window.out"; tail -40 "$LOG" 2>/dev/null || true; exit 1
fi
echo "engine started in $(( $(date +%s) - START ))s"
pgrep -f "$ENGINE" >/dev/null || { echo "FAIL: engine process missing"; exit 1; }

"$APP/Contents/MacOS/Jervis" --quit
for _ in $(seq 1 30); do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
if kill -0 "$PID" 2>/dev/null; then echo "FAIL: Jervis did not quit"; kill "$PID"; exit 1; fi
sleep 1
if pgrep -f "$ENGINE" >/dev/null; then echo "FAIL: the engine was left running after quitting"; exit 1; fi
echo "quit: window and engine both stopped"

# His window ended by force (a crash, Activity Monitor): the engine must not keep running on its own.
: > "$LOG"
"$APP/Contents/MacOS/Jervis" --hidden >> "$WORK/window.out" 2>&1 &
PID=$!
for _ in $(seq 1 120); do grep -q "listener is ready" "$LOG" 2>/dev/null && break; sleep 1; done
kill -9 "$PID"
for i in $(seq 1 15); do pgrep -f "$ENGINE" >/dev/null || break; sleep 1; done
if pgrep -f "$ENGINE" >/dev/null; then echo "FAIL: the engine kept running after its window was ended"; exit 1; fi
echo "window ended by force: the engine stopped by itself within ${i}s"

rm -rf "$WORK"
echo "PASS"
