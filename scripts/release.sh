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
rm -f dist/*.dmg dist/latest-mac.yml

# Build ARM64 (Apple Silicon)
echo "=== Building ARM64 (Apple Silicon) ==="
npm run build:mac

# Build x64 (Intel)
echo ""
echo "=== Building x64 (Intel) ==="
npm run build:mac:x64

# Find built artifacts
DMG_FILES=$(ls dist/*-${VERSION}-*.dmg 2>/dev/null || true)
if [ -z "$DMG_FILES" ]; then
  echo "Error: No .dmg files found in dist/"
  exit 1
fi

echo ""
echo "Artifacts to upload:"
for f in $DMG_FILES; do
  echo "  $f ($(du -h "$f" | cut -f1))"
done

# Generate latest-mac.yml for electron-updater
echo ""
echo "Generating latest-mac.yml..."

RELEASE_DATE=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")

cat > dist/latest-mac.yml << YMLEOF
version: ${VERSION}
files:
YMLEOF

for f in $DMG_FILES; do
  FNAME=$(basename "$f")
  FSIZE=$(stat -f%z "$f")
  FSHA512=$(shasum -a 512 "$f" | awk '{print $1}' | xxd -r -p | base64)
  cat >> dist/latest-mac.yml << YMLEOF
  - url: ${FNAME}
    sha512: ${FSHA512}
    size: ${FSIZE}
YMLEOF
done

# Use the arm64 DMG as the default path
ARM64_DMG=$(ls dist/*-${VERSION}-arm64.dmg 2>/dev/null | head -1)
if [ -n "$ARM64_DMG" ]; then
  ARM64_SHA=$(shasum -a 512 "$ARM64_DMG" | awk '{print $1}' | xxd -r -p | base64)
  cat >> dist/latest-mac.yml << YMLEOF
path: $(basename "$ARM64_DMG")
sha512: ${ARM64_SHA}
YMLEOF
fi

cat >> dist/latest-mac.yml << YMLEOF
releaseDate: '${RELEASE_DATE}'
YMLEOF

echo "Generated dist/latest-mac.yml"
cat dist/latest-mac.yml
echo ""

# Create the release
echo "Creating GitHub release $TAG..."
gh release create "$TAG" \
  --title "$TAG" \
  --generate-notes \
  $DMG_FILES dist/latest-mac.yml

echo ""
echo "Release $TAG published!"
echo "https://github.com/djnewage/cleanse/releases/tag/$TAG"
