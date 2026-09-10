#!/usr/bin/env bash
# Builds Surgebar.app — a real app bundle, which is not optional.
#
# `swift build` alone produces a bare executable, and a bare executable cannot
# put an item in the macOS menu bar: the status item needs a bundle with an
# Info.plist (LSUIElement, so there's no Dock icon) and a code signature. This
# script assembles that bundle and ad-hoc signs it.
set -euo pipefail

CONFIG="${1:-release}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/.build/Surgebar.app"
VERSION="1.1.0"
SOURCE_REVISION="$(git -C "$ROOT" rev-parse HEAD)"

echo "==> Building ($CONFIG)"
swift build -c "$CONFIG" --jobs 1 --package-path "$ROOT"
BIN="$(swift build -c "$CONFIG" --jobs 1 --package-path "$ROOT" --show-bin-path)/Surgebar"

echo "==> Assembling $APP"
if [ -d "$APP" ]; then rm -r "$APP"; fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/Surgebar"
cp "$ROOT/Resources/surgebar.icns" "$APP/Contents/Resources/surgebar.icns"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>Surgebar</string>
  <key>CFBundleIdentifier</key><string>com.talvinder.surgebar</string>
  <key>CFBundleName</key><string>surgebar</string>
  <key>CFBundleIconFile</key><string>surgebar</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>2</string>
  <key>SurgebarSourceRevision</key><string>$SOURCE_REVISION</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
</dict></plist>
PLIST

echo "==> Signing (ad-hoc)"
codesign --force --sign - --identifier com.talvinder.surgebar "$APP"

echo
echo "Built $APP"
echo "Install it with:  ./scripts/install.sh"
