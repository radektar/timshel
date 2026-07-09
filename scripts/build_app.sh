#!/bin/bash
# Build script for Timshel.app using py2app
# This script builds a macOS application bundle ready for distribution

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

echo "🔨 Building Timshel.app..."
echo "Project root: ${PROJECT_ROOT}"

# Check if we're on macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "❌ Error: This script must be run on macOS"
    exit 1
fi

# Check if we're on Apple Silicon
ARCH=$(uname -m)
if [[ "${ARCH}" != "arm64" ]]; then
    echo "⚠️  Warning: Building on ${ARCH}, but bundle will be for arm64 only"
fi

# Activate virtual environment. py2app bundles under python3.12 (see BUNDLE_SITE
# below), so the build MUST run on 3.12 — prefer venv312, then venv, then system.
if [ -d "venv312" ]; then
    echo "📦 Activating virtual environment (venv312)..."
    source venv312/bin/activate
elif [ -d "venv" ]; then
    echo "📦 Activating virtual environment (venv)..."
    source venv/bin/activate
else
    echo "⚠️  Warning: no venv found, using system Python"
fi

# Hard guard: the bundle layout is pinned to python3.12. Fail fast instead of
# silently building an incompatible bundle on 3.9/3.14.
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'; then
    echo "❌ Error: build requires Python 3.12 (active: $(python3 -V 2>&1))"
    echo "   Create it with: python3.12 -m venv venv312 && source venv312/bin/activate && make install"
    exit 1
fi

# Check if py2app is installed
if ! python3 -c "import py2app" 2>/dev/null; then
    echo "📥 Installing py2app..."
    pip install py2app
else
    echo "✅ py2app already installed"
fi

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf build dist

# Check if icon exists
if [ ! -f "assets/icon.icns" ]; then
    echo "⚠️  Warning: assets/icon.icns not found, building without icon"
fi

# Build the application
echo "🔨 Running py2app..."
# Note: py2app may segfault during import checking, but bundle is usually complete
# We check for bundle existence after build regardless of exit code
set +e  # Temporarily disable exit on error
python3 setup_app.py py2app
BUILD_EXIT_CODE=$?
set -e  # Re-enable exit on error

# Verify build - bundle should exist even if build ended with segfault
if [ ! -d "dist/Timshel.app" ]; then
    echo "❌ Error: Build failed - Timshel.app not found"
    exit 1
fi

# Warn if build ended with segfault but bundle exists
if [ $BUILD_EXIT_CODE -ne 0 ]; then
    echo "⚠️  Warning: Build ended with exit code $BUILD_EXIT_CODE (may be segfault during import checking)"
    echo "   Bundle exists and will be verified..."
fi

# Check bundle size
BUNDLE_SIZE=$(du -sh dist/Timshel.app | cut -f1)
BUNDLE_SIZE_BYTES=$(du -sk dist/Timshel.app | cut -f1)
BUNDLE_SIZE_MB=$((BUNDLE_SIZE_BYTES / 1024))

echo "✅ Build complete!"
echo "📦 Bundle location: dist/Timshel.app"
echo "📏 Bundle size: ${BUNDLE_SIZE} (${BUNDLE_SIZE_MB} MB)"

# Check if size is reasonable (<20MB without models)
if [ "${BUNDLE_SIZE_MB}" -gt 20 ]; then
    echo "⚠️  Warning: Bundle size (${BUNDLE_SIZE_MB} MB) exceeds 20MB target"
    echo "   Consider optimizing excludes in setup_app.py"
else
    echo "✅ Bundle size is within target (<20MB)"
fi

# Verify bundle structure
echo "🔍 Verifying bundle structure..."
if [ ! -f "dist/Timshel.app/Contents/Info.plist" ]; then
    echo "❌ Error: Info.plist not found"
    exit 1
fi

if [ ! -f "dist/Timshel.app/Contents/MacOS/Timshel" ]; then
    echo "❌ Error: Main executable not found"
    exit 1
fi

# Verify critical Python packages are bundled
REQUIRED_PKGS=("anthropic" "rumps" "mutagen" "httpx" "click" "dotenv")
BUNDLE_SITE="dist/Timshel.app/Contents/Resources/lib/python3.12"
for pkg in "${REQUIRED_PKGS[@]}"; do
    if [ ! -d "${BUNDLE_SITE}/${pkg}" ]; then
        echo "❌ Error: required package '${pkg}' not found in bundle"
        exit 1
    fi
done
echo "✅ All required Python packages verified in bundle"

# Make executable
chmod +x dist/Timshel.app/Contents/MacOS/Timshel

# Remove dangling symlinks before signing. py2app leaves a vestigial
# Resources/lib/python3.12/site.pyo -> ../../site.pyo (Python 3.12 dropped .pyo),
# which breaks `codesign --verify --strict` ("No such file or directory") and
# would make the installed bundle fail Gatekeeper.
echo "🧹 Pruning dangling symlinks..."
find dist/Timshel.app -type l ! -exec test -e {} \; -delete 2>/dev/null || true

# Sign bundle (Developer ID if available, otherwise ad-hoc for local installs)
if [ -n "${APPLE_DEVELOPER_ID:-}" ]; then
    echo "🔏 Signing app with Developer ID: ${APPLE_DEVELOPER_ID}"
    codesign --force --deep --sign "${APPLE_DEVELOPER_ID}" dist/Timshel.app
else
    echo "🔏 Signing app with ad-hoc certificate (local install mode)"
    codesign --force --deep --sign - dist/Timshel.app
fi

echo ""
echo "✅ Build verification complete!"
echo ""
echo "To test the app:"
echo "  open dist/Timshel.app"
echo ""
echo "To check bundle info:"
echo "  plutil -p dist/Timshel.app/Contents/Info.plist"

