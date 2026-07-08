#!/bin/bash
# scripts/build_release.sh
# Orchestrates the full build and release pipeline for Timshel

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

APP_NAME="Timshel"
PLATFORM="$(uname -s)"

echo "🚀 Starting release build for ${APP_NAME}..."

case "${PLATFORM}" in
    Darwin)
        echo "🍎 Platform: macOS (Darwin)"
        
        # 1. Build .app bundle
        echo "--- Step 1: Building .app bundle ---"
        bash scripts/build_app.sh
        
        # 2. Create DMG
        echo "--- Step 2: Creating DMG installer ---"
        bash scripts/create_dmg.sh
        
        # 3. Generate checksums
        echo "--- Step 3: Generating checksums ---"
        # Checksum the DMG that Step 2 actually produced — don't reconstruct its
        # name from a version string read by the *system* python3 (which lacks
        # this project's deps, so the import failed, fell back to a wrong name,
        # and the checksum was silently skipped).
        DMG_FILE="$(ls -t dist/${APP_NAME}-*-ARM64-UNSIGNED.dmg 2>/dev/null | head -1)"

        if [ -n "${DMG_FILE}" ] && [ -f "${DMG_FILE}" ]; then
            shasum -a 256 "${DMG_FILE}" > "${DMG_FILE}.sha256"
            echo "✅ Checksum generated: ${DMG_FILE}.sha256"
            echo "   $(cat "${DMG_FILE}.sha256")"
        else
            echo "⚠️  No DMG found in dist/ to checksum"
        fi
        
        echo ""
        echo "🎉 Release build complete!"
        echo "📂 Location: dist/"
        ;;
    
    MINGW*|MSYS*|CYGWIN*)
        echo "🪟 Platform: Windows"
        echo "❌ Error: Windows build pipeline is not yet implemented."
        echo "   Planned: PyInstaller + NSIS/Inno Setup. See BACKLOG.md"
        exit 1
        ;;
        
    *)
        echo "❓ Platform: ${PLATFORM} (Unknown)"
        echo "❌ Error: Unsupported platform for release build."
        exit 1
        ;;
esac
