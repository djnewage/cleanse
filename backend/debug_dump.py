"""Structured intermediate-state dumps for debugging the audio pipeline.

Gated by CLEANSE_DEBUG=1. When unset (the normal case for end users), all
calls are no-ops with effectively zero overhead. When set, each call writes
one JSON file to ~/Library/Logs/cleanse/debug/ named for the song + stage.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

_DEBUG_DIR = Path.home() / "Library" / "Logs" / "cleanse" / "debug"


def is_enabled() -> bool:
    return os.environ.get("CLEANSE_DEBUG") == "1"


def dump(stage: str, song_path: str, data) -> None:
    if not is_enabled():
        return
    try:
        _DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        song = re.sub(r"[^A-Za-z0-9_-]", "_", Path(song_path).stem)[:60]
        path = _DEBUG_DIR / f"{ts}-{song}-{stage}.json"
        path.write_text(json.dumps(data, indent=2, default=str))
    except Exception:
        pass
