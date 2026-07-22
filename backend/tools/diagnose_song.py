"""Diagnose Cleanse's detection/muting on a single song, headless.

Runs the exact pipeline the app runs (metadata -> lyrics fetch -> transcribe ->
flag -> lyrics pipeline), then reports every planned mute region attributed to
the detector that produced it, plus the karaoke timing invariants.

Use this whenever a processed song "sounds wrong" — it turns the complaint
into a per-mute attribution you can reason about.

Usage:
    venv/bin/python tools/diagnose_song.py "/path/to/song.mp3"
    venv/bin/python tools/diagnose_song.py song.mp3 --no-turbo --json out.json

Notes:
  * Single-pass only (no demucs vocal separation) — dual-pass in the app can
    add vocals-sourced detections this report won't show. Pass --vocals with
    an existing demucs stem to also run the app's ad-lib vocal-gap rescan.
  * Mute regions use the app's default padding (150ms before / 100ms after).
"""

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# App defaults sent by the renderer (App.tsx)
DEFAULT_PAD_BEFORE_MS = 150
DEFAULT_PAD_AFTER_MS = 100


def check_karaoke_invariants(words: list[dict]) -> list[str]:
    """Return violations of the invariants the karaoke renderer relies on."""
    violations = []
    for i, w in enumerate(words):
        if w["start"] > w["end"]:
            violations.append(f"start>end: [{i}] {w['word']!r} {w['start']}-{w['end']}")
        if w["start"] < 0:
            violations.append(f"negative start: [{i}] {w['word']!r}")
    for i in range(len(words) - 1):
        if words[i]["start"] > words[i + 1]["start"]:
            violations.append(
                f"unsorted at {i}: {words[i]['word']!r}@{words[i]['start']} "
                f"> {words[i + 1]['word']!r}@{words[i + 1]['start']}"
            )
        if words[i]["end"] > words[i + 1]["start"] + 1e-6:
            violations.append(
                f"overlap at {i}: {words[i]['word']!r} ends {words[i]['end']} "
                f"after {words[i + 1]['word']!r} starts {words[i + 1]['start']}"
            )
    return violations


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("audio_file", help="Path to the audio file")
    parser.add_argument("--no-turbo", action="store_true", help="Full beam search (slower)")
    parser.add_argument("--no-lyrics", action="store_true", help="Skip lyrics fetching")
    parser.add_argument(
        "--vocals", metavar="PATH",
        help="Vocals stem WAV (demucs output); enables the ad-lib vocal-gap rescan",
    )
    parser.add_argument("--json", metavar="PATH", help="Also dump the final words JSON here")
    parser.add_argument("--pad-before", type=int, default=DEFAULT_PAD_BEFORE_MS)
    parser.add_argument("--pad-after", type=int, default=DEFAULT_PAD_AFTER_MS)
    args = parser.parse_args()

    if not os.path.isfile(args.audio_file):
        sys.exit(f"File not found: {args.audio_file}")
    if args.vocals and not os.path.isfile(args.vocals):
        sys.exit(f"Vocals stem not found: {args.vocals}")

    from lyrics_fetcher import extract_metadata, fetch_lyrics
    from profanity_detector import flag_profanity
    from transcribe import clamp_stretched_words, rescan_vocal_gaps, transcribe_audio
    from audio_processor import _build_censor_regions
    from main import apply_lyrics_pipeline

    meta = extract_metadata(args.audio_file)
    print(f"metadata: {meta}")

    synced = plain = None
    from_tags = True
    if not args.no_lyrics:
        lyr = fetch_lyrics(
            meta.get("artist"), meta.get("title"), meta.get("duration"),
            filename=os.path.basename(args.audio_file),
        ) or {}
        synced = lyr.get("synced_lyrics")
        plain = lyr.get("plain_lyrics")
        from_tags = lyr.get("from_tag_metadata", True)
        print(
            f"lyrics: source={lyr.get('lyrics_source')} "
            f"synced={'yes' if synced else 'no'} plain={'yes' if plain else 'no'} "
            f"duration_mismatch={lyr.get('duration_mismatch', False)} "
            f"from_tag_metadata={from_tags}"
        )

    # Mirrors the app: guessed-metadata lyrics never bias the transcription.
    result = transcribe_audio(
        args.audio_file, turbo=not args.no_turbo,
        initial_prompt=plain if from_tags else None,
    )
    duration, lang = result["duration"], result["language"]
    print(f"transcribed: {len(result['words'])} words, duration={duration:.1f}s, lang={lang}")

    words = flag_profanity(result["words"], language=lang)

    # Mirrors the app (main.py /transcribe): clamp timestamp blowouts, then
    # rescan unattributed vocal energy when a stem is available.
    words = clamp_stretched_words(words)
    if args.vocals:
        recovered = rescan_vocal_gaps(
            words, args.vocals, language=lang, turbo=not args.no_turbo
        )
        if recovered:
            recovered = flag_profanity(recovered, language=lang)
            words = sorted(words + recovered, key=lambda w: w["start"])
        print(f"rescan: {len(recovered)} recovered word(s)")

    final = apply_lyrics_pipeline(words, duration, lang, plain, synced)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(final, f, indent=1)
        print(f"words dumped to {args.json}")

    profane = [w for w in final if w.get("is_profanity")]
    by_source = Counter(w.get("detection_source", "whisper") for w in profane)
    print(f"\nwords={len(final)} flagged={len(profane)} by_source={dict(by_source)}")

    violations = check_karaoke_invariants(final)
    print(f"karaoke invariant violations: {len(violations)}")
    for v in violations[:20]:
        print(f"  {v}")

    # Label each word with its detector so regions read as attributions,
    # e.g. "fuck(whisper)" vs "niggas(lyrics_gap)".
    labeled = [
        {**w, "word": f"{w['word']}({w.get('detection_source', 'whisper')})"}
        for w in profane
    ]
    regions = _build_censor_regions(
        labeled, int(duration * 1000), args.pad_before, args.pad_after
    )
    total_s = sum(r["end_ms"] - r["start_ms"] for r in regions) / 1000
    print(f"\nmute regions: {len(regions)}, total {total_s:.1f}s ({100 * total_s / duration:.1f}% of track)")
    for r in regions:
        s, e = r["start_ms"] / 1000, r["end_ms"] / 1000
        words_str = " ".join(r["words"][:12]) + (" ..." if len(r["words"]) > 12 else "")
        print(f"  {s:7.2f}-{e:7.2f} ({e - s:5.2f}s): {words_str}")


if __name__ == "__main__":
    main()
