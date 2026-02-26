"""Tests for profanity_detector: _normalize_word and flag_profanity."""

from profanity_detector import _normalize_word, flag_profanity


class TestNormalizeWord:
    def test_plain_word(self):
        variations = _normalize_word("shit")
        assert "shit" in variations

    def test_trailing_punctuation(self):
        variations = _normalize_word("fuck!")
        assert "fuck" in variations
        assert "fuck!" in variations

    def test_trailing_apostrophe(self):
        variations = _normalize_word("fuckin'")
        assert "fuckin" in variations

    def test_mixed_case(self):
        variations = _normalize_word("SHIT")
        assert "shit" in variations

    def test_empty_string(self):
        variations = _normalize_word("")
        assert variations == []

    def test_punctuation_only(self):
        variations = _normalize_word("!!!")
        # All variations should be empty after stripping, so filtered out
        assert all(v for v in variations)  # no empty strings


class TestFlagProfanity:
    def test_marks_profane_word(self):
        words = [{"word": "shit", "start": 0.0, "end": 0.5, "confidence": 0.9}]
        result = flag_profanity(words)
        assert result[0]["is_profanity"] is True

    def test_passes_clean_word(self):
        words = [{"word": "hello", "start": 0.0, "end": 0.5, "confidence": 0.9}]
        result = flag_profanity(words)
        assert result[0]["is_profanity"] is False

    def test_preserves_original_fields(self):
        words = [{"word": "hello", "start": 1.5, "end": 2.0, "confidence": 0.85}]
        result = flag_profanity(words)
        assert result[0]["start"] == 1.5
        assert result[0]["end"] == 2.0
        assert result[0]["confidence"] == 0.85
        assert result[0]["word"] == "hello"

    def test_empty_list(self):
        assert flag_profanity([]) == []

    def test_trailing_punctuation_detected(self):
        words = [{"word": "shit!", "start": 0.0, "end": 0.5, "confidence": 0.9}]
        result = flag_profanity(words)
        assert result[0]["is_profanity"] is True
