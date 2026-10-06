#!/bin/bash
# Removes Jarvis Wake (the listener, its app, its sign-in entry and its model). Jarvis himself isn't touched; the logs
# stay in ~/Library/Logs/JarvisWake.
#     bash wake/uninstall.sh
LABEL="io.github.arielzaha.jervis-wake"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Applications/Jarvis Wake.app" "$HOME/Library/Application Support/JarvisWake"
rm -rf "$HOME/Applications/Jervis Wake.app" "$HOME/Library/Application Support/JervisWake"   # from before the rename
tccutil reset Microphone "$LABEL" >/dev/null 2>&1 || true
echo "Jarvis Wake is removed. Jarvis no longer opens by voice while he's closed."
