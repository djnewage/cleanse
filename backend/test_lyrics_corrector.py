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


class TestCorrectWordsWithLyrics:
    def test_empty_words_returns_unchanged(self):
        assert correct_words_with_lyrics([], "[00:10.00] hello") == []

    def test_empty_lyrics_returns_unchanged(self):
        words = [{"word": "hi", "start": 0, "end": 0.5, "confidence": 0.9}]
        assert correct_words_with_lyrics(words, "") is words

    def test_applies_correction(self):
        words = [{"word": "helo", "start": 10.0, "end": 10.3, "confidence": 0.3, "is_profanity": False}]
        synced = "[00:10.00] hello world"
        result = correct_words_with_lyrics(words, synced)
        assert result[0]["word"] == "hello"
        assert result[0]["original_word"] == "helo"
        assert "correction_confidence" in result[0]

    def test_no_correction_when_high_confidence_exact(self):
        words = [{"word": "hello", "start": 10.0, "end": 10.3, "confidence": 0.95, "is_profanity": False}]
        synced = "[00:10.00] hello world"
        result = correct_words_with_lyrics(words, synced)
        assert "original_word" not in result[0]
        assert result[0]["word"] == "hello"


class TestFillGapsWithLyrics:
    def test_empty_inputs(self):
        words = [{"word": "hi", "start": 0, "end": 0.5, "confidence": 0.9}]
        assert fill_gaps_with_lyrics(words, "") is words
        assert fill_gaps_with_lyrics([], "[00:10.00] hello") == []

    def test_injects_uncovered_words(self):
        words = [{"word": "end", "start": 50.0, "end": 50.3, "confidence": 0.9, "is_profanity": False}]
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
