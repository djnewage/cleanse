"""Tests for lyrics_corrector: word similarity, correction decisions, and gap-filling."""

# Heavy deps are stubbed in conftest.py.
# tinytag and requests need stubbing (imported by lyrics_fetcher at module level).
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("tinytag", MagicMock())
sys.modules.setdefault("requests", MagicMock())

from lyrics_corrector import (  # noqa: E402
    _compute_word_similarity,
    _should_correct_word,
    correct_words_with_lyrics,
    fill_gaps_with_lyrics,
    extract_profanity_vocab,
    flag_with_profanity_vocab,
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
