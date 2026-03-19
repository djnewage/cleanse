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


class TestCustomWordList:
    """Verify expanded custom_profanity.txt words are detected."""

    def _check(self, word):
        words = [{"word": word, "start": 0.0, "end": 0.5, "confidence": 0.9}]
        result = flag_profanity(words)
        assert result[0]["is_profanity"] is True, f"'{word}' was not detected as profanity"

    def test_mothafucka(self):
        self._check("mothafucka")

    def test_muthafucka(self):
        self._check("muthafucka")

    def test_biatch(self):
        self._check("biatch")

    def test_biotch(self):
        self._check("biotch")

    def test_azz(self):
        self._check("azz")

    def test_mofo(self):
        self._check("mofo")

    def test_nigguh(self):
        self._check("nigguh")

    def test_skank(self):
        self._check("skank")

    def test_thottie(self):
        self._check("thottie")

    def test_dayum(self):
        self._check("dayum")

    def test_shyt(self):
        self._check("shyt")

    def test_effin(self):
        self._check("effin")


class TestCompoundProfanity:
    """Verify adjacent tokens forming compound profanity are both flagged."""

    def _words(self, *texts):
        return [{"word": t, "start": i * 0.5, "end": (i + 1) * 0.5, "confidence": 0.9} for i, t in enumerate(texts)]

    def test_mother_fucker(self):
        result = flag_profanity(self._words("mother", "fucker"))
        assert result[0]["is_profanity"] is True
        assert result[1]["is_profanity"] is True

    def test_mother_fucking(self):
        result = flag_profanity(self._words("mother", "fucking"))
        assert result[0]["is_profanity"] is True
        assert result[1]["is_profanity"] is True

    def test_mother_fucker_with_punctuation(self):
        result = flag_profanity(self._words("mother,", "fucker!"))
        assert result[0]["is_profanity"] is True
        assert result[1]["is_profanity"] is True

    def test_bull_shit(self):
        result = flag_profanity(self._words("bull", "shit"))
        assert result[0]["is_profanity"] is True
        assert result[1]["is_profanity"] is True

    def test_god_damn(self):
        result = flag_profanity(self._words("god", "damn"))
        assert result[0]["is_profanity"] is True
        assert result[1]["is_profanity"] is True

    def test_jack_ass(self):
        result = flag_profanity(self._words("jack", "ass"))
        assert result[0]["is_profanity"] is True
        assert result[1]["is_profanity"] is True

    def test_non_compound_not_flagged(self):
        result = flag_profanity(self._words("mother", "love"))
        assert result[0]["is_profanity"] is False
        assert result[1]["is_profanity"] is False

    def test_compound_in_sentence(self):
        result = flag_profanity(self._words("you", "mother", "fucker", "yeah"))
        assert result[0]["is_profanity"] is False
        assert result[1]["is_profanity"] is True
        assert result[2]["is_profanity"] is True
        assert result[3]["is_profanity"] is False
