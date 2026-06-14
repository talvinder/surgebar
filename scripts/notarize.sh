#!/bin/bash
# Sign + notarize + staple dist/Surgebar.app for distribution to other Macs.
#
# Requires an Apple Developer account ($99/yr) and a "Developer ID Application"
# certificate in your login keychain. One-time: store notarytool credentials with
#   xcrun notarytool store-credentials surgebar-notary \
#     --apple-id "you@example.com" --team-id "XXXXXXXXXX" --password "app-specific-pw"
#
# Usage:
#   DEV_ID="Developer ID Application: Your Name (XXXXXXXXXX)" bash scripts/notarize.sh
set -euo pipefail

APP="dist/Surgebar.app"
KEYCHAIN_PROFILE="${KEYCHAIN_PROFILE:-surgebar-notary}"
DEV_ID="${DEV_ID:?Set DEV_ID to your 'Developer ID Application: …' certificate name}"

[ -d "$APP" ] || { echo "✗ $APP not found — run: python setup_app.py py2app"; exit 1; }

echo "→ Codesigning (hardened runtime, deep)…"
codesign --force --deep --options runtime --timestamp \
  --sign "$DEV_ID" "$APP"

echo "→ Zipping for submission…"
ZIP="dist/Surgebar.zip"
ditto -c -k --keepParent "$APP" "$ZIP"

echo "→ Submitting to Apple notary service (this can take a few minutes)…"
xcrun notarytool submit "$ZIP" --keychain-profile "$KEYCHAIN_PROFILE" --wait

echo "→ Stapling ticket to the app…"
xcrun stapler staple "$APP"

echo "→ Verifying…"
codesign --verify --strict --verbose=2 "$APP"
spctl --assess --type execute --verbose "$APP"

rm -f "$ZIP"
echo "✓ Notarized: $APP"
