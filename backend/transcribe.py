"""Transcription module using faster-whisper for word-level timestamps."""

import sys
from faster_whisper import WhisperModel

# Global model instance - loaded once at import time
_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    """Load the Whisper model (cached after first call)."""
    global _model
    if _model is None:
        print("[Transcribe] Loading faster-whisper 'base' model...", file=sys.stderr)
        _model = WhisperModel("base", device="cpu", compute_type="int8")
        print("[Transcribe] Model loaded.", file=sys.stderr)
    return _model


def transcribe_audio(file_path: str) -> dict:
    """
    Transcribe an audio file and return word-level timestamps.

    Returns:
        {
            "words": [{"word": str, "start": float, "end": float, "confidence": float}, ...],
            "duration": float,
            "language": str
        }
    """
    model = get_model()

    segments, info = model.transcribe(
        file_path,
        beam_size=5,
        word_timestamps=True,
        language=None,  # auto-detect
    )

    words = []
    last_end = 0.0

    for segment in segments:
        if segment.words:
            for w in segment.words:
                words.append(
                    {
                        "word": w.word.strip(),
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "confidence": round(w.probability, 3),
                    }
                )
                last_end = max(last_end, w.end)

    return {
        "words": words,
        "duration": round(info.duration, 3),
        "language": info.language,
    }
