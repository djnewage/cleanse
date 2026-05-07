#!/usr/bin/env python3
"""
End-to-end accuracy test for the Cleanse censoring pipeline.

Runs the full pipeline (transcription → profanity detection → lyrics correction
→ vocab flagging) against a real audio file and prints a detailed report.

Usage:
    python3 test_e2e_accuracy.py <audio_file> [--turbo] [--no-lyrics]

Examples:
    python3 test_e2e_accuracy.py "/path/to/song.mp3"
    python3 test_e2e_accuracy.py "/path/to/song.mp3" --turbo
    python3 test_e2e_accuracy.py "/path/to/song.mp3" --no-lyrics
"""

import argparse
import os
import sys
import time


def format_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:05.2f}"


def format_duration(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def main():
    parser = argparse.ArgumentParser(description="E2E accuracy test for Cleanse pipeline")
    parser.add_argument("audio_file", help="Path to audio file")
    parser.add_argument("--turbo", action="store_true", help="Use turbo mode (beam_size=1)")
    parser.add_argument("--no-lyrics", action="store_true", help="Skip lyrics fetching")
    parser.add_argument("--show-all", action="store_true", help="Show all transcribed words, not just profanity")
    args = parser.parse_args()

    if not os.path.isfile(args.audio_file):
        print(f"Error: File not found: {args.audio_file}", file=sys.stderr)
        sys.exit(1)

    # Import pipeline modules (triggers model loading)
    print("Loading modules...", flush=True)
    from transcribe import transcribe_audio
    from profanity_detector import flag_profanity
    from lyrics_fetcher import extract_metadata, fetch_lyrics, parse_synced_lyrics
    from lyrics_corrector import (
        correct_words_with_lyrics,
        fill_gaps_with_lyrics,
        fill_gaps_with_plain_lyrics,
        extract_profanity_vocab,
        flag_with_profanity_vocab,
    )

    # ── Step 1: Extract metadata ──
    print("Extracting metadata...", flush=True)
    metadata = extract_metadata(args.audio_file)
    artist = metadata.get("artist") or "Unknown"
    title = metadata.get("title") or os.path.basename(args.audio_file)
    duration = metadata.get("duration") or 0

    # ── Step 2: Fetch lyrics ──
    plain_lyrics = None
    synced_lyrics = None
    lyrics_source = None

    if not args.no_lyrics and metadata.get("artist") and metadata.get("title"):
        print(f"Fetching lyrics for: {artist} - {title}...", flush=True)
        lyrics_result = fetch_lyrics(artist, title, duration)
        if lyrics_result:
            plain_lyrics = lyrics_result.get("plain_lyrics")
            synced_lyrics = lyrics_result.get("synced_lyrics")
            lyrics_source = lyrics_result.get("lyrics_source", "unknown")

    # ── Step 3: Transcribe ──
    print(f"Transcribing (turbo={args.turbo})... this may take a while on first run (model download).", flush=True)
    t0 = time.time()
    result = transcribe_audio(
        args.audio_file,
        turbo=args.turbo,
        initial_prompt=plain_lyrics,
    )
    transcribe_time = time.time() - t0

    raw_words = result["words"]
    detected_language = result["language"]
    audio_duration = result["duration"]

    # ── Step 4: Flag profanity ──
    words = flag_profanity(raw_words)

    # Track stats
    stats = {
        "total_words": len(words),
        "profanity_after_flag": sum(1 for w in words if w.get("is_profanity")),
        "corrections": 0,
        "gap_fills": 0,
        "alignment_score": None,
        "vocab_flags": 0,
    }

    # ── Step 5: Lyrics correction ──
    alignment_score = 0.0
    if synced_lyrics:
        words, alignment_score = correct_words_with_lyrics(words, synced_lyrics)
        stats["alignment_score"] = alignment_score
        stats["corrections"] = sum(1 for w in words if w.get("detection_source") == "lyrics_corrected")

    lyrics_aligned = alignment_score >= 0.25

    # ── Step 6: Gap filling ──
    pre_gap_count = len(words)
    if synced_lyrics and lyrics_aligned:
        words = fill_gaps_with_lyrics(words, synced_lyrics, audio_duration=audio_duration)
        if len(words) == pre_gap_count:
            # Synced gap-fill bailed (typically a remix/edit where original
            # lyrics span longer than the audio). Fall back to anchor-based
            # plain gap-fill using the synced lyrics text.
            plain_from_synced = "\n".join(
                line["text"] for line in parse_synced_lyrics(synced_lyrics)
            )
            if plain_from_synced.strip():
                print(
                    "[Pipeline] Synced gap-fill bailed; falling back to plain gap-fill (anchor-based)."
                )
                words = fill_gaps_with_plain_lyrics(
                    words, plain_from_synced, audio_duration
                )
    elif not synced_lyrics and plain_lyrics:
        words = fill_gaps_with_plain_lyrics(words, plain_lyrics, audio_duration)
    stats["gap_fills"] = len(words) - pre_gap_count

    # ── Step 7: Re-flag profanity ──
    if synced_lyrics or plain_lyrics:
        words = flag_profanity(words)

    # ── Step 8: Vocab-based flagging ──
    pre_vocab_count = sum(1 for w in words if w.get("is_profanity"))
    lyrics_for_vocab = plain_lyrics or synced_lyrics
    profanity_vocab = set()
    if lyrics_for_vocab:
        profanity_vocab = extract_profanity_vocab(lyrics_for_vocab)
        if profanity_vocab:
            words = flag_with_profanity_vocab(words, profanity_vocab)
    stats["vocab_flags"] = sum(1 for w in words if w.get("is_profanity")) - pre_vocab_count

    # ── Build report ──
    profane_words = [w for w in words if w.get("is_profanity")]

    # Count by source
    source_counts = {}
    for w in profane_words:
        src = w.get("detection_source", "primary")
        source_counts[src] = source_counts.get(src, 0) + 1

    # ── Print report ──
    print()
    print("═" * 50)
    print("  E2E Accuracy Report")
    print("═" * 50)
    print()
    print(f"  Song:       {artist} - {title}")
    print(f"  Duration:   {format_duration(audio_duration)}")
    print(f"  File:       {os.path.basename(args.audio_file)}")
    lyrics_desc = []
    if synced_lyrics:
        lyrics_desc.append("synced")
    if plain_lyrics:
        lyrics_desc.append("plain")
    if lyrics_source:
        lyrics_desc.append(f"({lyrics_source})")
    print(f"  Lyrics:     {' + '.join(lyrics_desc) if lyrics_desc else 'none'}")
    print()

    print("── Transcription ──")
    print(f"  Total words:     {stats['total_words']}")
    print(f"  Beam size:       {'1 (turbo)' if args.turbo else '5'}")
    print(f"  Language:        {detected_language}")
    print(f"  Time:            {transcribe_time:.1f}s")
    print()

    if stats["alignment_score"] is not None:
        print("── Lyrics Alignment ──")
        print(f"  Alignment score: {stats['alignment_score']:.0%}")
        print(f"  Aligned:         {'Yes' if lyrics_aligned else 'No (< 25%, skipping gap-fill)'}")
        print(f"  Corrections:     {stats['corrections']} words corrected")
        print(f"  Gap-fills:       {stats['gap_fills']} words injected")
        print()

    print("── Profanity Detection ──")
    print(f"  Total flagged:   {len(profane_words)} words")
    if source_counts:
        print("  By source:")
        for src in sorted(source_counts.keys()):
            print(f"    {src:25s} {source_counts[src]}")
    print()

    print("── Flagged Words ──")
    if profane_words:
        for w in profane_words:
            src = w.get("detection_source", "primary")
            conf = w.get("confidence", 0)
            extra = ""
            if w.get("original_word"):
                extra = f' (was: "{w["original_word"]}")'
            print(f'  {format_time(w["start"])}  "{w["word"]:15s}" [conf: {conf:.2f}] {src}{extra}')
    else:
        print("  (none)")

    if args.show_all:
        print()
        print("── All Transcribed Words ──")
        for w in words:
            flag = " ***PROFANITY***" if w.get("is_profanity") else ""
            src = w.get("detection_source", "")
            src_str = f" [{src}]" if src else ""
            print(f'  {format_time(w["start"])}  "{w["word"]}" [conf: {w.get("confidence", 0):.2f}]{src_str}{flag}')
    print()

    if profanity_vocab:
        print("── Profanity Vocab from Lyrics ──")
        print(f"  {', '.join(sorted(profanity_vocab))} ({len(profanity_vocab)} unique)")
        print()

    # ── Summary line ──
    print("─" * 50)
    print(f"  {len(profane_words)} profanities detected in {stats['total_words']} words "
          f"({len(profane_words)/max(stats['total_words'],1)*100:.1f}%)")
    print("─" * 50)


if __name__ == "__main__":
    main()
