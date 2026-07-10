"""Lyrics-based transcription correction using synced lyrics and fuzzy matching."""

import re
import sys
from difflib import SequenceMatcher
from typing import List, Dict, Optional, Tuple
from lyrics_fetcher import parse_synced_lyrics
from profanity_detector import _normalize_word, _wildcard_match, WHITELIST, scan_token

# Configuration constants
TIME_WINDOW_SECONDS = 5.0  # Max time drift to consider words in same window
MIN_SIMILARITY_THRESHOLD = 0.6  # 60% similarity required for correction
HIGH_CONFIDENCE_THRESHOLD = 0.85  # 85%+ similarity = auto-correct
LOW_TRANSCRIPTION_CONF = 0.7  # Only correct transcriptions with <70% confidence
MAX_WORD_LENGTH_DIFF = 3  # Max character difference for word pair matching

# Words whose timestamps are estimates (line-division / anchor interpolation),
# not Whisper-observed. They always yield to real words in timeline conflicts.
SYNTHETIC_SOURCES = {"lyrics", "lyrics_gap"}
MIN_WORD_DURATION = 0.05  # words trimmed below this are unrenderable — drop/transfer

# A displaced synthetic profanity transfers its flag to the real word it
# covers only when the real word plausibly IS the misheard profanity
# ("ducking" <- "fucking"). ASR mishearings are phonetically similar;
# positional guesswork (gap-fill even spacing landing "niggas" on "asked")
# is not, and transferring it would mute clean vocals.
TRANSFER_SIMILARITY_MIN = 0.4


def _is_synthetic(word: Dict) -> bool:
    return word.get("detection_source") in SYNTHETIC_SOURCES


def normalize_word_timeline(
    words: List[Dict], audio_duration: Optional[float] = None
) -> List[Dict]:
    """Enforce the timing invariants the karaoke renderer relies on: sorted by
    start, non-overlapping [start, end) intervals, positive durations, within
    [0, audio_duration]. The renderer binary-searches these intervals — an
    overlap makes two words 'active' at once and the highlight race/jump.

    Conflict rules (left-to-right sweep):
    - synthetic (estimated-timestamp) words yield to real Whisper words;
    - real vs real: the non-profanity word yields (dual-pass merge timing
      rewrites can overlap neighbors — never shrink a mute);
    - a synthetic PROFANITY word that would be trimmed away transfers its
      is_profanity flag to the real word it overlaps instead of vanishing:
      the mute survives and gains accurate Whisper timing.
    """
    if not words:
        return words

    trimmed = dropped = transferred = 0
    swept: List[Dict] = []

    for w in sorted(words, key=lambda x: (x["start"], x["end"])):
        w = dict(w)
        # Clamp to the audio bounds and repair inverted intervals.
        w["start"] = max(0.0, w["start"])
        if audio_duration is not None:
            w["end"] = min(w["end"], audio_duration)
            w["start"] = min(w["start"], w["end"])
        if w["end"] <= w["start"]:
            w["end"] = w["start"] + MIN_WORD_DURATION

        while True:
            prev = swept[-1] if swept else None
            if prev is None or w["start"] >= prev["end"] - 1e-9:
                swept.append(w)
                break

            # Overlap. Decide who yields: synthetic yields to real; between
            # equals, profanity wins; between equal-priority, the later yields.
            prev_synth, w_synth = _is_synthetic(prev), _is_synthetic(w)
            if prev_synth and not w_synth:
                yielder, keeper = prev, w
            elif w_synth and not prev_synth:
                yielder, keeper = w, prev
            elif prev.get("is_profanity") and not w.get("is_profanity"):
                yielder, keeper = w, prev
            elif w.get("is_profanity") and not prev.get("is_profanity"):
                yielder, keeper = prev, w
            else:
                yielder, keeper = w, prev

            if yielder is w:
                # Trim the later word's start up to prev's end.
                new_start = prev["end"]
                if w["end"] - new_start >= MIN_WORD_DURATION:
                    w["start"] = new_start
                    trimmed += 1
                    swept.append(w)
                else:
                    # Nothing left of w after trimming.
                    if (
                        w.get("is_profanity")
                        and not prev.get("is_profanity")
                        and _compute_word_similarity(w["word"], prev["word"])
                        >= TRANSFER_SIMILARITY_MIN
                    ):
                        prev["is_profanity"] = True
                        prev["detection_source"] = "lyrics"
                        transferred += 1
                    else:
                        dropped += 1
                break
            else:
                # Trim the earlier word's end down to w's start.
                new_end = w["start"]
                if new_end - prev["start"] >= MIN_WORD_DURATION:
                    prev["end"] = new_end
                    trimmed += 1
                    swept.append(w)
                    break
                # Nothing left of prev: transfer/drop it and re-test w
                # against the word before it.
                if (
                    prev.get("is_profanity")
                    and not w.get("is_profanity")
                    and _compute_word_similarity(prev["word"], w["word"])
                    >= TRANSFER_SIMILARITY_MIN
                ):
                    w["is_profanity"] = True
                    w["detection_source"] = "lyrics"
                    transferred += 1
                else:
                    dropped += 1
                swept.pop()

    if trimmed or dropped or transferred:
        print(
            f"[LyricsCorrector] Timeline normalized: {trimmed} trimmed, "
            f"{dropped} dropped, {transferred} profanity flags transferred",
            file=sys.stderr,
        )
    return swept


def correct_words_with_lyrics(
    transcribed_words: List[Dict],
    synced_lyrics: str,
    auto_correct_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
) -> Tuple[List[Dict], float]:
    """
    Correct transcribed words using synced lyrics with fuzzy matching.

    Args:
        transcribed_words: List of {word, start, end, confidence, is_profanity, ...}
        synced_lyrics: LRC format lyrics string
        auto_correct_threshold: Similarity threshold for automatic correction (0-1)

    Returns:
        Tuple of:
        - List of words with corrections applied, preserving original timing.
          Corrected words have additional fields:
          - original_word: The transcribed text before correction
          - correction_confidence: How confident we are in the correction (0-1)
        - Alignment score (0.0-1.0): fraction of transcribed words that found
          a lyrics match within the time window. Low scores indicate the lyrics
          don't match the audio (e.g., remix with reordered vocals).
    """
    if not synced_lyrics or not transcribed_words:
        return transcribed_words, 0.0

    # Parse LRC lyrics
    lyrics_lines = parse_synced_lyrics(synced_lyrics)
    if not lyrics_lines:
        return transcribed_words, 0.0

    # Build lyrics word lookup structure with timing
    lyrics_words = []
    for i, line in enumerate(lyrics_lines):
        # Calculate line duration
        next_time = lyrics_lines[i + 1]["time"] if i + 1 < len(lyrics_lines) else line["time"] + 5.0
        line_duration = min(next_time - line["time"], 5.0)

        words_in_line = line["text"].split()
        num_words = max(len(words_in_line), 1)
        word_duration = line_duration / num_words

        for j, word in enumerate(words_in_line):
            # Estimate word timestamp
            estimated_start = line["time"] + j * word_duration
            estimated_end = estimated_start + min(word_duration, 0.35)

            # Clean word (remove punctuation from edges)
            clean_word = re.sub(r"^[^\w'*@$]+|[^\w'*@$]+$", "", word)
            if clean_word:
                lyrics_words.append(
                    {
                        "word": clean_word,
                        "start": estimated_start,
                        "end": estimated_end,
                        "line_index": i,
                    }
                )

    # Process each transcribed word
    corrected_words = []
    matched_count = 0
    for tw in transcribed_words:
        # Find best match in time window
        match_result = _find_best_match_in_window(
            tw, tw["start"] - TIME_WINDOW_SECONDS, tw["start"] + TIME_WINDOW_SECONDS, lyrics_words
        )

        if match_result:
            matched_count += 1
            lyrics_word, similarity = match_result

            # Decide if we should correct
            if _should_correct_word(tw, lyrics_word, similarity, auto_correct_threshold):
                # Apply correction
                corrected_word = tw.copy()
                corrected_word["original_word"] = tw["word"]
                corrected_word["word"] = lyrics_word
                corrected_word["correction_confidence"] = similarity
                corrected_word["detection_source"] = "lyrics_corrected"

                print(
                    f"[LyricsCorrector] Corrected '{tw['word']}' -> '{lyrics_word}' "
                    f"(similarity: {similarity:.2f}, trans_conf: {tw['confidence']:.2f})"
                )

                corrected_words.append(corrected_word)
            else:
                corrected_words.append(tw)
        else:
            # No match found, keep original
            corrected_words.append(tw)

    alignment_score = matched_count / len(transcribed_words) if transcribed_words else 0.0
    print(
        f"[LyricsCorrector] Alignment score: {alignment_score:.0%} "
        f"({matched_count}/{len(transcribed_words)} words matched)",
        file=sys.stderr,
    )

    return corrected_words, alignment_score


def _find_best_match_in_window(
    transcribed_word: Dict,
    window_start: float,
    window_end: float,
    lyrics_words: List[Dict],
) -> Optional[Tuple[str, float]]:
    """
    Find the best matching lyrics word within a time window.

    Args:
        transcribed_word: Single word from transcription
        window_start: Start of time window (seconds)
        window_end: End of time window (seconds)
        lyrics_words: All lyrics words with timing

    Returns:
        (best_match_word, confidence_score) or None if no good match
    """
    best_match = None
    best_score = 0.0

    for lw in lyrics_words:
        # Skip words outside time window
        if lw["start"] < window_start or lw["start"] > window_end:
            continue

        # Compute similarity
        similarity = _compute_word_similarity(transcribed_word["word"], lw["word"])

        # Check word length difference (reject if too different)
        len_diff = abs(len(transcribed_word["word"]) - len(lw["word"]))
        if len_diff > MAX_WORD_LENGTH_DIFF:
            continue

        # Track best match
        if similarity > best_score and similarity >= MIN_SIMILARITY_THRESHOLD:
            best_score = similarity
            best_match = lw["word"]

    if best_match:
        return (best_match, best_score)
    return None


def _compute_word_similarity(word1: str, word2: str) -> float:
    """
    Compute similarity score between two words using normalized comparison.

    Uses SequenceMatcher with normalization (lowercase, strip punctuation).
    Returns 0.0-1.0 where 1.0 is exact match.
    """
    # Normalize both words (same as profanity detection)
    norm1 = _normalize_word(word1)
    norm2 = _normalize_word(word2)

    # Try all normalized variations, take best match
    best_score = 0.0
    for v1 in norm1:
        for v2 in norm2:
            score = SequenceMatcher(None, v1.lower(), v2.lower()).ratio()
            best_score = max(best_score, score)

    return best_score


def _is_profanity(word: str) -> bool:
    """Check if a word is profanity via the shared tiered matcher (exact +
    de-elongation + fuzzy, whitelist-protected)."""
    return scan_token(word) is not None


def _should_correct_word(
    transcribed_word: Dict,
    lyrics_word: str,
    similarity: float,
    threshold: float,
) -> bool:
    """
    Determine if a transcribed word should be corrected.

    Considers:
    - Similarity score vs threshold
    - Original transcription confidence
    - Whether the lyrics word is profanity (use lower thresholds — missing
      profanity is worse than a false positive the user can un-flag)

    Decision Matrix (normal words):
    - Trans conf < 0.5 + similarity >= 0.60 → correct
    - Trans conf 0.5-0.7 + similarity >= 0.85 → correct
    - Trans conf >= 0.7 + similarity >= 0.90 → correct
    - Otherwise → skip

    Decision Matrix (profanity words — more aggressive):
    - Trans conf < 0.5 + similarity >= 0.50 → correct
    - Trans conf 0.5-0.7 + similarity >= 0.70 → correct
    - Trans conf >= 0.7 + similarity >= 0.80 → correct
    """
    trans_conf = transcribed_word.get("confidence", 1.0)

    # Never correct if words are identical
    if transcribed_word["word"].lower() == lyrics_word.lower():
        return False

    # Use lower thresholds when the lyrics word is profanity
    lyrics_is_profane = _is_profanity(lyrics_word)

    if lyrics_is_profane:
        if trans_conf < 0.5:
            return similarity >= 0.50
        elif trans_conf < LOW_TRANSCRIPTION_CONF:
            return similarity >= 0.70
        else:
            return similarity >= 0.80
    else:
        if trans_conf < 0.5:
            return similarity >= 0.60
        elif trans_conf < LOW_TRANSCRIPTION_CONF:
            return similarity >= threshold
        else:
            return similarity >= threshold and similarity >= 0.90


def fill_gaps_with_lyrics(
    transcribed_words: List[Dict],
    synced_lyrics: str,
    overlap_time_threshold: float = 0.75,
    coverage_threshold: float = 0.3,
    audio_duration: float | None = None,
) -> List[Dict]:
    """
    Fill gaps in transcription where synced lyrics have content but transcription is empty.

    For each lyrics line, checks how many of its words are "covered" by existing
    transcription (temporal proximity + text similarity). If coverage is below the
    threshold, injects the uncovered lyrics words with estimated timestamps.

    Args:
        transcribed_words: List of word dicts from transcription
        synced_lyrics: LRC format string
        overlap_time_threshold: Max seconds to consider a transcribed word as covering a lyrics word
        coverage_threshold: Fraction of line words that must be covered to skip gap-fill
        audio_duration: If provided, lyric lines starting after this (with a small
            buffer) are dropped. Lets the function work for edits/remixes that are
            shorter than the original song without tripping the 2x safeguard.

    Returns:
        New list with original words + gap-filled words, sorted by start time.
        Gap-filled words have detection_source='lyrics_gap', confidence=0.4.
    """
    if not synced_lyrics or not transcribed_words:
        return transcribed_words

    lyrics_lines = parse_synced_lyrics(synced_lyrics)
    if not lyrics_lines:
        return transcribed_words

    if audio_duration is not None:
        original_count = len(lyrics_lines)
        lyrics_lines = [l for l in lyrics_lines if l["time"] <= audio_duration + 5]
        if len(lyrics_lines) < original_count:
            print(
                f"[LyricsCorrector] Clipped synced lyrics to audio duration "
                f"({audio_duration:.1f}s): {len(lyrics_lines)} of {original_count} lines kept",
                file=sys.stderr,
            )
        if not lyrics_lines:
            return transcribed_words

    new_words = []

    # Skip lyrics lines before the first transcribed word (instrumental intro)
    first_word_start = transcribed_words[0]["start"] if transcribed_words else 0.0

    for i, line in enumerate(lyrics_lines):
        if line["time"] < first_word_start - 1.0:
            continue

        # Calculate line duration (time to next line, capped at 5s)
        next_time = lyrics_lines[i + 1]["time"] if i + 1 < len(lyrics_lines) else line["time"] + 5.0
        line_duration = min(next_time - line["time"], 5.0)

        words_in_line = line["text"].split()
        num_words = max(len(words_in_line), 1)
        word_duration = line_duration / num_words

        # Build lyrics words with estimated timestamps for this line
        line_lyrics_words = []
        for j, word in enumerate(words_in_line):
            clean_word = re.sub(r"^[^\w'*@$]+|[^\w'*@$]+$", "", word)
            if not clean_word:
                continue
            estimated_start = line["time"] + j * word_duration
            estimated_end = estimated_start + min(word_duration, 0.35)
            line_lyrics_words.append({
                "word": clean_word,
                "start": round(estimated_start, 3),
                "end": round(estimated_end, 3),
            })

        if not line_lyrics_words:
            continue

        # Check coverage: how many lyrics words have a matching transcribed word nearby?
        covered_count = 0
        uncovered_words = []

        for lw in line_lyrics_words:
            is_covered = False
            for tw in transcribed_words:
                time_dist = abs(tw["start"] - lw["start"])
                if time_dist > overlap_time_threshold:
                    continue
                similarity = _compute_word_similarity(tw["word"], lw["word"])
                if similarity >= 0.5:
                    is_covered = True
                    break
            if is_covered:
                covered_count += 1
            else:
                uncovered_words.append(lw)

        # If line is sufficiently covered, skip it
        coverage = covered_count / len(line_lyrics_words)
        if coverage >= coverage_threshold:
            continue

        # Inject uncovered words from this line
        for lw in uncovered_words:
            new_words.append({
                "word": lw["word"],
                "start": lw["start"],
                "end": lw["end"],
                "confidence": 0.4,
                "is_profanity": False,
                "detection_source": "lyrics_gap",
            })

    if not new_words:
        return transcribed_words

    # Reject if gap-fill would add far more words than the transcription — lyrics are likely wrong
    if len(new_words) > len(transcribed_words) * 2:
        print(
            f"[LyricsCorrector] Rejected synced gap-fill: {len(new_words)} new words >> "
            f"{len(transcribed_words)} transcribed (lyrics likely wrong)",
            file=sys.stderr,
        )
        return transcribed_words

    print(f"[LyricsCorrector] Gap-filled {len(new_words)} words from synced lyrics")

    result = list(transcribed_words) + new_words
    result.sort(key=lambda w: w["start"])
    return result


def _find_lyrics_alignment_start(
    transcribed_words: List[Dict],
    lyrics_tokens: List[str],
    window_size: int = 5,
) -> Optional[int]:
    """
    Find the position in lyrics where the transcription begins.

    Slides a window of transcribed words across the lyrics tokens,
    computing average word similarity at each position. Returns the
    lyrics index with the best match, or None if no good alignment found.
    """
    if not transcribed_words or not lyrics_tokens:
        return None

    actual_window = min(window_size, len(transcribed_words))
    trans_window = [tw["word"] for tw in transcribed_words[:actual_window]]

    if len(lyrics_tokens) < actual_window:
        return 0

    best_pos = None
    best_score = 0.0

    for pos in range(len(lyrics_tokens) - actual_window + 1):
        lyrics_window = lyrics_tokens[pos : pos + actual_window]
        total_sim = sum(
            _compute_word_similarity(tw, lw)
            for tw, lw in zip(trans_window, lyrics_window)
        )
        avg_sim = total_sim / actual_window

        if avg_sim > best_score:
            best_score = avg_sim
            best_pos = pos

    return best_pos if best_score >= 0.4 else None


def fill_gaps_with_plain_lyrics(
    transcribed_words: List[Dict],
    plain_lyrics: str,
    song_duration: float,
) -> List[Dict]:
    """
    Fill gaps using plain lyrics (no timestamps) by aligning word sequences.

    Fallback for when synced/timestamped lyrics aren't available from LRCLIB.
    Uses a sliding window to find where in the lyrics the transcription starts,
    then greedy forward matching to map transcribed words to lyrics positions.
    Lyrics words not covered by any transcribed word are injected as gap-fills.

    Args:
        transcribed_words: List of word dicts from transcription
        plain_lyrics: Plain text lyrics (newline-separated lines)
        song_duration: Total audio duration in seconds

    Returns:
        New list with original words + gap-filled words, sorted by start time.
        Gap-filled words have detection_source='lyrics_gap', confidence=0.3.
    """
    if not plain_lyrics or not transcribed_words:
        return transcribed_words

    # Tokenize lyrics into clean word list
    lyrics_tokens = []
    for line in plain_lyrics.strip().split("\n"):
        for word in line.split():
            clean = re.sub(r"^[^\w'*@$]+|[^\w'*@$]+$", "", word)
            if clean:
                lyrics_tokens.append(clean)

    if not lyrics_tokens:
        return transcribed_words

    # Step 1: Find where transcription starts in the lyrics
    alignment_start = _find_lyrics_alignment_start(transcribed_words, lyrics_tokens)
    if alignment_start is None:
        print(
            f"[LyricsCorrector] Plain gap-fill: no alignment start found "
            f"(lyrics_tokens={len(lyrics_tokens)}, trans={len(transcribed_words)})",
            file=sys.stderr,
        )
        return transcribed_words

    # Step 2: Greedy forward alignment from the start position
    alignment = []  # (lyrics_idx, trans_idx) pairs
    lyrics_ptr = alignment_start

    for t_idx, tw in enumerate(transcribed_words):
        best_idx = None
        best_sim = 0.0
        # Look ahead up to 20 lyrics words for a match
        for l_idx in range(lyrics_ptr, min(lyrics_ptr + 20, len(lyrics_tokens))):
            sim = _compute_word_similarity(tw["word"], lyrics_tokens[l_idx])
            if sim > best_sim and sim >= 0.6:
                best_sim = sim
                best_idx = l_idx

        if best_idx is not None:
            alignment.append((best_idx, t_idx))
            lyrics_ptr = best_idx + 1

    if not alignment:
        print(
            f"[LyricsCorrector] Plain gap-fill: alignment empty (start={alignment_start})",
            file=sys.stderr,
        )
        return transcribed_words

    # Step 3: Identify gap segments and inject words
    matched_lyrics = {a[0] for a in alignment}
    new_words = []

    # Start from the first aligned lyrics word — skip the pre-gap before vocals begin
    # (instrumental intros should not be filled with lyrics words)
    first_matched_idx = alignment[0][0] if alignment else 0
    i = first_matched_idx
    while i < len(lyrics_tokens):
        if i in matched_lyrics:
            i += 1
            continue

        # Start of a gap segment
        gap_start = i
        while i < len(lyrics_tokens) and i not in matched_lyrics:
            i += 1
        gap_end = i  # exclusive

        gap_tokens = lyrics_tokens[gap_start:gap_end]

        # Find time anchor BEFORE this gap (latest matched word before gap_start)
        anchor_before = 0.0
        for a_l, a_t in alignment:
            if a_l < gap_start:
                anchor_before = transcribed_words[a_t]["end"]

        # Find time anchor AFTER this gap (earliest matched word at or after gap_end)
        anchor_after = song_duration
        for a_l, a_t in alignment:
            if a_l >= gap_end:
                anchor_after = transcribed_words[a_t]["start"]
                break

        # Skip if no room for gap words
        if anchor_after <= anchor_before:
            continue

        # Distribute gap words evenly between anchors
        gap_duration = anchor_after - anchor_before
        word_spacing = gap_duration / (len(gap_tokens) + 1)

        for j, token in enumerate(gap_tokens):
            est_start = anchor_before + (j + 1) * word_spacing
            est_end = est_start + min(word_spacing * 0.8, 0.35)
            new_words.append(
                {
                    "word": token,
                    "start": round(est_start, 3),
                    "end": round(est_end, 3),
                    "confidence": 0.3,
                    "is_profanity": False,
                    "detection_source": "lyrics_gap",
                }
            )

    if not new_words:
        print(
            f"[LyricsCorrector] Plain gap-fill: no gap segments produced "
            f"(alignment={len(alignment)}, lyrics_tokens={len(lyrics_tokens)})",
            file=sys.stderr,
        )
        return transcribed_words

    # Reject if gap-fill would add far more words than the transcription — lyrics are likely wrong
    if len(new_words) > len(transcribed_words) * 2:
        print(
            f"[LyricsCorrector] Rejected plain gap-fill: {len(new_words)} new words >> "
            f"{len(transcribed_words)} transcribed (lyrics likely wrong)",
            file=sys.stderr,
        )
        return transcribed_words

    print(
        f"[LyricsCorrector] Plain-lyrics gap-filled {len(new_words)} words "
        f"(aligned at lyrics position {alignment_start})"
    )

    result = list(transcribed_words) + new_words
    result.sort(key=lambda w: w["start"])
    return result


def _line_corroborated(
    line_text: str,
    line_start: float,
    line_end: float,
    transcribed_words: List[Dict],
    min_ratio: float = 0.3,
    sim_threshold: float = 0.6,
) -> bool:
    """Is this LRC line actually being sung at its timestamp? True when at
    least ``min_ratio`` of the line's words have a REAL transcribed word
    (not a synthetic injection) within [line_start - 1, line_end + 1] at
    ``sim_threshold`` similarity.

    Guards the synced-lyrics profanity injector against offset/wrong-version
    lyrics: a global alignment score passes easily on repetitive songs, but a
    line whose words are nowhere near its timestamp must not inject mutes.
    """
    line_words = line_text.split()
    if not line_words:
        return False

    nearby = [
        tw for tw in transcribed_words
        if tw.get("detection_source") not in SYNTHETIC_SOURCES
        and line_start - 1.0 <= tw["start"] <= line_end + 1.0
    ]
    if not nearby:
        return False

    matched = sum(
        1 for lw in line_words
        if any(_compute_word_similarity(lw, tw["word"]) >= sim_threshold for tw in nearby)
    )
    return matched / len(line_words) >= min_ratio


def find_lyrics_profanity(
    synced_lyrics: str,
    transcribed_words: List[Dict],
    overlap_threshold: float = 0.75,
) -> List[Dict]:
    """Find profanities in synced lyrics that weren't detected by transcription.

    Each line must be corroborated by the transcript (see _line_corroborated)
    before it may inject — offset or wrong-version synced lyrics otherwise
    place mutes over clean audio.
    """
    lines = parse_synced_lyrics(synced_lyrics)
    if not lines:
        return []

    new_detections = []
    skipped_lines = 0

    # Skip lyrics lines before the first transcribed word (instrumental intro)
    first_word_start = transcribed_words[0]["start"] if transcribed_words else 0.0

    for i, line in enumerate(lines):
        if line["time"] < first_word_start - 1.0:
            continue

        # Determine line duration (time to next line, capped at 5s)
        next_time = lines[i + 1]["time"] if i + 1 < len(lines) else line["time"] + 5.0
        line_duration = min(next_time - line["time"], 5.0)

        words_in_line = line["text"].split()
        num_words = max(len(words_in_line), 1)
        word_duration = line_duration / num_words

        line_checked = False
        line_ok = False
        for j, word in enumerate(words_in_line):
            # Same tiered, whitelist-aware matcher as the ASR path. The old raw
            # contains_profanity check bypassed WHITELIST (injecting mutes for
            # god/hell/fat/panty) and missed stylized spellings (fuuuck).
            if scan_token(word) is None:
                continue

            # Corroborate the line once, lazily (only lines with profanity pay).
            if not line_checked:
                line_checked = True
                line_ok = _line_corroborated(
                    line["text"], line["time"], line["time"] + line_duration,
                    transcribed_words,
                )
                if not line_ok:
                    skipped_lines += 1
            if not line_ok:
                break

            # Estimate word timestamp: center each word in its slot within the line
            estimated_start = line["time"] + j * word_duration
            estimated_end = estimated_start + min(word_duration, 0.35)

            # Check if any transcribed profanity exists near this timestamp
            already_detected = any(
                abs(tw["start"] - estimated_start) < overlap_threshold
                and tw.get("is_profanity")
                for tw in transcribed_words
            )

            if not already_detected:
                # Clean the word for display (remove punctuation)
                clean_word = re.sub(r"[^\w'*@$]", "", word)
                if clean_word:
                    new_detections.append({
                        "word": clean_word,
                        "start": round(estimated_start, 3),
                        "end": round(estimated_end, 3),
                        "confidence": 0.5,
                        "is_profanity": True,
                        "detection_source": "lyrics",
                    })

    if skipped_lines:
        print(
            f"[LyricsCorrector] Lyrics profanity injector: skipped {skipped_lines} "
            f"uncorroborated line(s) (transcript doesn't match line timing)",
            file=sys.stderr,
        )
    return new_detections


def find_plain_lyrics_profanity(
    transcribed_words: List[Dict],
    plain_lyrics: str,
    song_duration: float,
    cover_window: float = 0.75,
    inject_pad: float = 0.0,
    max_gap_span: float = 6.0,
) -> List[Dict]:
    """Inject profanities that appear in PLAIN (un-timestamped) lyrics but are
    missing from the transcription. The plain-lyrics analogue of
    ``find_lyrics_profanity`` (which needs synced lyrics) — closes the gap for the
    common case where only plain lyrics are available (e.g. Genius).

    Aligns the lyric word-sequence to the transcript (same greedy match as the
    plain gap-fill) to place each missed profanity at an estimated time:
      * if the profane lyric word aligned to a transcribed word, use that word's
        timing (accurate) — this recovers mis-heard profanities like "nigga"->"yeah";
      * otherwise interpolate between the nearest matched anchors, but only when the
        gap is tight (<= ``max_gap_span``) so we don't censor a random spot.
    Skips any profanity already detected nearby (``cover_window``). ``inject_pad``
    defaults to 0: the word interval should represent the word itself — safety
    padding is the audio processor's job (it already adds extra for
    lyrics-sourced words), and pre-padded intervals both double-dipped there
    and broke the karaoke non-overlap invariant.

    Returns NEW words only (caller appends + re-sorts). Exempt from the gap-fill's
    global 2x reject — it only ever adds the few profane tokens, never bulk lyrics.
    """
    if not plain_lyrics or not transcribed_words:
        return []

    lyrics_tokens: List[str] = []
    for line in plain_lyrics.strip().split("\n"):
        for word in line.split():
            clean = re.sub(r"^[^\w'*@$]+|[^\w'*@$]+$", "", word)
            if clean:
                lyrics_tokens.append(clean)
    if not lyrics_tokens:
        return []

    # Profane lyric token positions -> display word.
    prof_tokens: Dict[int, str] = {}
    for li, tok in enumerate(lyrics_tokens):
        if _is_profanity(tok) and not any(v in WHITELIST for v in _normalize_word(tok.lower())):
            prof_tokens[li] = re.sub(r"[^\w'*@$]", "", tok)
    if not prof_tokens:
        return []

    # Greedy forward alignment lyrics -> transcript (mirrors fill_gaps_with_plain_lyrics).
    start = _find_lyrics_alignment_start(transcribed_words, lyrics_tokens)
    if start is None:
        return []
    alignment: List[tuple] = []  # (lyrics_idx, trans_idx)
    ptr = start
    for t_idx, tw in enumerate(transcribed_words):
        best_idx, best_sim = None, 0.0
        for l_idx in range(ptr, min(ptr + 20, len(lyrics_tokens))):
            sim = _compute_word_similarity(tw["word"], lyrics_tokens[l_idx])
            if sim > best_sim and sim >= 0.6:
                best_sim, best_idx = sim, l_idx
        if best_idx is not None:
            alignment.append((best_idx, t_idx))
            ptr = best_idx + 1
    if not alignment:
        return []
    matched = {a[0]: a[1] for a in alignment}

    detected_times = [
        (w["start"] + w["end"]) / 2 for w in transcribed_words if w.get("is_profanity")
    ]

    def estimate(li: int):
        if li in matched:                          # aligned -> accurate timing
            tw = transcribed_words[matched[li]]
            return tw["start"], tw["end"], True
        before_t = after_t = None                  # else interpolate between anchors
        for a_l, a_t in alignment:
            if a_l < li:
                before_t = transcribed_words[a_t]["end"]
            elif a_l > li:
                after_t = transcribed_words[a_t]["start"]
                break
        if before_t is None and after_t is None:
            return None
        if before_t is None:
            before_t = max(after_t - 0.5, 0.0)
        if after_t is None:
            after_t = min(before_t + 0.5, song_duration)
        if after_t <= before_t or (after_t - before_t) > max_gap_span:
            return None                            # too wide to place confidently
        mid = (before_t + after_t) / 2
        return mid, mid + 0.3, False

    injected: List[Dict] = []
    for li, word in sorted(prof_tokens.items()):
        if li in matched and transcribed_words[matched[li]].get("is_profanity"):
            continue                               # already caught
        est = estimate(li)
        if est is None:
            continue
        s, e, _accurate = est
        center = (s + e) / 2
        if any(abs(center - dt) < cover_window for dt in detected_times):
            continue                               # already covered nearby
        injected.append({
            "word": word,
            "start": round(max(s - inject_pad, 0.0), 3),
            "end": round(e + inject_pad, 3),
            "confidence": 0.5,
            "is_profanity": True,
            "detection_source": "lyrics",
        })
        detected_times.append(center)              # avoid double-injecting repeats

    if injected:
        print(
            f"[LyricsCorrector] Plain-lyrics profanity injector: recovered {len(injected)} "
            f"missed profanit{'y' if len(injected) == 1 else 'ies'} from lyrics",
            file=sys.stderr,
        )
    return injected


def extract_profanity_vocab(lyrics_text: str) -> set:
    """
    Extract unique profanity words from lyrics text (time-agnostic).

    Useful for remixes or poor-alignment scenarios where timestamp-based
    matching fails but the vocabulary is still informative.

    Filters out WHITELIST entries — better-profanity flags some non-profane
    words ("god", "fat", "slave", proper nouns like "Woody"), and including
    them in the vocab causes fuzzy-match false positives downstream.
    """
    vocab = set()
    # Keep '*' and '-' so censored lyric spellings (f***ing — common on Genius)
    # survive tokenization and reach the wildcard tier.
    for word in re.findall(r"[\w'*-]+", lyrics_text):
        hit = scan_token(word)
        if hit:
            lowered = word.lower()
            if any(v in WHITELIST for v in _normalize_word(lowered)):
                continue
            # A censored spelling enters the vocab as its matched real word
            # ("f***ing" -> "fucking", "b*tches" -> "bitches") so downstream
            # fuzzy matching has a real root to compare transcribed words
            # against. Single-censor-char forms hit the exact tier (leet map)
            # before the wildcard tier, so resolve those explicitly too.
            if hit["match_type"] == "wildcard":
                vocab.add(hit["matched"].lower())
            elif re.search(r"[*\-]", lowered):
                resolved = _wildcard_match(lowered)
                vocab.add(resolved["matched"].lower() if resolved else lowered)
            else:
                vocab.add(lowered)
    return vocab


def flag_with_profanity_vocab(
    words: list,
    profanity_vocab: set,
    similarity_threshold: float = 0.75,
    lyrics_text: str | None = None,
) -> list:
    """
    Flag transcribed words that fuzzy-match known profanity from lyrics.

    Time-agnostic — works for remixes where lyrics ordering doesn't match.
    Only flags words not already marked as profanity.

    When ``lyrics_text`` is given, transcribed words that appear verbatim in
    the lyrics are never fuzzy-flagged: they're the lyrics' own (clean) word,
    not a mishearing of the profanity. This is what separates "witches" in a
    song whose lyrics contain both "witches" and "bitches" (legit — don't mute)
    from a transcribed "ducking" that appears nowhere in lyrics containing
    "fucking" (an ASR soft-substitute — mute it).
    """
    if not profanity_vocab:
        return words

    lyrics_words = (
        set(re.findall(r"[\w']+", lyrics_text.lower())) if lyrics_text else set()
    )

    # SequenceMatcher ratio is permissive on short tokens — "He's" vs "hoes",
    # "toes" vs "hoes", and "holes" vs "hoes" all score 0.75. Require a tighter
    # match for short vocab words to avoid false positives.
    def _threshold_for(pword: str) -> float:
        n = len(pword)
        if n <= 3:
            return 0.95
        if n == 4:
            # Single-substitution against a 4-letter word gives ratio ~0.85
            # ("hes"/"holes" vs "hoes"). Tighten so coincidental near-matches
            # don't get flagged as profanity.
            return 0.90
        return similarity_threshold

    flagged_count = 0
    result = []
    for w in words:
        if w.get("is_profanity"):
            result.append(w)
            continue

        # Defense in depth: even if a WHITELIST word slipped into the vocab
        # somehow, never flag a transcribed word that itself is whitelisted.
        if any(v in WHITELIST for v in _normalize_word(w["word"])):
            result.append(w)
            continue

        # Words the lyrics themselves contain are legit, not soft-substitutes.
        if re.sub(r"[^\w']", "", w["word"]).lower() in lyrics_words:
            result.append(w)
            continue

        matched = False
        for pword in profanity_vocab:
            if _compute_word_similarity(w["word"], pword) >= _threshold_for(pword):
                matched = True
                break

        if matched:
            flagged_count += 1
            result.append({**w, "is_profanity": True, "detection_source": "lyrics"})
        else:
            result.append(w)

    if flagged_count:
        print(
            f"[LyricsCorrector] Vocab-based profanity flagging: {flagged_count} additional words flagged",
            file=sys.stderr,
        )

    return result


# Example usage for testing
if __name__ == "__main__":
    # Example transcribed words
    transcribed = [
        {"word": "how's", "start": 12.5, "end": 12.8, "confidence": 0.65, "is_profanity": False},
        {"word": "feed", "start": 14.2, "end": 14.6, "confidence": 0.55, "is_profanity": False},
    ]

    # Example synced lyrics
    synced = """[00:12.50] Charge them hos a fee
[00:15.00] I don't get into the chatter"""

    # Run correction
    corrected, score = correct_words_with_lyrics(transcribed, synced, auto_correct_threshold=0.85)

    print("\n=== Correction Results ===")
    for w in corrected:
        if "original_word" in w:
            print(
                f"[OK] {w['original_word']} -> {w['word']} "
                f"(confidence: {w['correction_confidence']:.2f})"
            )
        else:
            print(f"[SKIP] {w['word']} (no correction)")
