"""Audio processing module for censoring words using pydub."""

import os
import sys
import subprocess
import numpy as np
from scipy.signal import butter, sosfilt
from pydub import AudioSegment
from pydub.generators import Sine
from pydub.utils import mediainfo_json

# Padding in milliseconds to account for timestamp imprecision and reverb tails.
# The after-padding is larger to catch echoes/delay effects common in
# hip-hop and EDM production that extend past the word's end timestamp.
PADDING_BEFORE_MS = 200
PADDING_AFTER_MS = 250

# Extra padding for words with estimated (lyrics-derived) timestamps. Additive,
# NOT multiplicative: the old 3x/2x multiplier made injected words within one
# lyric line chain into contiguous blanket mutes over whole sections.
ESTIMATED_PAD_EXTRA_MS = 100

# Crossfade duration for smooth transitions at censor boundaries
CROSSFADE_MS = 30

# dBFS threshold below which vocals are considered "missing" at a position,
# indicating demucs likely placed the vocal in the accompaniment track
VOCAL_SILENCE_THRESHOLD = -40

# Band-reject filter bounds for suppressing leaked vocals in accompaniment.
# Preserves sub-bass/kick (below 250Hz) and hi-hats/cymbals (above 4kHz).
BANDREJECT_LOW = 250
BANDREJECT_HIGH = 4000

# Output extensions whose pydub format accepts a `bitrate` kwarg (lossy codecs).
# WAV/FLAC are lossless and pydub ignores/rejects bitrate for them.
_LOSSY_FORMATS = {"mp3", "mp4", "ogg"}

# Fallback bitrate when source detection fails. 320k is the max for MP3 and
# perceptually transparent for stereo music.
_DEFAULT_LOSSY_BITRATE_KBPS = 320

# Minimum bitrate to accept from source probing. Below this, the source is
# likely speech-only or corrupted metadata — fall back to the default.
_MIN_SOURCE_BITRATE_KBPS = 96

# Output formats whose containers reliably carry tags + embedded cover art via an
# ffmpeg stream-copy remux. WAV/AIFF have no standard cover-art container and OGG
# cover embedding is unreliable via stream copy, so they are intentionally skipped.
_SUPPORTED_META_FORMATS = {"mp3", "flac", "m4a", "mp4"}




def _apply_bandreject(segment: AudioSegment, low: int = BANDREJECT_LOW, high: int = BANDREJECT_HIGH) -> AudioSegment:
    """Apply band-reject filter to suppress vocal frequencies while preserving bass and highs."""
    samples = np.array(segment.get_array_of_samples(), dtype=np.float64)
    sample_rate = segment.frame_rate
    channels = segment.channels

    sos = butter(N=6, Wn=[low, high], btype='bandstop', fs=sample_rate, output='sos')

    if channels > 1:
        samples = samples.reshape(-1, channels)
        for ch in range(channels):
            samples[:, ch] = sosfilt(sos, samples[:, ch])
        filtered = samples.flatten()
    else:
        filtered = sosfilt(sos, samples)

    return segment._spawn(np.int16(np.clip(filtered, -32768, 32767)).tobytes())


def _make_replacement(audio: AudioSegment, start_ms: int, end_ms: int, censor_type: str) -> AudioSegment:
    """Build the replacement segment for a censored word."""
    duration_ms = end_ms - start_ms
    if censor_type == "beep":
        beep = Sine(1000).to_audio_segment(duration=duration_ms)
        original_segment = audio[start_ms:end_ms]
        if original_segment.dBFS > -float("inf"):
            beep = beep.apply_gain(original_segment.dBFS - beep.dBFS)
        return beep
    elif censor_type == "reverse":
        return audio[start_ms:end_ms].reverse()
    elif censor_type == "tape_stop":
        segment = audio[start_ms:end_ms]
        n_chunks = 20
        chunk_len = len(segment) // n_chunks
        if chunk_len < 10:
            return AudioSegment.silent(duration=duration_ms)
        result = AudioSegment.empty()
        for i in range(n_chunks):
            s = i * chunk_len
            e = s + chunk_len if i < n_chunks - 1 else len(segment)
            chunk = segment[s:e]
            speed = max(0.15, 1.0 - (i / n_chunks) * 0.85)
            new_rate = int(chunk.frame_rate * speed)
            slowed = chunk._spawn(chunk.raw_data, overrides={"frame_rate": max(new_rate, 1000)})
            slowed = slowed.set_frame_rate(segment.frame_rate)
            result += slowed
        result = _fit_exact(result, duration_ms)
        return result.fade_out(min(duration_ms, 100))
    else:  # mute or unknown
        return AudioSegment.silent(duration=duration_ms, frame_rate=audio.frame_rate)


def _fit_exact(segment: AudioSegment, duration_ms: int) -> AudioSegment:
    """Force a segment to exactly duration_ms, padding with matching silence.

    Demucs stems can run a few ms shorter than the source, so a region near the
    end of the track may slice short. Splicing a short replacement would shrink
    the output and invalidate every cue point after it, so pad rather than trim.
    """
    deficit = duration_ms - len(segment)
    if deficit == 0:
        return segment
    if deficit < 0:
        return segment[:duration_ms]
    pad = AudioSegment.silent(duration=deficit, frame_rate=segment.frame_rate)
    pad = pad.set_channels(segment.channels).set_sample_width(segment.sample_width)
    return segment + pad


def _splice_with_crossfade(audio: AudioSegment, start_ms: int, end_ms: int, replacement: AudioSegment, crossfade_ms: int = CROSSFADE_MS) -> AudioSegment:
    """Splice a replacement into audio with crossfade at boundaries."""
    before = audio[:start_ms]
    after = audio[end_ms:]

    if crossfade_ms > 0 and len(before) >= crossfade_ms and len(after) >= crossfade_ms:
        before_tail = before[-crossfade_ms:].fade_out(crossfade_ms)
        after_head = after[:crossfade_ms].fade_in(crossfade_ms)
        return before[:-crossfade_ms] + before_tail + replacement + after_head + after[crossfade_ms:]
    return before + replacement + after


def _detect_source_bitrate_kbps(source_path: str | None) -> int | None:
    """Probe a source file's audio bitrate in kbps. Returns None on failure.

    Uses mediainfo_json (not mediainfo) because main.py monkey-patches the
    JSON variant with an ffmpeg-based fallback when ffprobe is not on PATH.
    """
    if not source_path or not os.path.isfile(source_path):
        return None
    try:
        info = mediainfo_json(source_path)
    except Exception:
        return None
    # Prefer the audio stream's bit_rate; fall back to container/format bit_rate.
    candidates = []
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "audio" and stream.get("bit_rate"):
            candidates.append(stream["bit_rate"])
    fmt_br = info.get("format", {}).get("bit_rate")
    if fmt_br:
        candidates.append(fmt_br)
    for raw in candidates:
        if raw and str(raw).isdigit():
            kbps = int(raw) // 1000
            if kbps >= _MIN_SOURCE_BITRATE_KBPS:
                return kbps
    return None


def _ffmpeg_exe() -> str:
    """Resolve the ffmpeg binary, preferring pydub's configured converter."""
    converter = getattr(AudioSegment, "converter", None)
    if converter:
        return converter
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _copy_metadata(source_path: str | None, output_path: str, out_format: str) -> None:
    """Copy tags + embedded cover art from source into the exported file.

    Best-effort: pydub's export writes raw audio with no tags or artwork, so we
    remux via ffmpeg (stream copy — no re-encode) to carry the source's metadata
    and cover image onto the cleaned output. Any failure is swallowed so the core
    censoring output is never lost; the pydub-exported file is simply left as-is.
    """
    if not source_path or not os.path.isfile(source_path):
        return
    if out_format not in _SUPPORTED_META_FORMATS:
        return

    base, ext = os.path.splitext(output_path)
    temp_path = f"{base}.meta{ext}"
    cmd = [
        _ffmpeg_exe(), "-y",
        "-i", output_path,    # input 0: the cleaned audio we just wrote
        "-i", source_path,    # input 1: original, for metadata + cover art
        "-map", "0:a",        # keep the cleaned audio
        "-map", "1:v:0?",     # optional cover-art stream from the source
        "-c", "copy",         # no re-encode
        "-map_metadata", "1", # copy all container tags from the source
        "-disposition:v:0", "attached_pic",
    ]
    if out_format == "mp3":
        cmd += ["-id3v2_version", "3"]
    cmd.append(temp_path)

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode == 0 and os.path.isfile(temp_path) and os.path.getsize(temp_path) > 0:
            os.replace(temp_path, output_path)
        else:
            stderr = result.stderr.decode("utf-8", "replace")[-500:]
            print(f"[Metadata] ffmpeg remux failed (rc={result.returncode}): {stderr}", file=sys.stderr)
            if os.path.isfile(temp_path):
                os.remove(temp_path)
    except Exception as e:
        print(f"[Metadata] Failed to copy metadata to {output_path}: {e}", file=sys.stderr)
        if os.path.isfile(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _export(audio: AudioSegment, output_path: str, source_path: str | None = None) -> str:
    """Export audio, preserving source bitrate for lossy formats.

    Args:
        audio: The processed AudioSegment to write.
        output_path: Destination path; format is inferred from extension.
        source_path: Optional original input path used to probe a target
            bitrate. Falls back to a high-quality default if unavailable.
    """
    ext = os.path.splitext(output_path)[1].lower().lstrip(".")
    format_map = {"mp3": "mp3", "wav": "wav", "ogg": "ogg", "m4a": "mp4", "flac": "flac", "aiff": "aiff", "aif": "aiff"}
    out_format = format_map.get(ext, "mp3")

    kwargs: dict = {"format": out_format}
    if out_format in _LOSSY_FORMATS:
        src_kbps = _detect_source_bitrate_kbps(source_path)
        # Cap at 320k: that's MP3's ceiling and audibly transparent for AAC/Opus.
        target_kbps = min(src_kbps or _DEFAULT_LOSSY_BITRATE_KBPS, 320)
        kwargs["bitrate"] = f"{target_kbps}k"

    audio.export(output_path, **kwargs)
    _copy_metadata(source_path, output_path, out_format)
    return output_path


def _build_censor_regions(
    words: list[dict],
    audio_len_ms: int,
    padding_before_ms: int,
    padding_after_ms: int,
) -> list[dict]:
    """Compute padded censor intervals per word and merge overlapping/touching
    regions of the same censor_type. Returns regions sorted by start:
    [{"start_ms", "end_ms", "censor_type", "words": [str, ...]}].

    Merging keeps crossfaded splices from stacking on the same samples, and
    the coverage log makes over-muting regressions visible.
    """
    intervals = []
    for w in sorted(words, key=lambda x: x["start"]):
        extra = ESTIMATED_PAD_EXTRA_MS if w.get("detection_source", "") in ("lyrics", "lyrics_gap", "hook_echo", "acoustic_echo") else 0
        start_ms = max(0, int(w["start"] * 1000) - padding_before_ms - extra)
        end_ms = min(audio_len_ms, int(w["end"] * 1000) + padding_after_ms + extra)
        if end_ms - start_ms <= 0:
            continue
        intervals.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "censor_type": w.get("censor_type", "mute"),
            "words": [w.get("word", "?")],
        })

    regions: list[dict] = []
    for iv in intervals:
        prev = regions[-1] if regions else None
        if prev and iv["start_ms"] <= prev["end_ms"] and iv["censor_type"] == prev["censor_type"]:
            prev["end_ms"] = max(prev["end_ms"], iv["end_ms"])
            prev["words"].extend(iv["words"])
        elif prev and iv["start_ms"] < prev["end_ms"]:
            # Different censor_type overlapping: trim the later region's start.
            iv["start_ms"] = prev["end_ms"]
            if iv["end_ms"] - iv["start_ms"] > 0:
                regions.append(iv)
        else:
            regions.append(iv)

    total_ms = sum(r["end_ms"] - r["start_ms"] for r in regions)
    if regions and audio_len_ms > 0:
        pct = 100.0 * total_ms / audio_len_ms
        print(
            f"[AudioProcessor] {len(regions)} censor regions covering "
            f"{total_ms / 1000:.1f}s ({pct:.1f}% of track)",
            file=sys.stderr,
        )
        if pct > 20.0:
            print(
                f"[AudioProcessor] WARNING: censoring {pct:.1f}% of the track — "
                f"likely mispositioned lyrics-derived detections",
                file=sys.stderr,
            )
    return regions


def censor_audio(
    input_path: str,
    words: list[dict],
    output_path: str,
    crossfade_ms: int = CROSSFADE_MS,
    padding_before_ms: int = PADDING_BEFORE_MS,
    padding_after_ms: int = PADDING_AFTER_MS,
) -> str:
    """
    Censor specified words in an audio file (full mix).

    Args:
        input_path: Path to the original audio file
        words: List of {"word": str, "start": float, "end": float, "censor_type": str}
        output_path: Where to save the censored audio
        crossfade_ms: Duration of crossfade at edit boundaries
        padding_before_ms: Extra ms before each word to censor
        padding_after_ms: Extra ms after each word to censor

    Returns:
        The output file path
    """
    audio = AudioSegment.from_file(input_path)

    regions = _build_censor_regions(words, len(audio), padding_before_ms, padding_after_ms)
    for r in regions:
        replacement = _make_replacement(audio, r["start_ms"], r["end_ms"], r["censor_type"])
        audio = _splice_with_crossfade(audio, r["start_ms"], r["end_ms"], replacement, crossfade_ms)

    return _export(audio, output_path, source_path=input_path)


def censor_audio_vocals_only(
    vocals_path: str,
    accompaniment_path: str,
    words: list[dict],
    output_path: str,
    crossfade_ms: int = CROSSFADE_MS,
    padding_before_ms: int = PADDING_BEFORE_MS,
    padding_after_ms: int = PADDING_AFTER_MS,
    source_path: str | None = None,
) -> str:
    """
    Censor only the vocals track, then remix with untouched accompaniment.

    Args:
        vocals_path: Path to the isolated vocals audio
        accompaniment_path: Path to the accompaniment (instrumental) audio
        words: List of {"word": str, "start": float, "end": float, "censor_type": str}
        output_path: Where to save the final mixed output
        crossfade_ms: Duration of crossfade at edit boundaries
        padding_before_ms: Extra ms before each word to censor
        padding_after_ms: Extra ms after each word to censor
        source_path: Original full-mix input path; used to detect target export
            bitrate. Demucs stems are typically WAV, so probing them would
            yield no useful bitrate hint.

    Returns:
        The output file path
    """
    vocals = AudioSegment.from_file(vocals_path)
    accompaniment = AudioSegment.from_file(accompaniment_path)

    # Base the output on the ORIGINAL audio, not on a full-track stem remix.
    # Demucs stems are a lossy reconstruction at the model's own sample rate and
    # bit depth, so returning accompaniment.overlay(vocals) degraded 100% of the
    # track in order to fix ~0.5s per censored word. Splicing stem-derived audio
    # only into the censored regions leaves everything else identical to the
    # source, and makes the output exactly the source's length -- which is what
    # cue points in DJ software depend on.
    base = None
    if source_path and os.path.isfile(source_path):
        try:
            base = AudioSegment.from_file(source_path)
        except Exception as e:
            print(
                f"[AudioProcessor] Could not decode source for splice base ({e}); "
                f"falling back to full stem remix",
                file=sys.stderr,
            )
    if base is None:
        base = accompaniment.overlay(vocals)

    original_len_ms = len(base)
    regions = _build_censor_regions(words, original_len_ms, padding_before_ms, padding_after_ms)
    for r in regions:
        start_ms, end_ms = r["start_ms"], r["end_ms"]
        region_len = end_ms - start_ms

        # Stems can run slightly short of the source; pin both slices to the
        # region length so the splice cannot change the track's duration.
        vocal_slice = _fit_exact(vocals[start_ms:end_ms], region_len)
        accomp_slice = _fit_exact(accompaniment[start_ms:end_ms], region_len)

        # Check vocal level to detect demucs leakage
        vocal_level = vocal_slice.dBFS
        is_leaked = vocal_level < VOCAL_SILENCE_THRESHOLD

        print(
            f"[AudioProcessor] Region {start_ms}-{end_ms}ms "
            f"words={' '.join(r['words'])} "
            f"censor={r['censor_type']} "
            f"vocal_dBFS={vocal_level:.1f}"
            f"{'  -> BANDREJECT' if is_leaked else ''}",
            file=sys.stderr,
        )

        # Censor the vocal for this region only.
        censored_vocal = _make_replacement(vocal_slice, 0, region_len, r["censor_type"])

        # If vocals are silent, the word leaked into the accompaniment.
        # Apply band-reject filter to suppress vocal frequencies (250-4000Hz)
        # while preserving kick/bass/hi-hats.
        if is_leaked:
            accomp_slice = _apply_bandreject(accomp_slice)

        # Rebuild just this region from the stems, then splice it into the
        # original. Demucs artifacts stay confined to the censored words.
        replacement = _fit_exact(accomp_slice.overlay(censored_vocal), region_len)
        base = _splice_with_crossfade(base, start_ms, end_ms, replacement, crossfade_ms)

    if len(base) != original_len_ms:
        # Every cue point after a length change would land in the wrong place.
        print(
            f"[AudioProcessor] WARNING: output length {len(base)}ms != "
            f"source length {original_len_ms}ms",
            file=sys.stderr,
        )

    return _export(base, output_path, source_path=source_path)
