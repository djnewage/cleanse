"""Transcription module using faster-whisper for word-level timestamps."""

import json
import os
import re
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
    _report_download_progress("downloading", 0, "Downloading audio engine...")

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
                    f"Downloading audio engine ({size_mb} MB)..."
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

    if os.environ.get("CLEANSE_DEVICE") == "cpu":
        # Diagnostic escape hatch: rule out GPU/quantization issues by forcing CPU.
        print("[Transcribe] CLEANSE_DEVICE=cpu — forcing CPU inference", file=sys.stderr)
        print(
            "[Transcribe] Loading faster-whisper 'medium' model (device=cpu, compute=int8, forced)...",
            file=sys.stderr,
        )
        _model = WhisperModel("medium", device="cpu", compute_type="int8")
        _model_turbo = turbo
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


# --- Language detection ------------------------------------------------------
#
# Whisper's in-call auto-detect looks at a single 30s window of whatever audio
# it is given. On songs with instrumental/DJ-drop intros that window contains
# no clean speech, and the detector can return junk like "km" — which then
# poisons every pass that forces the detected language. Detection therefore
# runs as an explicit step (on the vocals stem when available) with VAD,
# multiple segments, and a confidence-based fallback.

# Whisper language codes whose orthography is Latin script.
LATIN_SCRIPT_LANGS = {
    "en", "es", "fr", "de", "it", "pt", "nl", "pl", "tr", "ro", "ca", "sv",
    "da", "no", "fi", "cs", "hr", "hu", "sk", "sl", "id", "ms", "vi", "sw",
    "tl", "af",
}

_LANG_CONFIDENCE_THRESHOLD = 0.6
_LYRICS_LATIN_RATIO_THRESHOLD = 0.85


def _latin_ratio(text: str) -> float:
    """Fraction of alphabetic characters that are Latin script (incl. accented)."""
    alpha = [c for c in text if c.isalpha()]
    if not alpha:
        return 0.0
    # Basic Latin + Latin-1 Supplement + Latin Extended-A/B covers en/es/fr/...
    latin = sum(1 for c in alpha if ord(c) < 0x0250)
    return latin / len(alpha)


def choose_language(
    detected: str,
    probability: float,
    all_probs: list[tuple[str, float]] | None,
    lyrics_text: str | None = None,
) -> dict:
    """Decide the transcription language from raw detector output.

    Returns {"language", "probability", "source", "low_confidence"}.
    """
    prob_map = dict(all_probs) if all_probs else {}

    # 1. Lyrics-script prior: Latin-script lyrics make a non-Latin detection
    # implausible. Only overrides TOWARD Latin — Hangul lyrics with detected
    # "ko" pass through untouched.
    if (
        lyrics_text
        and _latin_ratio(lyrics_text) >= _LYRICS_LATIN_RATIO_THRESHOLD
        and detected not in LATIN_SCRIPT_LANGS
    ):
        latin_candidates = [
            (lang, p) for lang, p in prob_map.items() if lang in LATIN_SCRIPT_LANGS
        ]
        if latin_candidates:
            language = max(latin_candidates, key=lambda lp: lp[1])[0]
        else:
            language = "en"
        return {
            "language": language,
            "probability": prob_map.get(language, 0.0),
            "source": "lyrics_script_override",
            "low_confidence": True,
        }

    # 2. Confident detection: trust it (keeps genuine es/ko/ja/... working).
    if probability >= _LANG_CONFIDENCE_THRESHOLD:
        return {
            "language": detected,
            "probability": probability,
            "source": "detector",
            "low_confidence": False,
        }

    # 3. Low confidence: profanity matching only supports en/es, so fall back
    # to whichever of those the detector considered more likely.
    language = "es" if prob_map.get("es", 0.0) > prob_map.get("en", 0.0) else "en"
    return {
        "language": language,
        "probability": prob_map.get(language, 0.0),
        "source": "low_confidence_fallback",
        "low_confidence": True,
    }


def detect_song_language(
    file_path: str,
    turbo: bool = False,
    lyrics_text: str | None = None,
) -> dict:
    """Detect a song's language with VAD + multi-segment voting + sane fallbacks.

    Returns the same shape as choose_language().
    """
    model = get_model(turbo=turbo)
    audio = _decode_audio_ffmpeg(file_path, sampling_rate=16000)

    detected = None
    for vad in (True, False):
        try:
            detected, probability, all_probs = model.detect_language(
                audio=audio,
                vad_filter=vad,
                language_detection_segments=8,
                language_detection_threshold=0.7,
            )
            break
        except Exception as e:
            # Known case: VAD finds zero speech (instrumental) -> the library's
            # per-segment loop never runs and max({}) raises ValueError.
            print(
                f"[Language] detect_language failed (vad_filter={vad}): {e}",
                file=sys.stderr,
            )

    if detected is None:
        result = {
            "language": "en",
            "probability": 0.0,
            "source": "error_fallback",
            "low_confidence": True,
        }
        print("[Language] Detection failed entirely -> falling back to en", file=sys.stderr)
        return result

    result = choose_language(detected, probability, all_probs, lyrics_text=lyrics_text)
    top5 = sorted(all_probs, key=lambda lp: lp[1], reverse=True)[:5] if all_probs else []
    print(
        f"[Language] raw={detected} p={probability:.2f} -> chose {result['language']} "
        f"({result['source']}); top5={[(l, round(p, 3)) for l, p in top5]}",
        file=sys.stderr,
    )
    return result


def collapse_repetition_loops(
    words: list[dict],
    min_cycles: int = 4,
    min_cycle_gap: float = 0.18,
    max_density: float = 8.0,
) -> list[dict]:
    """Collapse Whisper repetition hallucinations — a short phrase repeating
    CONSECUTIVELY many times, crammed into a region with implausible density
    (near-zero word durations / overlapping timestamps), e.g. "dope shit dope shit
    dope shit…" filling an instrumental break.

    Backstop to the temperature-fallback retry: only collapses runs that are both
    long (>= ``min_cycles`` cycles of a period-1..4 phrase) AND crammed (> ``max_density``
    words/sec or cycles spaced < ``min_cycle_gap``). Legitimately-spaced repeats (real
    hooks) are left untouched.
    """
    n = len(words)
    if n < min_cycles * 2:
        return words

    def norm(i: int) -> str:
        return re.sub(r"[^\w]", "", words[i]["word"]).lower()

    keep = [True] * n
    i = 0
    while i < n:
        # Longest consecutive repeat of a period-p phrase starting at i.
        best_p, best_reps = 0, 0
        for p in range(1, 5):
            if i + 2 * p > n:
                break
            phrase = [norm(i + k) for k in range(p)]
            if "" in phrase:
                continue
            reps, j = 1, i + p
            while j + p <= n and [norm(j + k) for k in range(p)] == phrase:
                reps += 1
                j += p
            if reps >= min_cycles and reps > best_reps:
                best_p, best_reps = p, reps
        if best_p == 0:
            i += 1
            continue

        run_start, run_end = i, i + best_p * best_reps
        span = words[run_end - 1]["end"] - words[run_start]["start"]
        density = (best_p * best_reps) / max(span, 1e-6)
        crammed = span <= 0 or density > max_density or (span / best_reps) < min_cycle_gap
        if crammed:
            # Keep only cycles whose start advances >= min_cycle_gap; drop the crammed rest.
            last_kept = None
            for c in range(best_reps):
                cyc_start = words[run_start + c * best_p]["start"]
                if last_kept is None or (cyc_start - last_kept) >= min_cycle_gap:
                    last_kept = cyc_start
                else:
                    for k in range(best_p):
                        keep[run_start + c * best_p + k] = False
        i = run_end

    return [w for w, k in zip(words, keep) if k]


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
        # Temperature FALLBACK (not a fixed 0): greedy first, but when a segment
        # trips compression_ratio_threshold / log_prob_threshold — which a Whisper
        # repetition loop ("dope shit dope shit…") does, since repeated text is highly
        # compressible — retry it at a higher temperature to break the loop. A fixed
        # temperature=0 disables this retry and lets the hallucinated loop through.
        temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
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
                # Skip Whisper hallucinations (§, ♪, ♫, etc.) — keep only words
                # with letters/digits. Exception: a run of asterisks is Whisper
                # censoring profanity it heard (censored-subtitle training
                # data); keep it so the wildcard tier can flag and mute it.
                if not any(c.isalnum() for c in text) and not re.fullmatch(r"\*{3,}", text):
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

    pre_collapse = len(words)
    words = collapse_repetition_loops(words)
    if len(words) != pre_collapse:
        print(f"[Transcribe] Collapsed repetition hallucination: {pre_collapse} -> {len(words)} words", file=sys.stderr)

    print(f"[Transcribe] Transcription done in {_time.monotonic() - t2:.1f}s - {len(words)} words", file=sys.stderr)
    if progress_scale >= 100:
        _report_progress("complete", 100.0, "Transcription complete!")
    else:
        # Partial-range pass (dual-pass leg or capped single pass): the
        # endpoint still has rescan/echo/lyrics stages to run — it owns the
        # "complete" message.
        _report_progress(
            "transcribing", round(progress_offset + progress_scale, 1),
            "Transcribing audio...",
        )

    return {
        "words": words,
        "duration": round(info.duration, 3),
        "language": info.language,
    }


# --- Vocal-gap rescan: recover ad-libs the full-pass transcription missed -----

_RESCAN_FRAME_S = 0.05          # RMS envelope hop
_RESCAN_MIN_REGION_S = 0.35     # ignore shorter energy blips
_RESCAN_CLOSE_GAP_S = 0.5       # merge energy islands across quiet gaps this short
_RESCAN_PAD_S = 0.4             # context around each region
_RESCAN_MAX_REGIONS = 24        # cost cap per song
_RESCAN_MIN_CONF = 0.3          # drop low-confidence slice words (hallucination guard)
_RESCAN_MIN_CONF_PROFANE = 0.15  # profanity floor; dual-pass vocals filter precedent
_RESCAN_ENERGY_RATIO = 0.3      # region RMS vs typical active-vocal RMS
_RESCAN_MAX_REGION_S = 8.0      # cap slice length: long slices reintroduce the
                                # dominant-voice attention problem
MAX_SUNG_WORD_S = 2.0           # word timestamps occasionally blow out across
                                # audio Whisper didn't transcribe (whole rescan
                                # slices, background ad-lib sections); no sung
                                # word lasts this long


def clamp_stretched_words(
    words: list[dict], max_word_s: float = MAX_SUNG_WORD_S
) -> list[dict]:
    """Cap absurd word durations from Whisper timestamp blowout (a word's end
    stretched across audio it didn't transcribe, e.g. background ad-libs —
    measured: 'and' spanning 5.3s over a repeated ad-lib chorus). Frees the
    tail so find_unattributed_vocal_regions can see the energy under it, and
    stops the karaoke highlight stalling on one word for seconds.

    Profanity-flagged words are exempt: the mute extends to the word's end,
    and shrinking a mute is the one thing this pipeline must never do.

    Returns a new list; input dicts are not mutated.
    """
    clamped: list[dict] = []
    examples: list[str] = []
    for w in words:
        if w["end"] - w["start"] > max_word_s and not w.get("is_profanity"):
            new_w = {**w, "end": round(w["start"] + max_word_s, 3)}
            if len(examples) < 5:
                examples.append(
                    f"'{w['word']}' {w['start']:.2f}-{w['end']:.2f} -> {new_w['end']:.2f}"
                )
            clamped.append(new_w)
        else:
            clamped.append(w)
    if examples:
        n = sum(1 for a, b in zip(words, clamped) if a is not b)
        print(
            f"[Transcribe] Clamped {n} stretched word(s): {', '.join(examples)}",
            file=sys.stderr,
        )
    return clamped


def compute_vocal_rms_envelope(
    words: list[dict],
    vocals_audio: np.ndarray,
    sample_rate: int = 16000,
) -> tuple[np.ndarray, np.ndarray, float] | None:
    """Per-frame RMS envelope of the vocals stem at ``_RESCAN_FRAME_S`` hop.

    Returns ``(rms, covered, threshold)`` where ``covered`` marks frames
    inside transcribed words (±0.15s) and ``threshold`` is the
    active-vocal level (``_RESCAN_ENERGY_RATIO`` × median covered RMS), or
    None when the audio is empty or no covered frames carry energy.
    """
    n = len(vocals_audio)
    if n == 0:
        return None
    hop = max(1, int(_RESCAN_FRAME_S * sample_rate))
    n_frames = n // hop
    if n_frames == 0:
        return None
    frames = vocals_audio[: n_frames * hop].reshape(n_frames, hop)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))

    # "Active vocal" level = median RMS of frames inside transcribed words.
    covered = np.zeros(n_frames, dtype=bool)
    for w in words:
        a = int(max(w["start"] - 0.15, 0) / _RESCAN_FRAME_S)
        b = int((w["end"] + 0.15) / _RESCAN_FRAME_S) + 1
        covered[a:min(b, n_frames)] = True
    active = rms[covered & (rms > 1e-4)]
    if not len(active):
        return None
    threshold = _RESCAN_ENERGY_RATIO * float(np.median(active))
    return rms, covered, threshold


def find_unattributed_vocal_regions(
    words: list[dict],
    vocals_audio: np.ndarray,
    sample_rate: int = 16000,
) -> list[tuple[float, float]]:
    """Time regions where the vocals stem has real energy but NO transcribed
    word covers them — the acoustic signature of a missed ad-lib. Whisper
    decodes one voice stream: background shouts between (or under) main-vocal
    phrases routinely never get emitted, in either transcription pass.
    """
    envelope = compute_vocal_rms_envelope(words, vocals_audio, sample_rate)
    if envelope is None:
        return []
    rms, covered, threshold = envelope
    n_frames = len(rms)

    hot = (~covered) & (rms >= threshold)
    regions: list[tuple[float, float]] = []
    start = None
    for i, h in enumerate(hot):
        if h and start is None:
            start = i
        elif not h and start is not None:
            regions.append((start * _RESCAN_FRAME_S, i * _RESCAN_FRAME_S))
            start = None
    if start is not None:
        regions.append((start * _RESCAN_FRAME_S, n_frames * _RESCAN_FRAME_S))

    # Morphological closing: sung phrases have breaths/consonant gaps that dip
    # under the threshold for 100-400ms (measured mid-'suck my dick': frames at
    # 0.007 RMS inside an otherwise-hot phrase). Without merging across those,
    # a real ad-lib fragments into sub-minimum islands and is never rescanned.
    closed: list[tuple[float, float]] = []
    for a, b in regions:
        if closed and a - closed[-1][1] <= _RESCAN_CLOSE_GAP_S:
            closed[-1] = (closed[-1][0], b)
        else:
            closed.append((a, b))
    # Split over-long regions into equal chunks instead of truncating: a
    # missed outro can be 30s+ of continuous vocals, and dropping everything
    # past the first slice silently loses its profanity. Equal chunks keep
    # every slice under the cap (long slices reintroduce the dominant-voice
    # attention problem) without discarding the tail.
    regions = []
    for a, b in closed:
        if b - a < _RESCAN_MIN_REGION_S:
            continue
        n = max(1, int(np.ceil((b - a) / _RESCAN_MAX_REGION_S)))
        step = (b - a) / n
        regions.extend((a + i * step, a + (i + 1) * step) for i in range(n))
    if len(regions) > _RESCAN_MAX_REGIONS:
        # keep the most energetic ones, restore chronological order
        def region_energy(r):
            a, b = int(r[0] / _RESCAN_FRAME_S), int(r[1] / _RESCAN_FRAME_S)
            return float(np.sum(rms[a:b]))
        regions = sorted(sorted(regions, key=region_energy, reverse=True)[:_RESCAN_MAX_REGIONS])
    return regions


def _rescan_conf_floor(word_text: str, language: str | None = None) -> float:
    """Confidence floor for a rescan-recovered slice word.

    Profanity gets the dual-pass vocals floor (0.15, matching main.py's
    secondary-pass filter) instead of 0.3: faint background ad-libs decode at
    low confidence, the token already matched the tiered detector, and the
    slice already had unattributed vocal energy + repetition-loop collapse —
    a rare false hit mutes ~0.5s of untranscribable vocals, while a miss
    leaves profanity audible.
    """
    from profanity_detector import scan_token
    if scan_token(word_text, language) is not None:
        return _RESCAN_MIN_CONF_PROFANE
    return _RESCAN_MIN_CONF


def rescan_vocal_gaps(
    words: list[dict],
    vocals_path: str,
    language: str | None = None,
    turbo: bool = False,
) -> list[dict]:
    """Transcribe the unattributed-vocal-energy regions of the vocals stem in
    ISOLATION and return the recovered words (empty list if none).

    Isolated slices are the trick: over a whole track Whisper's attention
    locks onto the dominant voice and drops overlapping/background ad-libs
    (measured: 'suck my dick' ad-libs at conf 0.86-1.00 in a vocals-stem pass
    were still absent from the full-mix pass, and even the vocals pass loses
    them without a favorable prompt). A 1-3s slice containing only the ad-lib
    gives Whisper nothing else to attend to.

    Returned words carry detection_source='adlib_rescan' and slice-accurate
    timestamps; caller flags + merges them.
    """
    try:
        vocals_audio = _decode_audio_ffmpeg(vocals_path, sampling_rate=16000)
    except Exception as e:
        print(f"[Transcribe] Vocal-gap rescan skipped (decode failed: {e})", file=sys.stderr)
        return []

    regions = find_unattributed_vocal_regions(words, vocals_audio)
    if not regions:
        return []
    print(
        f"[Transcribe] Vocal-gap rescan: {len(regions)} unattributed vocal region(s)",
        file=sys.stderr,
    )

    from profanity_detector import scan_token

    def _covered(mid: float) -> bool:
        return any(w["start"] - 0.1 <= mid <= w["end"] + 0.1 for w in words)

    model = get_model(turbo=turbo)
    recovered: list[dict] = []
    for a, b in regions:
        s = max(a - _RESCAN_PAD_S, 0.0)
        e = min(b + _RESCAN_PAD_S, len(vocals_audio) / 16000)
        sl = vocals_audio[int(s * 16000): int(e * 16000)]
        try:
            segments, _info = model.transcribe(
                sl,
                beam_size=5,
                word_timestamps=True,
                language=language,
                condition_on_previous_text=False,
                no_speech_threshold=0.9,
            )
        except Exception as ex:
            print(f"[Transcribe] Rescan slice {s:.1f}-{e:.1f}s failed: {ex}", file=sys.stderr)
            continue
        slice_words = [
            {
                "word": w.word.strip(),
                "start": round(s + w.start, 3),
                "end": round(s + w.end, 3),
                "confidence": round(w.probability, 3),
                "detection_source": "adlib_rescan",
            }
            for seg in segments
            for w in (seg.words or [])
            if any(c.isalnum() for c in w.word)
            and (w.end - w.start) <= MAX_SUNG_WORD_S
        ]
        # Tiny slices hallucinate repetition loops readily ('-OOF' x5 in 0.6s);
        # reuse the full-pass collapse with slice-appropriate thresholds.
        slice_words = collapse_repetition_loops(slice_words, min_cycles=3)
        for w in slice_words:
            if w["confidence"] < _rescan_conf_floor(w["word"], language):
                continue
            # The pads make slices re-hear words the main pass already has
            # (the phrase edges). Keep an already-covered word only if it's a
            # new profanity — the merge/normalize layers reconcile those.
            mid = (w["start"] + w["end"]) / 2
            if _covered(mid) and scan_token(w["word"], language) is None:
                continue
            recovered.append(w)

    if recovered:
        print(
            f"[Transcribe] Vocal-gap rescan recovered {len(recovered)} word(s): "
            f"{' '.join(w['word'] for w in recovered[:20])}",
            file=sys.stderr,
        )
    return recovered
