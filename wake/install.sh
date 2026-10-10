#!/bin/bash
# Installs Jarvis Wake: say "Hey Jarvis", "Wake up Jarvis" or "Hello Jarvis" — or open the Jarvis app on your paired
# phone — and Jarvis opens, even when Jarvis and VS Code are closed.
#
#     bash wake/install.sh          (run again any time: it updates everything in place)
#
# What it puts where (nothing inside the iCloud-synced Desktop, which can offload files and stall a start at sign-in):
#   ~/Applications/Jarvis Wake.app                       the small app that owns the microphone permission
#   ~/Library/Application Support/JarvisWake/            the listener, its own Python environment, the speech model
#   ~/Library/LaunchAgents/io.github.arielzaha.jervis-wake.plist   starts it at sign-in and keeps it running
#   ~/Library/Logs/JarvisWake/                           logs
# Jarvis itself is started from this project folder, exactly as usual.
set -euo pipefail

LABEL="io.github.arielzaha.jervis-wake"
OLD_LABEL="com.ariel.jervis.wake-listener"   # a much older listener, removed if found (its real, old name)
HERE="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$HERE/.." && pwd)"
SUPPORT="$HOME/Library/Application Support/JarvisWake"
APP="$HOME/Applications/Jarvis Wake.app"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"
LOGS="$HOME/Library/Logs/JarvisWake"
MODEL_URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
DOMAIN="gui/$(id -u)"

say() { printf '\033[1m%s\033[0m\n' "$*"; }
fail() { printf 'Jarvis Wake was not installed: %s\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || fail "this is for macOS."
[ -f "$PROJECT/app.py" ] || fail "app.py isn't in $PROJECT."
[ -x "$PROJECT/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron" ] || \
  fail "Jarvis's window isn't set up yet. Run 'npm install' in $PROJECT (or start Jarvis once with run.py), then try again."
[ -x "$PROJECT/venv/bin/python" ] || \
  fail "Jarvis's Python environment isn't set up yet. Start Jarvis once with 'python3 run.py' in $PROJECT, then try again."

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

# Jarvis was called Jervis: an install from before the rename is taken over (its Python environment and speech
# model move, nothing is downloaded again) and its old app is removed.
OLD_SUPPORT="$HOME/Library/Application Support/JervisWake"
if [ -d "$OLD_SUPPORT" ] && [ ! -e "$SUPPORT" ]; then
  say "Moving the existing install over from its old name…"
  mv "$OLD_SUPPORT" "$SUPPORT"
fi
rm -rf "$HOME/Applications/Jervis Wake.app"

say "Installing the listener in ${SUPPORT}…"
mkdir -p "$SUPPORT" "$LOGS"
cp "$HERE/jarvis_wake.py" "$SUPPORT/jarvis_wake.py"
printf '{"project": "%s"}\n' "$PROJECT" > "$SUPPORT/config.json"

if [ ! -x "$SUPPORT/venv/bin/python3" ]; then
  "$PY" -m venv "$SUPPORT/venv"
fi
say "Installing its packages (Vosk speech recognition, sounddevice, numpy, websockets, cryptography)…"
"$SUPPORT/venv/bin/python3" -m pip install --quiet --disable-pip-version-check --upgrade pip
"$SUPPORT/venv/bin/python3" -m pip install --quiet --disable-pip-version-check "vosk==0.3.44" "sounddevice>=0.4.6" "numpy>=1.26" "websockets>=13" "cryptography>=42"

if [ ! -f "$SUPPORT/model/am/final.mdl" ]; then
  say "Downloading the wake-phrase model (40 MB, once)…"
  rm -rf "$SUPPORT/model" "$SUPPORT/model.zip" "$SUPPORT/vosk-model-small-en-us-0.15"
  curl -fL --retry 5 --retry-delay 2 -C - --progress-bar -o "$SUPPORT/model.zip" "$MODEL_URL"
  (cd "$SUPPORT" && unzip -q model.zip && mv vosk-model-small-en-us-0.15 model && rm model.zip)
fi
"$SUPPORT/venv/bin/python3" "$SUPPORT/jarvis_wake.py" --check || fail "the listener's packages or model don't load."

say "Building Jarvis Wake.app…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
clang -O2 -Wall -o "$APP/Contents/MacOS/jarvis-wake" "$HERE/launcher.c"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>$LABEL</string>
  <key>CFBundleName</key><string>Jarvis Wake</string>
  <key>CFBundleDisplayName</key><string>Jarvis Wake</string>
  <key>CFBundleExecutable</key><string>jarvis-wake</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSUIElement</key><true/>
  <key>NSMicrophoneUsageDescription</key>
  <string>Jarvis Wake listens for “Hey Jarvis” so it can open Jarvis. The sound is checked on this Mac and is never recorded or sent anywhere.</string>
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
codesign --verify "$APP" || fail "Jarvis Wake.app couldn't be signed."

say "Setting it to start when you sign in…"
mkdir -p "$(dirname "$AGENT")"
cat > "$AGENT" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$APP/Contents/MacOS/jarvis-wake</string></array>
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
if [ -n "${JARVIS_WAKE_NO_START:-}" ]; then echo "Installed (not started: JARVIS_WAKE_NO_START is set)."; exit 0; fi
launchctl bootstrap "$DOMAIN" "$AGENT"
launchctl enable "$DOMAIN/$LABEL"

sleep 3
if launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -q "state = running"; then
  say "Jarvis Wake is running."
else
  echo "Jarvis Wake didn't start. See $LOGS/agent.log and $LOGS/wake.log."
  exit 1
fi
cat <<EOF

Next:
  1. macOS asks "“Jarvis Wake” would like to access the microphone": click Allow.
     (No question? System Settings > Privacy & Security > Microphone: turn on Jarvis Wake.)
  2. Quit Jarvis and VS Code, then say "Hey Jarvis". Jarvis opens and says "I'm awake, how can I help you?"

Log:        tail -f "$LOGS/wake.log"
Status:     launchctl print $DOMAIN/$LABEL | grep state
Uninstall:  bash "$HERE/uninstall.sh"
EOF
