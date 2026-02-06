#!/usr/bin/env bash
set -euo pipefail

# Build the Python backend into a standalone executable using PyInstaller.
# Output: backend/dist/cleanse-backend/  (one-dir bundle)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"

echo "==> Building Python backend with PyInstaller..."

cd "$BACKEND_DIR"

# Use venv binaries directly (more reliable than `source activate` in scripts)
VENV_DIR="$BACKEND_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
  echo "ERROR: backend/venv not found. Run scripts/setup-python.sh first."
  exit 1
fi

PIP="$VENV_DIR/bin/pip"
PYTHON="$VENV_DIR/bin/python3"

# Ensure pyinstaller is installed
"$PIP" install pyinstaller --quiet

# Clean previous build artifacts
rm -rf dist/cleanse-backend build/cleanse-backend

# Run PyInstaller via the venv python
"$PYTHON" -m PyInstaller cleanse-backend.spec --noconfirm

echo "==> Backend built successfully: backend/dist/cleanse-backend/"
echo "==> Test with: ./backend/dist/cleanse-backend/cleanse-backend --port 8765"
