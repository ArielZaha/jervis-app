#!/bin/bash
# Removes Jervis Wake (the listener, its app, its sign-in entry and its model). Jervis himself isn't touched; the logs
# stay in ~/Library/Logs/JervisWake.
#     bash wake/uninstall.sh
LABEL="io.github.arielzaha.jervis-wake"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/Applications/Jervis Wake.app" "$HOME/Library/Application Support/JervisWake"
tccutil reset Microphone "$LABEL" >/dev/null 2>&1 || true
echo "Jervis Wake is removed. Jervis no longer opens by voice while he's closed."
