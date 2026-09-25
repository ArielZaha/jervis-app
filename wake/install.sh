#!/bin/bash
# Installs Jervis Wake: say "Hey Jervis", "Wake up Jervis" or "Hello Jervis" and Jervis opens, even when Jervis and
# VS Code are closed.
#
#     bash wake/install.sh          (run again any time: it updates everything in place)
#
# What it puts where (nothing inside the iCloud-synced Desktop, which can offload files and stall a start at sign-in):
#   ~/Applications/Jervis Wake.app                       the small app that owns the microphone permission
#   ~/Library/Application Support/JervisWake/            the listener, its own Python environment, the speech model
#   ~/Library/LaunchAgents/io.github.arielzaha.jervis-wake.plist   starts it at sign-in and keeps it running
#   ~/Library/Logs/JervisWake/                           logs
# Jervis itself is started from this project folder, exactly as usual.
set -euo pipefail

LABEL="io.github.arielzaha.jervis-wake"
OLD_LABEL="com.ariel.jervis.wake-listener"
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/.." && pwd)"
SUPPORT="$HOME/Library/Application Support/JervisWake"
APP="$HOME/Applications/Jervis Wake.app"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGS="$HOME/Library/Logs/JervisWake"
MODEL_URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
DOMAIN="gui/$(id -u)"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf 'Jervis Wake was not installed: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "this is for macOS."
[ -f "$PROJECT/app.py" ] || fail "app.py isn't in $PROJECT."
[ -x "$PROJECT/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron" ] || \
  fail "Jervis's window isn't set up yet. Run 'npm install' in $PROJECT (or start Jervis once with run.py), then try again."
[ -x "$PROJECT/venv/bin/python" ] || \
  fail "Jervis's Python environment isn't set up yet. Start Jervis once with 'python3 run.py' in $PROJECT, then try again."

PY=""
for candidate in /opt/homebrew/bin/python3.14 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3 \
                 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/local/bin/python3; do
  if [ -x "$candidate" ] && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || fail "no Python 3.9 or newer found. Install one with 'brew install python'."
command -v clang >/dev/null || fail "the Command Line Tools are missing. Run 'xcode-select --install', then try again."

mkdir -p "$LOGS"
say "Stopping any listener that's already running…"
launchctl bootout "$DOMAIN/$OLD_LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
if [ -f "$HOME/Library/LaunchAgents/$OLD_LABEL.plist" ]; then
  mv "$HOME/Library/LaunchAgents/$OLD_LABEL.plist" "$LOGS/old-wake-listener.plist.backup" 2>/dev/null || true
fi

say "Installing the listener in ${SUPPORT}…"
mkdir -p "$SUPPORT" "$LOGS"
cp "$HERE/jervis_wake.py" "$SUPPORT/jervis_wake.py"
printf '{"project": "%s"}\n' "$PROJECT" > "$SUPPORT/config.json"

if [ ! -x "$SUPPORT/venv/bin/python3" ]; then
  "$PY" -m venv "$SUPPORT/venv"
fi
say "Installing its packages (Vosk speech recognition, sounddevice, numpy)…"
"$SUPPORT/venv/bin/python3" -m pip install --quiet --disable-pip-version-check --upgrade pip
"$SUPPORT/venv/bin/python3" -m pip install --quiet --disable-pip-version-check "vosk==0.3.44" "sounddevice>=0.4.6" "numpy>=1.26"

if [ ! -f "$SUPPORT/model/am/final.mdl" ]; then
  say "Downloading the wake-phrase model (40 MB, once)…"
  rm -rf "$SUPPORT/model" "$SUPPORT/model.zip" "$SUPPORT/vosk-model-small-en-us-0.15"
  curl -fL --retry 5 --retry-delay 2 -C - --progress-bar -o "$SUPPORT/model.zip" "$MODEL_URL"
  (cd "$SUPPORT" && unzip -q model.zip && mv vosk-model-small-en-us-0.15 model && rm model.zip)
fi
"$SUPPORT/venv/bin/python3" "$SUPPORT/jervis_wake.py" --check || fail "the listener's packages or model don't load."

say "Building Jervis Wake.app…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
clang -O2 -Wall -o "$APP/Contents/MacOS/jervis-wake" "$HERE/launcher.c"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>$LABEL</string>
  <key>CFBundleName</key><string>Jervis Wake</string>
  <key>CFBundleDisplayName</key><string>Jervis Wake</string>
  <key>CFBundleExecutable</key><string>jervis-wake</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Jervis Wake listens for “Hey Jervis” so it can open Jervis. The sound is checked on this Mac and is never recorded or sent anywhere.</string>
</dict>
</plist>
EOF
if [ -f "$PROJECT/assets/icon.png" ]; then
  ICONSET="$(mktemp -d)/AppIcon.iconset"; mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z $size $size "$PROJECT/assets/icon.png" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z $((size * 2)) $((size * 2)) "$PROJECT/assets/icon.png" --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" 2>/dev/null || true
fi
xattr -cr "$APP" 2>/dev/null || true
codesign --force --sign - --identifier "$LABEL" "$APP" 2>/dev/null
codesign --verify "$APP" || fail "Jervis Wake.app couldn't be signed."

say "Setting it to start when you sign in…"
mkdir -p "$(dirname "$AGENT")"
cat > "$AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$APP/Contents/MacOS/jervis-wake</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Interactive</string>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>StandardOutPath</key><string>$LOGS/agent.log</string>
  <key>StandardErrorPath</key><string>$LOGS/agent.log</string>
</dict>
</plist>
EOF
plutil -lint "$AGENT" >/dev/null
if [ -n "${JERVIS_WAKE_NO_START:-}" ]; then echo "Installed (not started: JERVIS_WAKE_NO_START is set)."; exit 0; fi
launchctl bootstrap "$DOMAIN" "$AGENT"
launchctl enable "$DOMAIN/$LABEL"

sleep 3
if launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -q "state = running"; then
  say "Jervis Wake is running."
else
  echo "Jervis Wake didn't start. See $LOGS/agent.log and $LOGS/wake.log."
  exit 1
fi
cat <<EOF

Next:
  1. macOS asks "“Jervis Wake” would like to access the microphone": click Allow.
     (No question? System Settings > Privacy & Security > Microphone: turn on Jervis Wake.)
  2. Quit Jervis and VS Code, then say "Hey Jervis". Jervis opens and says "I'm awake, how can I help you?"

Log:        tail -f "$LOGS/wake.log"
Status:     launchctl print $DOMAIN/$LABEL | grep state
Uninstall:  bash "$HERE/uninstall.sh"
EOF
