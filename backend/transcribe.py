"""Transcription module using faster-whisper for word-level timestamps."""

import sys

# Global model instance - loaded once at first use
_model = None
_model_turbo: bool = False


def get_model(turbo: bool = False):
    """Load the Whisper model (cached after first call). Reloads if turbo mode changes."""
    from faster_whisper import WhisperModel
    global _model, _model_turbo
    if _model is not None and _model_turbo == turbo:
        return _model

    if turbo:
        from device_info import get_device_string

        device_type = get_device_string()
        # CTranslate2 (used by faster-whisper) does NOT support MPS
        if device_type == "cuda":
            device = "cuda"
            compute_type = "float16"
        else:
            device = "cpu"
            compute_type = "int8"
    else:
        device = "cpu"
        compute_type = "int8"

    print(
        f"[Transcribe] Loading faster-whisper 'medium' model (device={device}, compute={compute_type}, turbo={turbo})...",
        file=sys.stderr,
    )
    _model = WhisperModel("medium", device=device, compute_type=compute_type)
    _model_turbo = turbo
    print("[Transcribe] Model loaded.", file=sys.stderr)
    return _model


def transcribe_audio(file_path: str, turbo: bool = False) -> dict:
    """
    Transcribe an audio file and return word-level timestamps.

    Returns:
        {
            "words": [{"word": str, "start": float, "end": float, "confidence": float}, ...],
            "duration": float,
            "language": str
        }
    """
    model = get_model(turbo=turbo)

    beam_size = 1 if turbo else 5
    print(f"[Transcribe] beam_size={beam_size}, turbo={turbo}", file=sys.stderr)

    segments, info = model.transcribe(
        file_path,
        beam_size=beam_size,
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
