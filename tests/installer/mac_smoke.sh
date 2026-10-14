#!/bin/bash
# Fresh-install test for the macOS build: install from the .dmg into a scratch folder, check the signature and the
# engine's self-test, start Jarvis, check the engine comes up, quit, check nothing is left running, remove the app.
#     bash tests/installer/mac_smoke.sh path/to/Jarvis-x.y.z-arm64.dmg
set -euo pipefail
DMG="$1"
WORK="$(mktemp -d)"
MOUNT="$WORK/mnt"; APPS="$WORK/Applications"; mkdir -p "$MOUNT" "$APPS"
DATA="$HOME/Library/Application Support/Jarvis"
LOG="$DATA/logs/jarvis.log"
ENGINE="Jarvis.app/Contents/Resources/backend/jarvis-backend"

# Whatever happens, leave nothing running and nothing mounted.
cleanup() {
  pkill -f "$APPS/Jarvis.app/Contents/MacOS/Jarvis" 2>/dev/null || true
  hdiutil detach "$MOUNT" >/dev/null 2>&1 || true
  # the sign-in agent this test's copy wrote points at a temporary folder
  grep -qs "$WORK" "$HOME/Library/LaunchAgents/io.github.arielzaha.jervis.plist" && rm -f "$HOME/Library/LaunchAgents/io.github.arielzaha.jervis.plist"
  true
}
trap cleanup EXIT

hdiutil attach "$DMG" -nobrowse -readonly -mountpoint "$MOUNT" >/dev/null
cp -R "$MOUNT/Jarvis.app" "$APPS/"
hdiutil detach "$MOUNT" >/dev/null
APP="$APPS/Jarvis.app"
echo "installed to $APP ($(du -sh "$APP" | cut -f1))"

codesign --verify --deep --strict "$APP" && echo "signature: valid"
REQ="$(codesign -d -r- "$APP" 2>&1 | grep designated)"
echo "designated requirement: $REQ"
if [ -n "${JARVIS_MAC_IDENTITY:-}" ] && ! grep -Eq "certificate (leaf|root) = H" <<<"$REQ"; then
  echo "FAIL: not signed with Jarvis's certificate (permissions would be lost on every update)"; exit 1
fi
JARVIS_DATA_DIR="$WORK/selftest" "$APP/Contents/Resources/backend/jarvis-backend" --selftest | grep '^SELFTEST' | grep -q '"ok": true' \
  && echo "engine self-test: passed"

# Start the app the way a user would (hidden in the tray, as at sign-in), without the microphone or the AI download.
export JARVIS_NO_AI_SETUP=1 JARVIS_AUDIO=off
rm -f "$LOG"   # a log left by an earlier run must not count as this start
: > "$WORK/window.out"
START=$(date +%s)
"$APP/Contents/MacOS/Jarvis" --hidden >> "$WORK/window.out" 2>&1 &
PID=$!
for _ in $(seq 1 120); do
  grep -q "listener is ready" "$LOG" 2>/dev/null && break
  sleep 1
done
if ! grep -q "listener is ready" "$LOG" 2>/dev/null; then
  echo "FAIL: the engine did not start"; cat "$WORK/window.out"; tail -40 "$LOG" 2>/dev/null || true; exit 1
fi
echo "engine started in $(( $(date +%s) - START ))s"
AGENT="$HOME/Library/LaunchAgents/io.github.arielzaha.jervis.plist"
grep -q -- "--hidden" "$AGENT" 2>/dev/null || { echo "FAIL: not set to start (hidden) at sign-in"; exit 1; }
echo "starts at sign-in, hidden: $AGENT"
pgrep -f "$ENGINE" >/dev/null || { echo "FAIL: engine process missing"; exit 1; }

"$APP/Contents/MacOS/Jarvis" --quit
for _ in $(seq 1 30); do kill -0 "$PID" 2>/dev/null || break; sleep 1; done
if kill -0 "$PID" 2>/dev/null; then echo "FAIL: Jarvis did not quit"; kill "$PID"; exit 1; fi
sleep 1
if pgrep -f "$ENGINE" >/dev/null; then echo "FAIL: the engine was left running after quitting"; exit 1; fi
echo "quit: window and engine both stopped"

# His window ended by force (a crash, Activity Monitor): the engine must not keep running on its own.
: > "$LOG"
"$APP/Contents/MacOS/Jarvis" --hidden >> "$WORK/window.out" 2>&1 &
PID=$!
for _ in $(seq 1 120); do grep -q "listener is ready" "$LOG" 2>/dev/null && break; sleep 1; done
kill -9 "$PID"
for i in $(seq 1 15); do pgrep -f "$ENGINE" >/dev/null || break; sleep 1; done
if pgrep -f "$ENGINE" >/dev/null; then echo "FAIL: the engine kept running after its window was ended"; exit 1; fi
echo "window ended by force: the engine stopped by itself within ${i}s"

rm -rf "$WORK"
rm -f "$AGENT"   # it points at this test's temporary copy
echo "PASS"
