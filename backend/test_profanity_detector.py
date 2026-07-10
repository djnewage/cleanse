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


class TestWildcardCensoredTier:
    """Censored forms ('*'/'-' as single-char wildcards) must be caught: Whisper
    emits them (censored-subtitle training data), and Genius lyrics passed as
    initial_prompt are often asterisk-censored. The hyphenated-word NEGATIVES
    table is the FP spec — exact-length matching keeps ordinary hyphenated
    words from aligning with any target."""

    # Multi-censor-char forms the exact tier's leet map can't handle (it only
    # substitutes one char per position). f*ck/sh*t/b*tch are exact-tier.
    POSITIVES = [
        "f***", "s***", "n***a", "n****", "f***ing", "f**king", "f***in'",
        "motherf***er", "f---", "a**", "****", "d**n", "b****", "b*****s",
    ]

    NEGATIVES = [
        "t-shirt", "x-ray", "e-mail", "co-op", "hip-hop", "so-called",
        "twenty-two", "check-in", "mother-in-law", "uh-huh", "na-na", "la-la",
        "one-two", "k-pop", "v-neck", "u-turn", "drive-in", "pick-up", "re-up",
        "a-ha", "well-known", "cha-cha", "f-150", "he-ll",
        "----", "--", "-",  # em-dash separators must not read as wildcards
    ]

    def test_positives_caught(self):
        from profanity_detector import scan_token
        misses = [w for w in self.POSITIVES if scan_token(w) is None]
        assert not misses, f"censored forms NOT flagged: {misses}"

    def test_no_false_positives(self):
        from profanity_detector import scan_token
        fps = [w for w in self.NEGATIVES if scan_token(w) is not None]
        assert not fps, f"FALSE POSITIVES (hyphenated/innocent tokens flagged): {fps}"

    def test_resolves_to_real_word(self):
        from profanity_detector import scan_token
        assert scan_token("f***ing") == {"matched": "fucking", "match_type": "wildcard"}
        assert scan_token("n***a") == {"matched": "nigga", "match_type": "wildcard"}

    def test_flag_profanity_path(self):
        result = flag_profanity([
            {"word": "f***", "start": 0.0, "end": 0.5, "confidence": 0.9},
            {"word": "hello", "start": 0.5, "end": 1.0, "confidence": 0.9},
        ])
        assert result[0]["is_profanity"] is True
        assert result[1]["is_profanity"] is False


class TestJoinedCompoundProfanity:
    """Adjacent pairs whose JOINED form is in the exact list ("blow"+"job" ->
    "blowjob") are flagged even though neither half is profane alone."""

    def _words(self, *texts):
        return [{"word": t, "start": i * 0.5, "end": (i + 1) * 0.5, "confidence": 0.9} for i, t in enumerate(texts)]

    def _check_both(self, w1, w2):
        result = flag_profanity(self._words(w1, w2))
        assert result[0]["is_profanity"] is True, f"'{w1} {w2}': first half not flagged"
        assert result[1]["is_profanity"] is True, f"'{w1} {w2}': second half not flagged"

    def test_blow_job(self):
        self._check_both("blow", "job")

    def test_hand_job(self):
        self._check_both("hand", "job")

    def test_rim_job(self):
        self._check_both("rim", "job")

    def test_deep_throat(self):
        self._check_both("deep", "throat")

    def test_cum_shot(self):
        self._check_both("cum", "shot")

    def test_jerk_off(self):
        self._check_both("jerk", "off")

    def test_innocent_joins_not_flagged(self):
        # Negatives table: everyday pairs must never assemble into a hit.
        for w1, w2 in [
            ("class", "act"), ("grass", "hopper"), ("pass", "word"),
            ("hand", "some"), ("kick", "off"), ("mass", "ive"),
            ("but", "ton"), ("back", "side"), ("count", "down"),
        ]:
            result = flag_profanity(self._words(w1, w2))
            assert result[0]["is_profanity"] is False, f"FP: '{w1} {w2}' flagged {w1}"
            assert result[1]["is_profanity"] is False, f"FP: '{w1} {w2}' flagged {w2}"

    def test_short_tokens_cannot_assemble(self):
        # min-length guard: "s"+"hit" must not join into "shit"
        result = flag_profanity(self._words("s", "hit"))
        assert result[0]["is_profanity"] is False
        assert result[1]["is_profanity"] is False


class TestGappedCompoundProfanity:
    """Compound halves separated by one filler word ("hijo DE puta") flag all
    three tokens so the mute is contiguous."""

    def _words(self, *texts):
        return [{"word": t, "start": i * 0.5, "end": (i + 1) * 0.5, "confidence": 0.9} for i, t in enumerate(texts)]

    def test_hijo_de_puta(self):
        result = flag_profanity(self._words("hijo", "de", "puta"), language="es")
        assert [w["is_profanity"] for w in result] == [True, True, True]

    def test_cara_de_verga(self):
        result = flag_profanity(self._words("cara", "de", "verga"), language="es")
        assert [w["is_profanity"] for w in result] == [True, True, True]

    def test_innocent_gapped_phrase_not_flagged(self):
        result = flag_profanity(self._words("hijo", "de", "dios"), language="es")
        assert [w["is_profanity"] for w in result] == [False, False, False]

    def test_gap_requires_filler_word(self):
        # Non-filler middle word must not bridge the compound
        result = flag_profanity(self._words("hijo", "grande", "puta"), language="es")
        assert result[0]["is_profanity"] is False
        assert result[1]["is_profanity"] is False


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


class TestStyleRecallLayer:
    """Fuzzy/de-elongation recall layer (scan_token). The NEGATIVES table is the
    spec for the gates — zero false positives is the bar. Metaphone was rejected
    because its vowel-dropping collides with common words (shot/beach/count)."""

    from profanity_detector import scan_token

    # Stylized / elongated spellings that SHOULD be caught beyond the exact list.
    # fucc/fucck/bytch/shiet score under the fuzzy ratio-90 floor, so they live
    # in custom_profanity.txt (exact tier) instead of loosening the threshold.
    POSITIVES = ["biiitch", "pusssy", "fuuuck", "shiiit", "niggaaa", "fuuck", "shiit",
                 "biitch", "biatchhh", "fucc", "fucck", "bytch", "shiet"]

    # Common words that MUST NEVER be flagged. Two collision families:
    # (a) vowel-drop / single-edit neighbors of profanity roots (shot, count, shirt);
    # (b) natural doubled-letter words that de-elongation collapses (good, moon, grass).
    NEGATIVES = [
        # (a) edit-distance / vowel-drop neighbors
        "shot", "sheet", "shoot", "shoots", "beach", "batch", "fake", "folk",
        "cant", "can't", "shirt", "glass", "count", "ship", "class", "hash",
        "peach", "fact", "sheep", "duck", "sick", "sit", "chic", "clock", "rich",
        "which", "beech", "snitch", "ditch", "pitch", "witch", "assassin",
        "assess", "grass", "bass", "pass", "cocktail", "title", "shut", "chat",
        # (b) doubled-letter words exercised by the runs-of-2 de-elongation
        "good", "moon", "soon", "balloon", "coffee", "success", "cool", "look",
        "book", "feel", "see", "off", "egg", "ball", "small", "still", "happy",
        "butter", "dinner", "mirror", "yellow", "cookie", "raccoon", "cocoon",
    ]

    def _flagged(self, word):
        from profanity_detector import flag_profanity
        w = [{"word": word, "start": 0.0, "end": 0.5, "confidence": 0.9}]
        return flag_profanity(w)[0]["is_profanity"]

    def test_positives_caught(self):
        for w in self.POSITIVES:
            assert self._flagged(w) is True, f"stylized '{w}' was NOT flagged"

    def test_no_false_positives(self):
        fps = [w for w in self.NEGATIVES if self._flagged(w)]
        assert not fps, f"FALSE POSITIVES (clean words flagged as profanity): {fps}"

    def test_deelongation_routes_through_exact(self):
        from profanity_detector import scan_token
        assert scan_token("fuuuck")["match_type"] == "deelongate"
        assert scan_token("biiitch")["match_type"] == "deelongate"

    def test_whitelist_still_wins(self):
        # whitelisted words never match, even with elongation
        from profanity_detector import scan_token
        assert scan_token("god") is None
        assert scan_token("hellll") is None  # -> hell (whitelisted)
