#!/bin/zsh

PLIST_NAME="com.ariel.jervis.wake-listener"
PLIST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
rm -f "$PLIST"

echo "Jervis Wake Listener removed from automatic startup."
