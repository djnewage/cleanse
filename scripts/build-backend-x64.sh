#!/usr/bin/env bash
set -euo pipefail

# Build the Python backend for Intel Mac (x64) using PyInstaller.
# On Apple Silicon: uses Rosetta 2 (arch -x86_64) to create an x64 build.
# On Intel Mac: builds natively.
# Output: backend/dist/cleanse-backend/  (one-dir bundle)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"

echo "==> Building Python backend for x64 (Intel Mac)..."

cd "$BACKEND_DIR"

# Detect if we're on ARM64 and need to use Rosetta
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
  echo "==> Running on Apple Silicon, using arch -x86_64 for x64 build..."
  ARCH_PREFIX="arch -x86_64"
else
  echo "==> Running on Intel Mac, building natively..."
  ARCH_PREFIX=""
fi

# Use a separate x64 venv to isolate x64 dependencies
VENV_DIR="$BACKEND_DIR/venv-x64"
if [ ! -d "$VENV_DIR" ]; then
  echo "==> Creating x64 virtual environment..."
  $ARCH_PREFIX python3 -m venv "$VENV_DIR"
  echo "==> Installing dependencies for x64..."
  $ARCH_PREFIX "$VENV_DIR/bin/pip" install --upgrade pip --quiet
  $ARCH_PREFIX "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt"
fi

PIP="$VENV_DIR/bin/pip"
PYTHON="$VENV_DIR/bin/python3"

# Ensure pyinstaller is installed
$ARCH_PREFIX "$PIP" install pyinstaller --quiet

# Clean previous build artifacts
rm -rf dist/cleanse-backend build/cleanse-backend

# Run PyInstaller under Rosetta so it produces an x86_64 binary
$ARCH_PREFIX "$PYTHON" -m PyInstaller cleanse-backend.spec --noconfirm

echo "==> x64 backend built successfully: backend/dist/cleanse-backend/"
echo "==> Verify with: file backend/dist/cleanse-backend/cleanse-backend"
