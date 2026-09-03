#!/usr/bin/env bash
# Installs Surgebar.app into /Applications and starts it at login.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/.build/Surgebar.app"
LABEL="com.talvinder.surgebar"
AGENT="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ ! -d "$APP" ]; then
    echo "No app bundle yet — run ./scripts/build-app.sh first."
    exit 1
fi

echo "==> Installing to /Applications"
pkill -f "Surgebar.app/Contents/MacOS/Surgebar" 2>/dev/null || true
sleep 1
if [ -d "/Applications/Surgebar.app" ]; then rm -r "/Applications/Surgebar.app"; fi
cp -R "$APP" /Applications/

echo "==> Setting up start-at-login"
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$AGENT" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/open</string>
        <string>-a</string>
        <string>/Applications/Surgebar.app</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENT"

echo
echo "Done — surgebar is in your menu bar, and will be there after every login."
echo
echo "To uninstall:"
echo "  launchctl bootout gui/\$(id -u)/$LABEL"
echo "  rm \"$AGENT\""
echo "  rm -r /Applications/Surgebar.app"
