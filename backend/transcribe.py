"""Transcription module using faster-whisper for word-level timestamps."""

import json
import subprocess
import sys
import types

import numpy as np


def _report_progress(step: str, progress: float, message: str):
    """Print a JSON progress line to stdout for the Electron main process to parse."""
    print(json.dumps({
        "type": "transcription-progress",
        "step": step,
        "progress": progress,
        "message": message,
    }))
    sys.stdout.flush()


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
MODEL_ID = "medium"


def _report_download_progress(step: str, progress: float, message: str):
    """Report model download progress via JSON stdout."""
    print(json.dumps({
        "type": "model-download-progress",
        "step": step,
        "progress": progress,
        "message": message,
    }))
    sys.stdout.flush()


def download_model_with_progress():
    """Download the Whisper model with progress reporting. No-op if already cached."""
    import huggingface_hub

    repo_id = f"Systran/faster-whisper-{MODEL_ID}"

    # Check if model is already cached
    try:
        huggingface_hub.snapshot_download(repo_id, local_files_only=True)
        _report_download_progress("complete", 100, "Model ready")
        print(f"[Transcribe] Model already cached: {repo_id}", file=sys.stderr)
        return
    except Exception:
        pass  # Not cached, need to download

    print(f"[Transcribe] Downloading model: {repo_id}", file=sys.stderr)
    _report_download_progress("downloading", 0, "Downloading AI model...")

    # Use a custom tqdm class to report progress
    from tqdm import tqdm as _tqdm

    class ProgressTqdm(_tqdm):
        def update(self, n=1):
            super().update(n)
            if self.total and self.total > 0:
                pct = min(round(self.n / self.total * 100, 1), 99)
                size_mb = round(self.total / 1024 / 1024)
                _report_download_progress(
                    "downloading", pct,
                    f"Downloading AI model ({size_mb} MB)..."
                )

    huggingface_hub.snapshot_download(repo_id, tqdm_class=ProgressTqdm)
    _report_download_progress("complete", 100, "Model downloaded")
    print(f"[Transcribe] Model downloaded: {repo_id}", file=sys.stderr)


def warmup_model():
    """Download model (if needed) and load it into memory."""
    download_model_with_progress()
    _report_download_progress("loading", 100, "Loading model into memory...")
    get_model(turbo=False)
    _report_download_progress("complete", 100, "Model ready")


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
        # Normal mode: use GPU if available for speed
        from device_info import detect_device
        device_info = detect_device()

        if device_info["device_type"] == "cuda":
            device = "cuda"
            compute_type = "int8_float16"  # Mixed precision: faster than int8, lower VRAM than float16
        else:
            device = "cpu"
            compute_type = "int8"

    # TODO: Make model size configurable via UI settings
    print(
        f"[Transcribe] Loading faster-whisper 'medium' model (device={device}, compute={compute_type}, turbo={turbo})...",
        file=sys.stderr,
    )
    _model = WhisperModel("medium", device=device, compute_type=compute_type)
    _model_turbo = turbo
    print("[Transcribe] Model loaded.", file=sys.stderr)
    return _model


def transcribe_audio(
    file_path: str,
    turbo: bool = False,
    language: str | None = None,
    initial_prompt: str | None = None,
    progress_offset: float = 0.0,
    progress_scale: float = 100.0,
    sensitive_mode: bool = False,
) -> dict:
    """
    Transcribe an audio file and return word-level timestamps.

    Args:
        file_path: Path to the audio file
        turbo: Use GPU acceleration if available
        language: Force language (None = auto-detect)
        initial_prompt: Optional text to bias the decoder vocabulary (e.g. song lyrics)
        progress_offset: Base progress value (for multi-pass scaling)
        progress_scale: Range of progress values to use

    Returns:
        {
            "words": [{"word": str, "start": float, "end": float, "confidence": float}, ...],
            "duration": float,
            "language": str
        }
    """
    import time as _time

    _report_progress("loading", round(progress_offset + progress_scale * 0.02, 1), "Loading model...")
    t0 = _time.monotonic()
    model = get_model(turbo=turbo)
    print(f"[Transcribe] Model ready in {_time.monotonic() - t0:.1f}s", file=sys.stderr)

    # Pre-decode audio via ffmpeg subprocess instead of letting faster-whisper
    # use PyAV (which crashes on macOS < 14 due to libavdevice compatibility).
    _report_progress("decoding", round(progress_offset + progress_scale * 0.05, 1), "Decoding audio...")
    print(f"[Transcribe] Decoding audio via ffmpeg: {file_path}", file=sys.stderr)
    t1 = _time.monotonic()
    audio_array = _decode_audio_ffmpeg(file_path, sampling_rate=16000)
    print(f"[Transcribe] Audio decoded in {_time.monotonic() - t1:.1f}s ({len(audio_array)/16000:.1f}s of audio)", file=sys.stderr)

    beam_size = 5
    print(f"[Transcribe] beam_size={beam_size}, turbo={turbo}", file=sys.stderr)

    _report_progress("transcribing", round(progress_offset + progress_scale * 0.10, 1), "Transcribing audio...")

    if initial_prompt:
        if len(initial_prompt) > 15000:
            initial_prompt = initial_prompt[-15000:]
            print(f"[Transcribe] Truncated initial_prompt to 15000 chars", file=sys.stderr)
        print(f"[Transcribe] Using initial_prompt ({len(initial_prompt)} chars)", file=sys.stderr)

    transcribe_kwargs = dict(
        beam_size=beam_size,
        word_timestamps=True,
        language=language,
        initial_prompt=initial_prompt,
        temperature=0,
        no_speech_threshold=0.8,
        compression_ratio_threshold=2.8,
        condition_on_previous_text=False,
    )
    if sensitive_mode:
        transcribe_kwargs["no_speech_threshold"] = 0.9
        transcribe_kwargs["condition_on_previous_text"] = False
        print("[Transcribe] Sensitive mode: no_speech_threshold=0.9, condition_on_previous_text=False", file=sys.stderr)

    t2 = _time.monotonic()
    segments, info = model.transcribe(audio_array, **transcribe_kwargs)

    words = []
    last_end = 0.0
    duration = info.duration if info.duration > 0 else 1.0

    for segment in segments:
        # Report progress based on how far through the audio we are
        seg_progress = min(segment.end / duration, 1.0)
        mapped = progress_offset + progress_scale * (0.10 + seg_progress * 0.85)
        _report_progress("transcribing", round(mapped, 1), "Transcribing audio...")

        if segment.words:
            for w in segment.words:
                text = w.word.strip()
                # Skip Whisper hallucinations (§, ♪, ♫, etc.) — keep only words with letters/digits
                if not any(c.isalnum() for c in text):
                    continue
                words.append(
                    {
                        "word": text,
                        "start": round(w.start, 3),
                        "end": round(w.end, 3),
                        "confidence": round(w.probability, 3),
                    }
                )
                last_end = max(last_end, w.end)

    print(f"[Transcribe] Transcription done in {_time.monotonic() - t2:.1f}s — {len(words)} words", file=sys.stderr)
    _report_progress("complete", round(progress_offset + progress_scale, 1), "Transcription complete!")

    return {
        "words": words,
        "duration": round(info.duration, 3),
        "language": info.language,
    }
