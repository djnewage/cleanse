"""Audio processing module for censoring words using pydub."""

import os
from pydub import AudioSegment
from pydub.generators import Sine

# Padding in milliseconds to account for timestamp imprecision
PADDING_BEFORE_MS = 50
PADDING_AFTER_MS = 100

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
    else:  # mute or unknown
        return AudioSegment.silent(duration=duration_ms)


def _splice_with_crossfade(audio: AudioSegment, start_ms: int, end_ms: int, replacement: AudioSegment) -> AudioSegment:
    """Splice a replacement into audio with crossfade at boundaries."""
    before = audio[:start_ms]
    after = audio[end_ms:]

    if len(before) >= CROSSFADE_MS and len(after) >= CROSSFADE_MS:
        before_tail = before[-CROSSFADE_MS:].fade_out(CROSSFADE_MS)
        after_head = after[:CROSSFADE_MS].fade_in(CROSSFADE_MS)
        return before[:-CROSSFADE_MS] + before_tail + replacement + after_head + after[CROSSFADE_MS:]
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
) -> str:
    """
    Censor specified words in an audio file (full mix).

    Args:
        input_path: Path to the original audio file
        words: List of {"word": str, "start": float, "end": float, "censor_type": str}
        output_path: Where to save the censored audio

    Returns:
        The output file path
    """
    audio = AudioSegment.from_file(input_path)

    for w in words:
        start_ms = max(0, int(w["start"] * 1000) - PADDING_BEFORE_MS)
        end_ms = min(len(audio), int(w["end"] * 1000) + PADDING_AFTER_MS)
        if end_ms - start_ms <= 0:
            continue

        censor_type = w.get("censor_type", "mute")
        replacement = _make_replacement(audio, start_ms, end_ms, censor_type)
        audio = _splice_with_crossfade(audio, start_ms, end_ms, replacement)

    return _export(audio, output_path)


def censor_audio_vocals_only(
    vocals_path: str,
    accompaniment_path: str,
    words: list[dict],
    output_path: str,
) -> str:
    """
    Censor only the vocals track, then remix with untouched accompaniment.

    Args:
        vocals_path: Path to the isolated vocals audio
        accompaniment_path: Path to the accompaniment (instrumental) audio
        words: List of {"word": str, "start": float, "end": float, "censor_type": str}
        output_path: Where to save the final mixed output

    Returns:
        The output file path
    """
    vocals = AudioSegment.from_file(vocals_path)
    accompaniment = AudioSegment.from_file(accompaniment_path)

    for w in words:
        start_ms = max(0, int(w["start"] * 1000) - PADDING_BEFORE_MS)
        end_ms = min(len(vocals), int(w["end"] * 1000) + PADDING_AFTER_MS)
        if end_ms - start_ms <= 0:
            continue

        censor_type = w.get("censor_type", "mute")
        replacement = _make_replacement(vocals, start_ms, end_ms, censor_type)
        vocals = _splice_with_crossfade(vocals, start_ms, end_ms, replacement)

    # Mix censored vocals back with the untouched accompaniment
    mixed = accompaniment.overlay(vocals)
    return _export(mixed, output_path)
