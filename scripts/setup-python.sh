#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"

echo "=== Cleanse - Python Backend Setup ==="

# Check for Python 3.10+
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found. Please install Python 3.10 or later."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Found Python $PYTHON_VERSION"

# Check for ffmpeg
if ! command -v ffmpeg &> /dev/null; then
    echo "WARNING: ffmpeg not found. Audio processing requires ffmpeg."
    echo "  Install with: brew install ffmpeg (macOS) or apt install ffmpeg (Linux)"
fi

# Create virtual environment
VENV_DIR="$BACKEND_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists."
fi

# Activate and install dependencies
echo "Installing Python dependencies..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip -q
pip install -r "$BACKEND_DIR/requirements.txt"

echo ""
echo "=== Setup complete! ==="
echo "To start the backend manually:"
echo "  source $VENV_DIR/bin/activate"
echo "  python $BACKEND_DIR/main.py --port 8765"
