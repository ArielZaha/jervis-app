#!/bin/zsh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="/usr/local/bin/python3"
LISTENER="$SCRIPT_DIR/wake_listener.py"
PLIST_NAME="com.ariel.jervis.wake-listener"
PLIST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
LOG_DIR="$SCRIPT_DIR/logs"

if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3)"
fi

if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
    echo "Could not find python3."
    exit 1
fi

if [ ! -f "$LISTENER" ]; then
    echo "wake_listener.py was not found next to this installer."
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$LOG_DIR"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>$LISTENER</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ProcessType</key>
    <string>Background</string>

    <key>StandardOutPath</key>
    <string>$LOG_DIR/wake_listener.log</string>

    <key>StandardErrorPath</key>
    <string>$LOG_DIR/wake_listener_error.log</string>
</dict>
</plist>
EOF

# Stop an older copy if one exists.
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true

launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$PLIST_NAME"
launchctl kickstart -k "gui/$(id -u)/$PLIST_NAME"

echo
echo "=============================================="
echo "Jervis Wake Listener installed successfully."
echo "=============================================="
echo
echo 'It will start automatically when you log into your Mac.'
echo 'Say: "Wake Up Jervis"'
echo
echo "Listener: $LISTENER"
echo "LaunchAgent: $PLIST"
echo
echo "IMPORTANT:"
echo "macOS may ask Terminal/Python for Microphone permission."
echo "If prompted, allow it in System Settings > Privacy & Security > Microphone."
echo
echo "Log file: $LOG_DIR/wake_listener.log"
echo
