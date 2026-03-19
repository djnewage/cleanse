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

# Find built artifacts
DMG_FILES=$(ls dist/*.dmg 2>/dev/null || true)
if [ -z "$DMG_FILES" ]; then
  echo "Error: No .dmg files found in dist/"
  echo "Run 'npm run build:mac' first."
  exit 1
fi

echo "Artifacts to upload:"
for f in $DMG_FILES; do
  echo "  $f ($(du -h "$f" | cut -f1))"
done
echo ""

# Create the release
echo "Creating GitHub release $TAG..."
gh release create "$TAG" \
  --title "$TAG" \
  --generate-notes \
  $DMG_FILES

echo ""
echo "Release $TAG published!"
echo "https://github.com/djnewage/cleanse/releases/tag/$TAG"
