"""Audio processing module for censoring words using pydub."""

import os
import sys
from pydub import AudioSegment
from pydub.generators import Sine

# Padding in milliseconds to account for timestamp imprecision and reverb tails.
# The after-padding is larger to catch echoes/delay effects common in
# hip-hop and EDM production that extend past the word's end timestamp.
PADDING_BEFORE_MS = 200
PADDING_AFTER_MS = 250

# Crossfade duration for smooth transitions at censor boundaries
CROSSFADE_MS = 30




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
        if len(result) > duration_ms:
            result = result[:duration_ms]
        return result.fade_out(min(duration_ms, 100))
    else:  # mute or unknown
        return AudioSegment.silent(duration=duration_ms)


def _splice_with_crossfade(audio: AudioSegment, start_ms: int, end_ms: int, replacement: AudioSegment, crossfade_ms: int = CROSSFADE_MS) -> AudioSegment:
    """Splice a replacement into audio with crossfade at boundaries."""
    before = audio[:start_ms]
    after = audio[end_ms:]

    if crossfade_ms > 0 and len(before) >= crossfade_ms and len(after) >= crossfade_ms:
        before_tail = before[-crossfade_ms:].fade_out(crossfade_ms)
        after_head = after[:crossfade_ms].fade_in(crossfade_ms)
        return before[:-crossfade_ms] + before_tail + replacement + after_head + after[crossfade_ms:]
    return before + replacement + after


def _export(audio: AudioSegment, output_path: str) -> str:
    """Export audio to the given path, inferring format from extension."""
    ext = os.path.splitext(output_path)[1].lower().lstrip(".")
    format_map = {"mp3": "mp3", "wav": "wav", "ogg": "ogg", "m4a": "mp4", "flac": "flac"}
    out_format = format_map.get(ext, "mp3")
    audio.export(output_path, format=out_format)
    return output_path


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

    # Sort by timestamp for deterministic processing order
    words = sorted(words, key=lambda w: w["start"])

    for w in words:
        # Use wider padding for words with estimated timestamps (lyrics-sourced)
        source = w.get("detection_source", "")
        if source in ("lyrics", "lyrics_gap"):
            actual_before = padding_before_ms * 3
            actual_after = padding_after_ms * 2
        else:
            actual_before = padding_before_ms
            actual_after = padding_after_ms

        start_ms = max(0, int(w["start"] * 1000) - actual_before)
        end_ms = min(len(audio), int(w["end"] * 1000) + actual_after)
        if end_ms - start_ms <= 0:
            continue

        censor_type = w.get("censor_type", "mute")
        replacement = _make_replacement(audio, start_ms, end_ms, censor_type)
        audio = _splice_with_crossfade(audio, start_ms, end_ms, replacement, crossfade_ms)

    return _export(audio, output_path)


def censor_audio_vocals_only(
    vocals_path: str,
    accompaniment_path: str,
    words: list[dict],
    output_path: str,
    crossfade_ms: int = CROSSFADE_MS,
    padding_before_ms: int = PADDING_BEFORE_MS,
    padding_after_ms: int = PADDING_AFTER_MS,
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

    Returns:
        The output file path
    """
    vocals = AudioSegment.from_file(vocals_path)
    accompaniment = AudioSegment.from_file(accompaniment_path)

    # Sort by timestamp for deterministic processing order
    words = sorted(words, key=lambda w: w["start"])

    for w in words:
        # Use wider padding for words with estimated timestamps (lyrics-sourced)
        source = w.get("detection_source", "")
        if source in ("lyrics", "lyrics_gap"):
            actual_before = padding_before_ms * 3
            actual_after = padding_after_ms * 2
        else:
            actual_before = padding_before_ms
            actual_after = padding_after_ms

        start_ms = max(0, int(w["start"] * 1000) - actual_before)
        end_ms = min(len(vocals), int(w["end"] * 1000) + actual_after)
        if end_ms - start_ms <= 0:
            continue

        censor_type = w.get("censor_type", "mute")

        print(
            f"[AudioProcessor] Word '{w.get('word', '?')}' "
            f"time={w.get('start', 0):.2f}-{w.get('end', 0):.2f}s "
            f"padded={start_ms}-{end_ms}ms "
            f"censor={censor_type} "
            f"source={w.get('detection_source', 'unknown')}",
            file=sys.stderr,
        )

        # Censor vocals
        replacement = _make_replacement(vocals, start_ms, end_ms, censor_type)
        vocals = _splice_with_crossfade(vocals, start_ms, end_ms, replacement, crossfade_ms)

    # Mix censored vocals back with accompaniment
    mixed = accompaniment.overlay(vocals)
    return _export(mixed, output_path)
