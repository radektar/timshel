#!/bin/bash
# scripts/create_dmg.sh
# Creates a professional DMG for Timshel

set -e

APP_NAME="Timshel"
# Read version directly from source to avoid importing setup_app.py
# (import may fail on system python without setuptools/py2app).
VERSION=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' setup_app.py | head -n 1)
if [ -z "${VERSION}" ]; then
    echo "❌ Error: Could not read APP_VERSION from setup_app.py"
    exit 1
fi
DMG_FILENAME="${APP_NAME}-${VERSION}-ARM64-UNSIGNED.dmg"
DIST_DIR="dist"
APP_PATH="${DIST_DIR}/${APP_NAME}.app"
DMG_BACKGROUND="assets/dmg_background.png"
DMG_VOLICON="assets/icon.icns"
INFO_PLIST="${APP_PATH}/Contents/Info.plist"

echo "📦 Creating DMG for ${APP_NAME} v${VERSION}..."

# Check if .app exists
if [ ! -d "${APP_PATH}" ]; then
    echo "❌ Error: ${APP_PATH} not found. Build the app first using scripts/build_app.sh"
    exit 1
fi

# Ensure app bundle version matches setup_app.py to avoid mislabeled DMG files.
if [ -f "${INFO_PLIST}" ]; then
    BUNDLE_VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "${INFO_PLIST}" 2>/dev/null || echo "")
    if [ "${BUNDLE_VERSION}" != "${VERSION}" ]; then
        echo "⚠️  Bundle version (${BUNDLE_VERSION}) differs from setup_app.py (${VERSION})."
        echo "🔨 Rebuilding app bundle to match DMG version..."
        ./scripts/build_app.sh
    fi
fi

# A broken seal must never reach a DMG: Gatekeeper rejects it on the tester's
# Mac with no useful message. Verify here — the release path (build-dmg /
# release) does not run the smoke test, so this is its only signature gate.
if ! codesign --verify --strict --deep "${APP_PATH}"; then
    echo "❌ Error: codesign verification failed for ${APP_PATH}."
    echo "   The bundle's seal is broken (a stray write into dist/?)."
    echo "   Rebuild with scripts/build_app.sh before packaging."
    exit 1
fi
echo "✅ Code signature verified"

# Remove old DMG if exists
rm -f "${DIST_DIR}/${DMG_FILENAME}"

# Create DMG
# Settings:
# - Window position: 200, 120
# - Window size: 600, 400
# - Icon size: 100
# - App icon position: 175, 190
# - Applications link position: 425, 190
create-dmg \
  --volname "${APP_NAME} Installer" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --background "${DMG_BACKGROUND}" \
  --icon-size 100 \
  --icon "${APP_NAME}.app" 175 190 \
  --hide-extension "${APP_NAME}.app" \
  --app-drop-link 425 190 \
  --volicon "${DMG_VOLICON}" \
  --no-internet-enable \
  "${DIST_DIR}/${DMG_FILENAME}" \
  "${APP_PATH}"

echo "✅ DMG created: ${DIST_DIR}/${DMG_FILENAME}"
echo "📏 Size: $(du -sh "${DIST_DIR}/${DMG_FILENAME}" | cut -f1)"

# Verify the copy that actually ships. The gate above checked the source
# bundle; this checks what the tester will double-click, so a copy that lost
# or altered a sealed file cannot leave the machine reported as verified.
echo "🔍 Verifying the signature inside the DMG..."
MOUNT_POINT="$(mktemp -d "${TMPDIR:-/tmp}/timshel-dmg-verify.XXXXXX")"
# 0 = verified good, 1 = verified BAD (delete), 2 = could not verify (keep).
# Conflating the last two would delete a good image just because the machine
# could not mount it (already attached, no mount rights in CI, …).
DMG_VERIFY_STATUS=2
if hdiutil attach "${DIST_DIR}/${DMG_FILENAME}" -mountpoint "${MOUNT_POINT}" \
    -nobrowse -readonly -quiet; then
    if codesign --verify --strict --deep "${MOUNT_POINT}/${APP_NAME}.app"; then
        DMG_VERIFY_STATUS=0
    else
        DMG_VERIFY_STATUS=1
    fi
    hdiutil detach "${MOUNT_POINT}" -quiet || hdiutil detach "${MOUNT_POINT}" -force -quiet || true
fi
rmdir "${MOUNT_POINT}" 2>/dev/null || true

case "${DMG_VERIFY_STATUS}" in
  0) echo "✅ Signature verified inside the DMG" ;;
  1) echo "❌ Error: the app inside the DMG fails codesign verification."
     echo "   Do not ship this image — rebuild and repackage."
     rm -f "${DIST_DIR}/${DMG_FILENAME}"
     exit 1 ;;
  *) echo "❌ Error: could not mount ${DMG_FILENAME} to verify it."
     echo "   The image is KEPT at ${DIST_DIR}/${DMG_FILENAME} — verify it by"
     echo "   hand before shipping: open it, then"
     echo "   codesign --verify --strict --deep /Volumes/*/${APP_NAME}.app"
     exit 1 ;;
esac
