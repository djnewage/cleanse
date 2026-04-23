#!/bin/bash
set -e

# Read version from package.json
VERSION=$(node -p "require('./package.json').version")
TAG="v$VERSION"

echo "=== Cleanse Release $TAG ==="
echo ""

# Check we're on master
BRANCH=$(git branch --show-current)
if [ "$BRANCH" != "master" ]; then
  echo "Error: Must be on master branch (currently on '$BRANCH')"
  exit 1
fi

# Check for uncommitted changes
if ! git diff-index --quiet HEAD --; then
  echo "Error: Uncommitted changes detected. Commit or stash first."
  exit 1
fi

# Check if release already exists
if gh release view "$TAG" &>/dev/null; then
  echo "Error: Release $TAG already exists on GitHub"
  exit 1
fi

# Clean previous dist
rm -f dist/*.dmg dist/*.zip dist/latest-mac.yml

# Build ARM64 (Apple Silicon)
echo "=== Building ARM64 (Apple Silicon) ==="
npm run build:mac

# Build x64 (Intel)
echo ""
echo "=== Building x64 (Intel) ==="
npm run build:mac:x64

# Guardrail: ensure macOS-14-only FFmpeg/torchcodec dylibs never ship again.
# A torch>=2.0 float pin silently resolved to torch 2.10 + mandatory torchcodec,
# whose bundled libav* dylibs link AVFoundation symbols absent on macOS 13.
echo ""
echo "=== Verifying bundles contain no forbidden dylibs ==="
checked_any=0
for bundle in dist/mac-arm64/Cleanse.app dist/mac/Cleanse.app; do
  [ -d "$bundle" ] || continue
  checked_any=1
  bad=$(find "$bundle" \( -name 'libtorchcodec*' -o -name 'libavdevice*' \
                       -o -name 'libavutil*.dylib' -o -name 'libavcodec*.dylib' \
                       -o -name 'libavformat*.dylib' -o -name 'libavfilter*.dylib' \
                       -o -name 'libswscale*.dylib' -o -name 'libswresample*.dylib' \) 2>/dev/null)
  if [ -n "$bad" ]; then
    echo "ERROR: Forbidden dylibs found in $bundle:"
    echo "$bad"
    echo ""
    echo "These pull in macOS-14-only AVFoundation symbols and break users on macOS 13."
    echo "Audit backend/requirements.txt and cleanse-backend.spec."
    exit 1
  fi
done
if [ "$checked_any" = "0" ]; then
  echo "ERROR: No app bundles found under dist/; build output unexpected."
  exit 1
fi
echo "OK: no forbidden dylibs in bundles."

# Find built artifacts
DMG_FILES=$(ls dist/*-${VERSION}-*.dmg 2>/dev/null || true)
ZIP_FILES=$(ls dist/*-${VERSION}-*.zip 2>/dev/null || true)

if [ -z "$DMG_FILES" ]; then
  echo "Error: No .dmg files found in dist/"
  exit 1
fi

if [ -z "$ZIP_FILES" ]; then
  echo "Error: No .zip files found in dist/"
  exit 1
fi

echo ""
echo "Artifacts to upload:"
for f in $DMG_FILES $ZIP_FILES; do
  echo "  $f ($(du -h "$f" | cut -f1))"
done

# Generate latest-mac.yml for electron-updater (uses ZIP files for auto-update)
echo ""
echo "Generating latest-mac.yml..."

RELEASE_DATE=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")

cat > dist/latest-mac.yml << YMLEOF
version: ${VERSION}
files:
YMLEOF

for f in $ZIP_FILES; do
  FNAME=$(basename "$f")
  FSIZE=$(stat -f%z "$f")
  FSHA512=$(shasum -a 512 "$f" | awk '{print $1}' | xxd -r -p | base64)
  cat >> dist/latest-mac.yml << YMLEOF
  - url: ${FNAME}
    sha512: ${FSHA512}
    size: ${FSIZE}
YMLEOF
done

# Use the arm64 ZIP as the default path
ARM64_ZIP=$(ls dist/*-${VERSION}-arm64.zip 2>/dev/null | head -1)
if [ -n "$ARM64_ZIP" ]; then
  ARM64_SHA=$(shasum -a 512 "$ARM64_ZIP" | awk '{print $1}' | xxd -r -p | base64)
  cat >> dist/latest-mac.yml << YMLEOF
path: $(basename "$ARM64_ZIP")
sha512: ${ARM64_SHA}
YMLEOF
fi

cat >> dist/latest-mac.yml << YMLEOF
releaseDate: '${RELEASE_DATE}'
YMLEOF

echo "Generated dist/latest-mac.yml"
cat dist/latest-mac.yml
echo ""

# Create the release (upload DMGs for manual download + ZIPs for auto-update + metadata)
echo "Creating GitHub release $TAG..."
NOTES="${RELEASE_NOTES:-Bug fixes and improvements.}"
gh release create "$TAG" \
  --title "$TAG" \
  --notes "$NOTES" \
  $DMG_FILES $ZIP_FILES dist/latest-mac.yml

echo ""
echo "Release $TAG published!"
echo "https://github.com/djnewage/cleanse/releases/tag/$TAG"
