#!/bin/bash
# Package dist/Surgebar.app into a distributable Surgebar.dmg with a drag-to-
# Applications layout. Run AFTER notarize.sh so the app inside is stapled.
#
# Usage: bash scripts/make_dmg.sh
set -euo pipefail

APP="dist/Surgebar.app"
DMG="dist/Surgebar.dmg"
STAGING="dist/dmg-staging"

[ -d "$APP" ] || { echo "✗ $APP not found — run: python setup_app.py py2app"; exit 1; }

rm -rf "$STAGING" "$DMG"
mkdir -p "$STAGING"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

hdiutil create -volname "Surgebar" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
rm -rf "$STAGING"

echo "✓ Built $DMG"
echo "  Tip: notarize the .dmg too for the cleanest first-open experience:"
echo "    xcrun notarytool submit $DMG --keychain-profile surgebar-notary --wait"
echo "    xcrun stapler staple $DMG"
