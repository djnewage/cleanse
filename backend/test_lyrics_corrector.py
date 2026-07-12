"""Tests for lyrics_corrector: word similarity, correction decisions, and gap-filling."""

# Heavy deps are stubbed in conftest.py.
# tinytag and requests need stubbing (imported by lyrics_fetcher at module level).
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("tinytag", MagicMock())
sys.modules.setdefault("requests", MagicMock())

from lyrics_corrector import (  # noqa: E402
    _compute_word_similarity,
    _line_corroborated,
    _should_correct_word,
    correct_words_with_lyrics,
    fill_gaps_with_lyrics,
    extract_profanity_vocab,
    find_lyrics_profanity,
    flag_with_profanity_vocab,
    normalize_word_timeline,
)


class TestComputeWordSimilarity:
    def test_identical_words(self):
        assert _compute_word_similarity("hello", "hello") == 1.0

    def test_different_case(self):
        assert _compute_word_similarity("Hello", "hello") == 1.0

    def test_unrelated_words(self):
        assert _compute_word_similarity("cat", "xylophone") < 0.3

    def test_similar_words(self):
        score = _compute_word_similarity("fuckin", "fucking")
        assert score > 0.85

    def test_word_with_punctuation(self):
        score = _compute_word_similarity("shit!", "shit")
        assert score == 1.0


class TestShouldCorrectWord:
    def test_identical_words_never_corrected(self):
        tw = {"word": "hello", "confidence": 0.3}
        assert _should_correct_word(tw, "hello", similarity=1.0, threshold=0.85) is False

    def test_identical_case_insensitive(self):
        tw = {"word": "Hello", "confidence": 0.3}
        assert _should_correct_word(tw, "hello", similarity=1.0, threshold=0.85) is False

    def test_low_conf_good_similarity_corrects(self):
        tw = {"word": "helo", "confidence": 0.3}
        assert _should_correct_word(tw, "hello", similarity=0.7, threshold=0.85) is True

    def test_low_conf_bad_similarity_skips(self):
        tw = {"word": "xyz", "confidence": 0.3}
        assert _should_correct_word(tw, "hello", similarity=0.3, threshold=0.85) is False

    def test_medium_conf_high_similarity_corrects(self):
        tw = {"word": "helo", "confidence": 0.6}
        assert _should_correct_word(tw, "hello", similarity=0.90, threshold=0.85) is True

    def test_medium_conf_low_similarity_skips(self):
        tw = {"word": "xyz", "confidence": 0.6}
        assert _should_correct_word(tw, "hello", similarity=0.7, threshold=0.85) is False

    def test_high_conf_very_high_similarity_corrects(self):
        tw = {"word": "helo", "confidence": 0.9}
        assert _should_correct_word(tw, "hello", similarity=0.92, threshold=0.85) is True

    def test_high_conf_moderate_similarity_skips(self):
        tw = {"word": "helo", "confidence": 0.9}
        assert _should_correct_word(tw, "hello", similarity=0.87, threshold=0.85) is False


class TestProfanityAwareCorrection:
    """Profanity words use lower similarity thresholds for correction."""

    def test_high_conf_profanity_corrects_at_080(self):
        """With profanity lyrics word, 0.80 similarity is enough at high confidence."""
        tw = {"word": "truck", "confidence": 0.9}
        assert _should_correct_word(tw, "fuck", similarity=0.82, threshold=0.85) is True

    def test_high_conf_non_profanity_skips_at_080(self):
        """Non-profanity lyrics word still needs 0.90 at high confidence."""
        tw = {"word": "helo", "confidence": 0.9}
        assert _should_correct_word(tw, "hello", similarity=0.82, threshold=0.85) is False

    def test_medium_conf_profanity_corrects_at_070(self):
        tw = {"word": "witch", "confidence": 0.6}
        assert _should_correct_word(tw, "bitch", similarity=0.72, threshold=0.85) is True

    def test_medium_conf_non_profanity_skips_at_070(self):
        tw = {"word": "xyz", "confidence": 0.6}
        assert _should_correct_word(tw, "hello", similarity=0.72, threshold=0.85) is False

    def test_low_conf_profanity_corrects_at_050(self):
        tw = {"word": "duck", "confidence": 0.3}
        assert _should_correct_word(tw, "fuck", similarity=0.52, threshold=0.85) is True

    def test_low_conf_non_profanity_skips_at_050(self):
        tw = {"word": "xyz", "confidence": 0.3}
        assert _should_correct_word(tw, "hello", similarity=0.52, threshold=0.85) is False


class TestCorrectWordsWithLyrics:
    def test_empty_words_returns_unchanged(self):
        result, score = correct_words_with_lyrics([], "[00:10.00] hello")
        assert result == []
        assert score == 0.0

    def test_empty_lyrics_returns_unchanged(self):
        words = [{"word": "hi", "start": 0, "end": 0.5, "confidence": 0.9}]
        result, score = correct_words_with_lyrics(words, "")
        assert result is words
        assert score == 0.0

    def test_applies_correction(self):
        words = [{"word": "helo", "start": 10.0, "end": 10.3, "confidence": 0.3, "is_profanity": False}]
        synced = "[00:10.00] hello world"
        result, _score = correct_words_with_lyrics(words, synced)
        assert result[0]["word"] == "hello"
        assert result[0]["original_word"] == "helo"
        assert "correction_confidence" in result[0]

    def test_no_correction_when_high_confidence_exact(self):
        words = [{"word": "hello", "start": 10.0, "end": 10.3, "confidence": 0.95, "is_profanity": False}]
        synced = "[00:10.00] hello world"
        result, _score = correct_words_with_lyrics(words, synced)
        assert "original_word" not in result[0]
        assert result[0]["word"] == "hello"


class TestAlignmentScore:
    def test_good_alignment_returns_high_score(self):
        words = [
            {"word": "hello", "start": 10.0, "end": 10.3, "confidence": 0.9, "is_profanity": False},
            {"word": "world", "start": 10.5, "end": 10.8, "confidence": 0.9, "is_profanity": False},
        ]
        synced = "[00:10.00] hello world"
        _, score = correct_words_with_lyrics(words, synced)
        assert score >= 0.5

    def test_no_alignment_returns_low_score(self):
        words = [
            {"word": "xyz", "start": 100.0, "end": 100.3, "confidence": 0.9, "is_profanity": False},
            {"word": "abc", "start": 100.5, "end": 100.8, "confidence": 0.9, "is_profanity": False},
        ]
        synced = "[00:10.00] hello world"
        _, score = correct_words_with_lyrics(words, synced)
        assert score < 0.25


class TestFillGapsWithLyrics:
    def test_empty_inputs(self):
        words = [{"word": "hi", "start": 0, "end": 0.5, "confidence": 0.9}]
        assert fill_gaps_with_lyrics(words, "") is words
        assert fill_gaps_with_lyrics([], "[00:10.00] hello") == []

    def test_injects_uncovered_words(self):
        # Need enough transcribed words to avoid the 2x safety rejection.
        # Lyrics line at 10s should be gap-filled since none of these words cover it.
        words = [
            {"word": "one", "start": 5.0, "end": 5.3, "confidence": 0.9, "is_profanity": False},
            {"word": "two", "start": 5.5, "end": 5.8, "confidence": 0.9, "is_profanity": False},
            {"word": "three", "start": 6.0, "end": 6.3, "confidence": 0.9, "is_profanity": False},
        ]
        synced = "[00:10.00] some new words here"
        result = fill_gaps_with_lyrics(words, synced)
        gap_words = [w for w in result if w.get("detection_source") == "lyrics_gap"]
        assert len(gap_words) > 0
        assert gap_words[0]["confidence"] == 0.4

    def test_skips_covered_line(self):
        words = [
            {"word": "hello", "start": 10.0, "end": 10.3, "confidence": 0.9, "is_profanity": False},
            {"word": "world", "start": 10.5, "end": 10.8, "confidence": 0.9, "is_profanity": False},
        ]
        synced = "[00:10.00] hello world"
        result = fill_gaps_with_lyrics(words, synced)
        gap_words = [w for w in result if w.get("detection_source") == "lyrics_gap"]
        assert len(gap_words) == 0


def assert_karaoke_invariants(words):
    """Karaoke-correctness assertions: sorted, non-overlapping [start, end)
    intervals with positive durations — what the renderer's binary search
    assumes. Shared by the invariant and normalization test classes."""
    for i, w in enumerate(words):
        assert w["start"] <= w["end"], (
            f"word[{i}] {w['word']!r}: start {w['start']} > end {w['end']}"
        )
        assert w["start"] >= 0, f"word[{i}] {w['word']!r} has negative start {w['start']}"

    for i in range(len(words) - 1):
        assert words[i]["start"] <= words[i + 1]["start"], (
            f"words not sorted by start: [{i}] {words[i]['word']!r}@{words[i]['start']} "
            f"> [{i+1}] {words[i+1]['word']!r}@{words[i+1]['start']}"
        )

    # No overlapping [start, end) intervals — would make two words "active"
    # at the same time in the karaoke UI.
    for i in range(len(words) - 1):
        assert words[i]["end"] <= words[i + 1]["start"] + 1e-6, (
            f"overlap: [{i}] {words[i]['word']!r} ends {words[i]['end']} "
            f"after [{i+1}] {words[i+1]['word']!r} starts {words[i+1]['start']}"
        )


class TestKaraokeTimingInvariants:
    """Invariants that must hold for word timestamps to render correctly in karaoke.

    The frontend uses binary search on [start, end) intervals to pick the active
    word. Violating these invariants causes wrong-word highlighting, double-active
    states, or words highlighting before they're sung.
    """

    def _assert_invariants(self, words):
        assert_karaoke_invariants(words)

    def test_gap_fill_preserves_sort_order(self):
        """Gap-filled words merged with transcribed words must remain sorted by start."""
        words = [
            {"word": "intro", "start": 5.0, "end": 5.4, "confidence": 0.9, "is_profanity": False},
            {"word": "later", "start": 30.0, "end": 30.4, "confidence": 0.9, "is_profanity": False},
        ]
        synced = "[00:10.00] gap line one\n[00:20.00] gap line two"
        result = fill_gaps_with_lyrics(words, synced)
        self._assert_invariants(result)

    def test_gap_fill_no_overlap_with_whisper_words(self):
        """When Whisper timestamps and LRC timestamps are close, the merged
        list should not produce two words active at the same moment."""
        # Whisper word at 10.5s; LRC line at 10.0s would put gap-fill words
        # starting at 10.0 — overlap risk.
        words = [
            {"word": "shortbreak", "start": 5.0, "end": 5.3, "confidence": 0.9, "is_profanity": False},
            {"word": "uniqueword", "start": 10.5, "end": 10.8, "confidence": 0.9, "is_profanity": False},
        ]
        synced = "[00:10.00] alpha beta gamma delta"
        result = fill_gaps_with_lyrics(words, synced)
        self._assert_invariants(result)

    def test_gap_words_within_line_window(self):
        """Every lyrics_gap word's start should fall within its source line's
        time window — never before line.time, never after the next line."""
        synced = "[00:10.00] alpha beta\n[00:15.00] gamma delta\n[00:25.00] epsilon"
        # Empty transcription forces all lines to gap-fill
        words = [
            {"word": "decoy", "start": 1.0, "end": 1.3, "confidence": 0.9, "is_profanity": False},
        ]
        result = fill_gaps_with_lyrics(words, synced)
        gap = [w for w in result if w.get("detection_source") == "lyrics_gap"]
        # Lines: 10s, 15s, 25s
        line_times = [10.0, 15.0, 25.0]
        for gw in gap:
            owner = max((lt for lt in line_times if lt <= gw["start"] + 1e-6), default=None)
            assert owner is not None, (
                f"gap word {gw['word']!r} at {gw['start']} starts before any LRC line"
            )
            # Find the next line after the owner
            next_line = next((lt for lt in line_times if lt > owner), float("inf"))
            assert gw["start"] < next_line, (
                f"gap word {gw['word']!r} at {gw['start']} starts past next line @{next_line}"
            )

    def test_gap_word_durations_are_positive(self):
        """A 'word' with start == end would never be active in [start, end) lookup."""
        synced = "[00:10.00] alpha beta gamma"
        words = [{"word": "x", "start": 1.0, "end": 1.3, "confidence": 0.9, "is_profanity": False}]
        result = fill_gaps_with_lyrics(words, synced)
        for w in result:
            assert w["end"] > w["start"], (
                f"word {w['word']!r} has zero/negative duration ({w['start']}, {w['end']})"
            )


class TestNormalizeWordTimeline:
    """normalize_word_timeline is the last pipeline step and must guarantee the
    karaoke invariants regardless of what the injectors produced."""

    def _w(self, word, start, end, source=None, profanity=False, **extra):
        d = {"word": word, "start": start, "end": end, "confidence": 0.9,
             "is_profanity": profanity, **extra}
        if source:
            d["detection_source"] = source
        return d

    def test_empty_input(self):
        assert normalize_word_timeline([]) == []

    def test_sorts_by_start(self):
        words = [self._w("b", 2.0, 2.4), self._w("a", 1.0, 1.4)]
        result = normalize_word_timeline(words)
        assert [w["word"] for w in result] == ["a", "b"]
        assert_karaoke_invariants(result)

    def test_clamps_negative_start_and_audio_duration(self):
        words = [self._w("a", -0.5, 0.4), self._w("b", 179.0, 999.0)]
        result = normalize_word_timeline(words, audio_duration=180.0)
        assert result[0]["start"] == 0.0
        assert result[1]["end"] == 180.0
        assert_karaoke_invariants(result)

    def test_repairs_inverted_interval(self):
        words = [self._w("a", 5.0, 4.0)]
        result = normalize_word_timeline(words)
        assert result[0]["end"] > result[0]["start"]

    def test_synthetic_yields_to_real(self):
        real = self._w("real", 10.0, 10.5)
        synth = self._w("gap", 9.8, 10.2, source="lyrics_gap")
        result = normalize_word_timeline([real, synth])
        assert_karaoke_invariants(result)
        kept_real = next(w for w in result if w["word"] == "real")
        assert (kept_real["start"], kept_real["end"]) == (10.0, 10.5)

    def test_real_profanity_keeps_interval_over_real_clean(self):
        # dual-pass merge timing rewrites can overlap real neighbors;
        # never shrink a mute.
        prof = self._w("fuck", 10.0, 10.6, profanity=True)
        clean = self._w("yeah", 10.4, 10.9)
        result = normalize_word_timeline([prof, clean])
        assert_karaoke_invariants(result)
        kept = next(w for w in result if w["word"] == "fuck")
        assert (kept["start"], kept["end"]) == (10.0, 10.6)

    def test_nested_synthetic_profanity_transfers_flag(self):
        real = self._w("ducking", 10.0, 10.6)
        synth = self._w("fucking", 10.1, 10.5, source="lyrics", profanity=True)
        result = normalize_word_timeline([real, synth])
        assert_karaoke_invariants(result)
        assert len(result) == 1
        assert result[0]["word"] == "ducking"
        assert result[0]["is_profanity"] is True
        assert result[0]["detection_source"] == "lyrics"

    def test_dissimilar_synthetic_profanity_dropped_not_transferred(self):
        # Gap-fill even-spacing can land a profanity on an unrelated real word
        # ("niggas" over "asked"). That's positional guesswork, not a
        # mishearing — muting the real word would hole out clean vocals.
        real = self._w("asked", 10.0, 10.6)
        synth = self._w("niggas", 10.1, 10.5, source="lyrics_gap", profanity=True)
        result = normalize_word_timeline([real, synth])
        assert len(result) == 1
        assert result[0]["word"] == "asked"
        assert result[0]["is_profanity"] is False

    def test_nested_clean_synthetic_dropped(self):
        real = self._w("hello", 10.0, 10.6)
        synth = self._w("filler", 10.1, 10.5, source="lyrics_gap")
        result = normalize_word_timeline([real, synth])
        assert [w["word"] for w in result] == ["hello"]

    def test_partial_overlap_trims_not_drops(self):
        real = self._w("real", 10.0, 10.5)
        synth = self._w("gap", 10.3, 11.0, source="lyrics_gap")
        result = normalize_word_timeline([real, synth])
        assert_karaoke_invariants(result)
        assert len(result) == 2
        kept_synth = next(w for w in result if w["word"] == "gap")
        assert kept_synth["start"] == 10.5

    def test_idempotent(self):
        words = [
            self._w("a", 1.0, 1.5),
            self._w("b", 1.3, 1.8, source="lyrics_gap"),
            self._w("c", 1.7, 2.2, profanity=True),
        ]
        once = normalize_word_timeline(words)
        twice = normalize_word_timeline(once)
        assert once == twice
        assert_karaoke_invariants(twice)

    def test_burst_of_overlapping_synthetics(self):
        # gap-fill can smear a whole line across overlapping estimates
        words = [self._w(f"w{i}", 10.0 + i * 0.1, 10.0 + i * 0.1 + 0.35, source="lyrics_gap")
                 for i in range(10)]
        words.append(self._w("real", 10.5, 10.9))
        result = normalize_word_timeline(words)
        assert_karaoke_invariants(result)
        kept_real = next(w for w in result if w["word"] == "real")
        assert (kept_real["start"], kept_real["end"]) == (10.5, 10.9)


class TestProfanityVocab:
    def test_extracts_profanity_words(self):
        vocab = extract_profanity_vocab("I say fuck and shit every day")
        assert "fuck" in vocab
        assert "shit" in vocab
        assert "say" not in vocab
        assert "every" not in vocab

    def test_clean_lyrics_returns_empty(self):
        vocab = extract_profanity_vocab("hello world good morning")
        assert len(vocab) == 0

    def test_empty_input(self):
        assert extract_profanity_vocab("") == set()

    def test_flag_unflagged_word(self):
        words = [
            {"word": "fuck", "start": 0, "end": 0.5, "confidence": 0.9, "is_profanity": False},
        ]
        result = flag_with_profanity_vocab(words, {"fuck"})
        assert result[0]["is_profanity"] is True

    def test_does_not_double_flag(self):
        words = [
            {"word": "fuck", "start": 0, "end": 0.5, "confidence": 0.9, "is_profanity": True},
        ]
        result = flag_with_profanity_vocab(words, {"fuck"})
        assert result[0]["is_profanity"] is True

    def test_fuzzy_match_flags(self):
        words = [
            {"word": "fuckin", "start": 0, "end": 0.5, "confidence": 0.9, "is_profanity": False},
        ]
        result = flag_with_profanity_vocab(words, {"fucking"})
        assert result[0]["is_profanity"] is True

    def test_dissimilar_word_not_flagged(self):
        words = [
            {"word": "hello", "start": 0, "end": 0.5, "confidence": 0.9, "is_profanity": False},
        ]
        result = flag_with_profanity_vocab(words, {"fuck"})
        assert result[0]["is_profanity"] is False

    def test_empty_vocab_returns_unchanged(self):
        words = [
            {"word": "hello", "start": 0, "end": 0.5, "confidence": 0.9, "is_profanity": False},
        ]
        result = flag_with_profanity_vocab(words, set())
        assert result is words

    def test_extracts_censored_spellings_as_real_word(self):
        # Genius lyrics are often asterisk-censored; the vocab must resolve
        # them to real roots so fuzzy matching downstream has something to hit.
        vocab = extract_profanity_vocab("I'm f***ing done with this s*** and them b*tches")
        assert "fucking" in vocab
        assert "shit" in vocab
        assert "bitches" in vocab

    def test_dash_separator_lines_not_extracted(self):
        assert extract_profanity_vocab("verse one\n----\nverse two") == set()


class TestVocabLyricsPresenceGuard:
    """A transcribed word that appears verbatim in the lyrics is the lyrics'
    own clean word, never a soft-substitute of the profanity — 'witches' in a
    song containing both 'witches' and 'bitches' must not be muted."""

    def _word(self, text):
        return [{"word": text, "start": 1.0, "end": 1.4, "confidence": 0.9, "is_profanity": False}]

    def test_word_in_lyrics_not_flagged(self):
        for word, vocab, lyrics in [
            ("witches", {"bitches"}, "the witches brew and the bitches too"),
            ("hitting", {"shitting"}, "hitting hard, no shitting around"),
            ("trucking", {"fucking"}, "keep on trucking, keep on fucking"),
            ("brushes", {"bushes"}, "brushes past the bushes"),
        ]:
            result = flag_with_profanity_vocab(self._word(word), vocab, lyrics_text=lyrics)
            assert result[0]["is_profanity"] is False, f"'{word}' present in lyrics was flagged"

    def test_word_absent_from_lyrics_still_flagged(self):
        # Soft-substitute recall preserved: Whisper heard "ducking"/"witches"
        # but the lyrics only contain the profanity — that's a mishearing.
        for word, vocab, lyrics in [
            ("ducking", {"fucking"}, "keep on fucking around"),
            ("witches", {"bitches"}, "and the bitches too"),
        ]:
            result = flag_with_profanity_vocab(self._word(word), vocab, lyrics_text=lyrics)
            assert result[0]["is_profanity"] is True, f"soft-sub '{word}' was NOT flagged"

    def test_no_lyrics_text_keeps_old_behavior(self):
        result = flag_with_profanity_vocab(self._word("fuckin"), {"fucking"})
        assert result[0]["is_profanity"] is True


class TestLineCorroboration:
    def _tw(self, word, start):
        return {"word": word, "start": start, "end": start + 0.3, "confidence": 0.9,
                "is_profanity": False}

    def test_matching_line_corroborated(self):
        transcribed = [self._tw("oh", 10.1), self._tw("shit", 10.6), self._tw("man", 11.0)]
        assert _line_corroborated("oh shit man", 10.0, 15.0, transcribed) is True

    def test_offset_line_not_corroborated(self):
        # Wrong-version lyrics: line claims 10s but nothing matching is sung there
        transcribed = [self._tw("completely", 10.1), self._tw("different", 10.6),
                       self._tw("words", 11.0)]
        assert _line_corroborated("oh shit man", 10.0, 15.0, transcribed) is False

    def test_empty_region_not_corroborated(self):
        transcribed = [self._tw("oh", 60.0)]
        assert _line_corroborated("oh shit man", 10.0, 15.0, transcribed) is False

    def test_synthetic_words_dont_corroborate(self):
        # gap-filled words come FROM the lyrics — they must not vouch for them
        transcribed = [
            {**self._tw("oh", 10.1), "detection_source": "lyrics_gap"},
            {**self._tw("shit", 10.6), "detection_source": "lyrics_gap"},
            {**self._tw("man", 11.0), "detection_source": "lyrics_gap"},
        ]
        assert _line_corroborated("oh shit man", 10.0, 15.0, transcribed) is False


class TestFindLyricsProfanity:
    def test_detects_new_profanity(self):
        synced = "[00:10.00] oh shit man"
        transcribed = [
            {"word": "oh", "start": 10.0, "end": 10.3, "confidence": 0.9, "is_profanity": False},
            {"word": "man", "start": 11.0, "end": 11.3, "confidence": 0.9, "is_profanity": False},
        ]
        result = find_lyrics_profanity(synced, transcribed)
        assert len(result) >= 1
        profane_words = [d["word"] for d in result]
        assert "shit" in profane_words
        assert result[0]["detection_source"] == "lyrics"
        assert result[0]["is_profanity"] is True

    def test_no_duplicate_when_already_detected(self):
        synced = "[00:10.00] oh shit"
        # "oh shit" -- 2 words, line duration ~5s, word_duration ~2.5s
        # "shit" is word index 1 -> estimated_start = 10.0 + 1*2.5 = 12.5
        transcribed = [
            {"word": "shit", "start": 12.5, "end": 12.8, "confidence": 0.9, "is_profanity": True},
        ]
        result = find_lyrics_profanity(synced, transcribed, overlap_threshold=0.75)
        # abs(12.5 - 12.5) = 0.0 < 0.75 -> duplicate, should not be added
        assert len(result) == 0

    def test_empty_synced_lyrics(self):
        assert find_lyrics_profanity("", []) == []

    def test_no_profanity_in_lyrics(self):
        synced = "[00:10.00] hello beautiful world"
        result = find_lyrics_profanity(synced, [])
        assert result == []

    def test_whitelisted_words_not_injected(self):
        # Regression: raw contains_profanity bypassed WHITELIST, injecting
        # false mutes for everyday words in clean lyric lines.
        synced = "[00:10.00] oh my god I feel the hell of it\n[00:15.00] she got fat pockets and panty lines"
        result = find_lyrics_profanity(synced, [
            {"word": "oh", "start": 10.0, "end": 10.3, "confidence": 0.9, "is_profanity": False},
        ])
        assert result == [], f"whitelisted words injected as profanity: {[d['word'] for d in result]}"

    def test_stylized_spelling_injected(self):
        # Regression: the injector used only the exact tier, missing elongated
        # spellings that scan_token's de-elongation tier catches. Line must be
        # corroborated by the transcript for injection to happen.
        synced = "[00:10.00] fuuuck this whole thing"
        result = find_lyrics_profanity(synced, [
            {"word": "this", "start": 10.3, "end": 10.5, "confidence": 0.9, "is_profanity": False},
            {"word": "whole", "start": 10.6, "end": 10.9, "confidence": 0.9, "is_profanity": False},
        ])
        assert any(d["word"] == "fuuuck" for d in result)

    def test_uncorroborated_line_skipped(self):
        # Offset/wrong-version lyrics: the line has profanity, but nothing
        # matching that line is sung at its timestamp — no injection.
        synced = "[00:10.00] fuck this whole thing"
        result = find_lyrics_profanity(synced, [
            {"word": "totally", "start": 10.2, "end": 10.5, "confidence": 0.9, "is_profanity": False},
            {"word": "unrelated", "start": 10.6, "end": 10.9, "confidence": 0.9, "is_profanity": False},
            {"word": "singing", "start": 11.0, "end": 11.3, "confidence": 0.9, "is_profanity": False},
        ])
        assert result == []


class TestAlignLyricsToTranscript:
    """Global lyrics<->transcript alignment (replaces the fragile single
    start-anchor scheme)."""

    def _words(self, texts, t0=10.0):
        return [{"word": t, "start": t0 + i * 0.5, "end": t0 + i * 0.5 + 0.4,
                 "confidence": 0.9, "is_profanity": False} for i, t in enumerate(texts)]

    VERSE = ("walking down the street tonight with nothing left to lose "
             "counting every heartbeat like a message in the news").split()

    def test_survives_dj_intro_prefix(self):
        # The killer case: transcript opens with edit-intro chatter that appears
        # nowhere in the lyrics; the old anchor probe of the first 5 words died.
        from lyrics_corrector import _align_lyrics_to_transcript
        intro = "ayo this goes out to all my listeners alabazian alabazian".split()
        words = self._words(intro + self.VERSE)
        pairs = _align_lyrics_to_transcript(words, list(self.VERSE))
        assert len(pairs) >= len(self.VERSE) - 2
        # every pair maps the right transcript region (post-intro)
        assert all(ti >= len(intro) for _, ti in pairs)

    def test_unheard_lyric_block_is_skipped_not_fatal(self):
        # Whisper misses the chorus entirely; the verses around it still align.
        from lyrics_corrector import _align_lyrics_to_transcript
        chorus = "suck my dick suck my dick suck my dick".split()
        lyrics = list(self.VERSE) + chorus + list(self.VERSE)
        words = self._words(list(self.VERSE) + list(self.VERSE))
        pairs = _align_lyrics_to_transcript(words, lyrics)
        matched_lyrics = {li for li, _ in pairs}
        # chorus tokens unmatched, both verses covered
        chorus_range = set(range(len(self.VERSE), len(self.VERSE) + len(chorus)))
        assert not (matched_lyrics & chorus_range)
        assert len(matched_lyrics) >= 1.5 * len(self.VERSE)

    def test_monotonic(self):
        from lyrics_corrector import _align_lyrics_to_transcript
        words = self._words(list(self.VERSE) * 2)
        pairs = _align_lyrics_to_transcript(words, list(self.VERSE) * 2)
        for (l1, t1), (l2, t2) in zip(pairs, pairs[1:]):
            assert l2 > l1 and t2 > t1

    def test_wrong_song_rejected(self):
        # Same-title different song: only coincidental function words align.
        from lyrics_corrector import _align_lyrics_to_transcript
        wrong = ("you don't like the clothes i wear i shave my head or grow my hair "
                 "what makes you look over here what are you queer "
                 "skins and bangers joining fight as one those who persecute "
                 "battle til they have won tired of being pressured").split()
        rap = ("and if you hate that i don't spit out money and all the stuff i get "
               "and if you're angry that your girl wanna hunt me because she loves my music "
               "and if what i'm saying offends you once i'm done this track "
               "junkie and y'all done bumped my tape").split()
        pairs = _align_lyrics_to_transcript(self._words(rap), wrong)
        assert pairs == [], f"wrong-song lyrics aligned: {len(pairs)} pairs"


class TestLyricsMatchTranscript:
    def test_matching_lyrics_pass(self):
        from lyrics_corrector import lyrics_match_transcript
        verse = TestAlignLyricsToTranscript.VERSE
        words = [{"word": t, "start": i * 0.5, "end": i * 0.5 + 0.4,
                  "confidence": 0.9, "is_profanity": False} for i, t in enumerate(verse * 2)]
        assert lyrics_match_transcript(words, " ".join(verse * 2)) is True

    def test_empty_inputs_fail(self):
        from lyrics_corrector import lyrics_match_transcript
        assert lyrics_match_transcript([], "some lyrics here") is False
        assert lyrics_match_transcript([{"word": "hi", "start": 0, "end": 1}], "") is False
