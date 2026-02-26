"""Shared test configuration — stubs for heavy ML/web dependencies.

All test files run in the same pytest process. Modules stubbed here via
sys.modules are shared across every test file. Only stub modules that are
genuinely unavailable in the test environment (torch, demucs, faster_whisper,
fastapi, etc.). Do NOT stub lightweight/installed packages (pydub, certifi,
better_profanity, requests, tinytag, imageio_ffmpeg, numpy).
"""

import sys
from unittest.mock import MagicMock

# --- ML / GPU libraries (not installed in lightweight test env) ---
for mod in [
    "torch", "torchaudio", "torchaudio.transforms",
    "demucs", "demucs.pretrained", "demucs.apply",
    "tqdm",
    "faster_whisper",
    # Web framework
    "fastapi", "fastapi.middleware", "fastapi.middleware.cors",
    "fastapi.responses",
    "pydantic",
    "uvicorn",
]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()
