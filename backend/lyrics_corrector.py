"""Lyrics-based transcription correction using synced lyrics and fuzzy matching."""

import re
from difflib import SequenceMatcher
from typing import List, Dict, Optional, Tuple
from lyrics_fetcher import parse_synced_lyrics
from profanity_detector import _normalize_word

# Configuration constants
TIME_WINDOW_SECONDS = 5.0  # Max time drift to consider words in same window
MIN_SIMILARITY_THRESHOLD = 0.6  # 60% similarity required for correction
HIGH_CONFIDENCE_THRESHOLD = 0.85  # 85%+ similarity = auto-correct
LOW_TRANSCRIPTION_CONF = 0.7  # Only correct transcriptions with <70% confidence
MAX_WORD_LENGTH_DIFF = 3  # Max character difference for word pair matching


def correct_words_with_lyrics(
    transcribed_words: List[Dict],
    synced_lyrics: str,
    auto_correct_threshold: float = HIGH_CONFIDENCE_THRESHOLD,
) -> List[Dict]:
    """
    Correct transcribed words using synced lyrics with fuzzy matching.

    Args:
        transcribed_words: List of {word, start, end, confidence, is_profanity, ...}
        synced_lyrics: LRC format lyrics string
        auto_correct_threshold: Similarity threshold for automatic correction (0-1)

    Returns:
        List of words with corrections applied, preserving original timing.
        Corrected words have additional fields:
        - original_word: The transcribed text before correction
        - correction_confidence: How confident we are in the correction (0-1)
    """
    if not synced_lyrics or not transcribed_words:
        return transcribed_words

    # Parse LRC lyrics
    lyrics_lines = parse_synced_lyrics(synced_lyrics)
    if not lyrics_lines:
        return transcribed_words

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
    for tw in transcribed_words:
        # Find best match in time window
        match_result = _find_best_match_in_window(
            tw, tw["start"] - TIME_WINDOW_SECONDS, tw["start"] + TIME_WINDOW_SECONDS, lyrics_words
        )

        if match_result:
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
                    f"[LyricsCorrector] Corrected '{tw['word']}' → '{lyrics_word}' "
                    f"(similarity: {similarity:.2f}, trans_conf: {tw['confidence']:.2f})"
                )

                corrected_words.append(corrected_word)
            else:
                corrected_words.append(tw)
        else:
            # No match found, keep original
            corrected_words.append(tw)

    return corrected_words


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
    - Word length difference (reject if too different)

    Decision Matrix:
    - Trans conf < 0.5 + similarity >= 0.60 → correct
    - Trans conf 0.5-0.7 + similarity >= 0.85 → correct
    - Trans conf >= 0.7 + similarity >= 0.85 → correct (only high confidence)
    - Otherwise → skip
    """
    trans_conf = transcribed_word.get("confidence", 1.0)

    # Never correct if words are identical
    if transcribed_word["word"].lower() == lyrics_word.lower():
        return False

    # Decision matrix
    if trans_conf < 0.5:
        # Low transcription confidence - correct if reasonable similarity
        return similarity >= 0.60
    elif trans_conf < LOW_TRANSCRIPTION_CONF:
        # Medium transcription confidence - only correct if high similarity
        return similarity >= threshold
    else:
        # High transcription confidence - only correct if very high similarity
        # This prevents correcting accurate transcriptions
        return similarity >= threshold and similarity >= 0.90


def fill_gaps_with_lyrics(
    transcribed_words: List[Dict],
    synced_lyrics: str,
    overlap_time_threshold: float = 0.75,
    coverage_threshold: float = 0.3,
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

    Returns:
        New list with original words + gap-filled words, sorted by start time.
        Gap-filled words have detection_source='lyrics_gap', confidence=0.4.
    """
    if not synced_lyrics or not transcribed_words:
        return transcribed_words

    lyrics_lines = parse_synced_lyrics(synced_lyrics)
    if not lyrics_lines:
        return transcribed_words

    new_words = []

    for i, line in enumerate(lyrics_lines):
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
        return transcribed_words

    # Step 3: Identify gap segments and inject words
    matched_lyrics = {a[0] for a in alignment}
    new_words = []

    # Scan lyrics from the beginning to catch the pre-gap
    i = 0
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
        return transcribed_words

    print(
        f"[LyricsCorrector] Plain-lyrics gap-filled {len(new_words)} words "
        f"(aligned at lyrics position {alignment_start})"
    )

    result = list(transcribed_words) + new_words
    result.sort(key=lambda w: w["start"])
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
    corrected = correct_words_with_lyrics(transcribed, synced, auto_correct_threshold=0.85)

    print("\n=== Correction Results ===")
    for w in corrected:
        if "original_word" in w:
            print(
                f"✅ {w['original_word']} → {w['word']} "
                f"(confidence: {w['correction_confidence']:.2f})"
            )
        else:
            print(f"⏭️  {w['word']} (no correction)")
