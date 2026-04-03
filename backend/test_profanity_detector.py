"""Tests for profanity_detector: _normalize_word and flag_profanity."""

from profanity_detector import _normalize_word, flag_profanity, COMPOUND_PROFANITY_ES


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


class TestSpanishProfanity:
    """Verify Spanish profanity words are detected."""

    def _check(self, word):
        words = [{"word": word, "start": 0.0, "end": 0.5, "confidence": 0.9}]
        result = flag_profanity(words)
        assert result[0]["is_profanity"] is True, f"'{word}' was not detected as profanity"

    def test_puta(self):
        self._check("puta")

    def test_mierda(self):
        self._check("mierda")

    def test_chingada(self):
        self._check("chingada")

    def test_pendejo(self):
        self._check("pendejo")

    def test_cabron(self):
        self._check("cabron")

    def test_verga(self):
        self._check("verga")

    def test_pinche(self):
        self._check("pinche")

    def test_hijueputa(self):
        self._check("hijueputa")

    def test_carajo(self):
        self._check("carajo")

    def test_joder(self):
        self._check("joder")


class TestAccentNormalization:
    """Verify accented characters are normalized for detection."""

    def test_accent_stripped_in_variations(self):
        variations = _normalize_word("cabrón")
        assert "cabron" in variations

    def test_n_tilde_stripped(self):
        variations = _normalize_word("coño")
        assert "cono" in variations

    def test_cabron_with_accent_detected(self):
        words = [{"word": "cabrón", "start": 0.0, "end": 0.5, "confidence": 0.9}]
        result = flag_profanity(words)
        assert result[0]["is_profanity"] is True


class TestSpanishCompoundProfanity:
    """Verify Spanish compound profanity detection."""

    def _words(self, *texts):
        return [{"word": t, "start": i * 0.5, "end": (i + 1) * 0.5, "confidence": 0.9} for i, t in enumerate(texts)]

    def test_hijo_puta(self):
        result = flag_profanity(self._words("hijo", "puta"), language="es")
        assert result[0]["is_profanity"] is True
        assert result[1]["is_profanity"] is True

    def test_hija_puta(self):
        result = flag_profanity(self._words("hija", "puta"), language="es")
        assert result[0]["is_profanity"] is True
        assert result[1]["is_profanity"] is True

    def test_spanish_compound_not_flagged_without_language(self):
        result = flag_profanity(self._words("hijo", "puta"))
        # "puta" is still flagged as a standalone word, but "hijo" should not be
        assert result[0]["is_profanity"] is False
        assert result[1]["is_profanity"] is True


class TestWhitelist:
    """Verify whitelisted words are NOT flagged as profanity."""

    def _check_not_profane(self, word):
        words = [{"word": word, "start": 0.0, "end": 0.5, "confidence": 0.9}]
        result = flag_profanity(words)
        assert result[0]["is_profanity"] is False, f"'{word}' should NOT be flagged (whitelisted)"

    def test_dame_not_flagged(self):
        self._check_not_profane("Dame")

    def test_dame_lowercase_not_flagged(self):
        self._check_not_profane("dame")

    def test_woody_not_flagged(self):
        self._check_not_profane("Woody")

    def test_dummy_not_flagged(self):
        self._check_not_profane("dummy")

    def test_damn_still_flagged(self):
        """Ensure actual profanity near whitelist words still works."""
        words = [{"word": "damn", "start": 0.0, "end": 0.5, "confidence": 0.9}]
        result = flag_profanity(words)
        assert result[0]["is_profanity"] is True


class TestSlangWords:
    """Verify newly added slang words are detected."""

    def _check(self, word):
        words = [{"word": word, "start": 0.0, "end": 0.5, "confidence": 0.9}]
        result = flag_profanity(words)
        assert result[0]["is_profanity"] is True, f"'{word}' was not detected as profanity"

    def test_coochie(self):
        self._check("coochie")

    def test_puchi(self):
        self._check("puchi")
