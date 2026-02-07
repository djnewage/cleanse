"""Transcription module using faster-whisper for word-level timestamps."""

import subprocess
import sys
import types

import numpy as np


# ---------------------------------------------------------------------------
# Stub out the 'av' (PyAV) package BEFORE faster-whisper is imported.
#
# PyAV 16.1.0 bundles libavdevice compiled for macOS 14+, which crashes on
# macOS 13 and older with:
#   Symbol not found: _AVCaptureDeviceTypeContinuityCamera
#
# faster-whisper imports av at module level (faster_whisper/audio.py line 15),
# so we must intercept before any `from faster_whisper import ...`.
#
# We decode audio via ffmpeg subprocess instead (same approach as openai/whisper).
# ---------------------------------------------------------------------------
def _install_av_stub():
    if "av" in sys.modules:
        return

    av = types.ModuleType("av")
    av.__path__ = []
    av.__package__ = "av"

    av_audio = types.ModuleType("av.audio")
    av_audio.__path__ = []
    av_audio.__package__ = "av.audio"

    av_audio_resampler = types.ModuleType("av.audio.resampler")
    av_audio_resampler.__package__ = "av.audio"
    av_audio_resampler.AudioResampler = type(
        "AudioResampler", (), {"__init__": lambda *a, **kw: None}
    )

    av_audio_fifo = types.ModuleType("av.audio.fifo")
    av_audio_fifo.__package__ = "av.audio"
    av_audio_fifo.AudioFifo = type(
        "AudioFifo", (), {"__init__": lambda *a, **kw: None}
    )

    av_error = types.ModuleType("av.error")
    av_error.__package__ = "av"
    av_error.InvalidDataError = type("InvalidDataError", (Exception,), {})

    av.audio = av_audio
    av.error = av_error
    av_audio.resampler = av_audio_resampler
    av_audio.fifo = av_audio_fifo
    av.open = lambda *a, **kw: None

    for name, mod in [
        ("av", av),
        ("av.audio", av_audio),
        ("av.audio.resampler", av_audio_resampler),
        ("av.audio.fifo", av_audio_fifo),
        ("av.error", av_error),
    ]:
        sys.modules[name] = mod

    print("[Transcribe] Installed av stub (PyAV native library bypassed)", file=sys.stderr)


_install_av_stub()


# ---------------------------------------------------------------------------
# ffmpeg subprocess audio decoder (replaces PyAV-based decode_audio)
# ---------------------------------------------------------------------------
def _decode_audio_ffmpeg(file_path: str, sampling_rate: int = 16000) -> np.ndarray:
    """Decode audio to 16kHz mono float32 numpy array using ffmpeg subprocess."""
    import imageio_ffmpeg

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe,
        "-nostdin",
        "-threads", "0",
        "-i", file_path,
        "-f", "s16le",
        "-ac", "1",
        "-acodec", "pcm_s16le",
        "-ar", str(sampling_rate),
        "-",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"ffmpeg failed to decode audio: {e.stderr.decode(errors='replace')}"
        ) from e

    audio = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    return audio


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

    # Pre-decode audio via ffmpeg subprocess instead of letting faster-whisper
    # use PyAV (which crashes on macOS < 14 due to libavdevice compatibility).
    print(f"[Transcribe] Decoding audio via ffmpeg: {file_path}", file=sys.stderr)
    audio_array = _decode_audio_ffmpeg(file_path, sampling_rate=16000)

    beam_size = 1 if turbo else 5
    print(f"[Transcribe] beam_size={beam_size}, turbo={turbo}", file=sys.stderr)

    segments, info = model.transcribe(
        audio_array,
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
