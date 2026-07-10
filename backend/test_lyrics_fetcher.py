"""Tests for lyrics_fetcher: _extract_first_artist, parse_synced_lyrics, find_lyrics_profanity."""

# Heavy deps are stubbed in conftest.py.
# tinytag and requests need stubbing here (lightweight but not always installed).
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("tinytag", MagicMock())
sys.modules.setdefault("requests", MagicMock())

from lyrics_fetcher import _extract_first_artist, _clean_search_title, parse_synced_lyrics  # noqa: E402


class TestExtractFirstArtist:
    def test_comma_separated(self):
        assert _extract_first_artist("Carti, Future, & Travis") == "Carti"

    def test_ampersand(self):
        assert _extract_first_artist("Playboi Carti & Future") == "Playboi Carti"

    def test_feat_dot(self):
        assert _extract_first_artist("Drake feat. Lil Baby") == "Drake"

    def test_ft_dot(self):
        assert _extract_first_artist("Drake ft. Lil Baby") == "Drake"

    def test_paren_feat(self):
        assert _extract_first_artist("Artist (feat. Other)") == "Artist"

    def test_solo_artist(self):
        assert _extract_first_artist("Drake") == "Drake"

    def test_featuring_keyword(self):
        assert _extract_first_artist("Artist featuring Other") == "Artist"


class TestParseSyncedLyrics:
    def test_basic_line(self):
        result = parse_synced_lyrics("[01:23.45] Hello world")
        assert len(result) == 1
        assert abs(result[0]["time"] - 83.45) < 0.01
        assert result[0]["text"] == "Hello world"

    def test_zero_timestamp(self):
        result = parse_synced_lyrics("[00:05.00] First line")
        assert len(result) == 1
        assert abs(result[0]["time"] - 5.0) < 0.01

    def test_empty_text_skipped(self):
        result = parse_synced_lyrics("[01:00.00]   ")
        assert result == []

    def test_empty_input(self):
        result = parse_synced_lyrics("")
        assert result == []

    def test_multiple_lines(self):
        lyrics = "[00:10.00] Line one\n[00:15.00] Line two\n[00:20.00] Line three"
        result = parse_synced_lyrics(lyrics)
        assert len(result) == 3
        assert result[0]["text"] == "Line one"
        assert result[2]["text"] == "Line three"

    def test_malformed_line_skipped(self):
        lyrics = "Not a valid line\n[00:05.00] Valid line"
        result = parse_synced_lyrics(lyrics)
        assert len(result) == 1
        assert result[0]["text"] == "Valid line"


class TestCleanSearchTitle:
    def test_simple_remix(self):
        assert _clean_search_title("Song (remix)") == "Song"

    def test_named_remix(self):
        assert _clean_search_title("FWU (Red Sip Remix)") == "FWU"

    def test_dj_edit(self):
        assert _clean_search_title("Song (DJ Snake Edit)") == "Song"

    def test_multi_word_remix(self):
        assert _clean_search_title("FWU (Cheyenne Giles Remix)") == "FWU"

    def test_simple_deluxe(self):
        assert _clean_search_title("Album (Deluxe)") == "Album"

    def test_simple_intro(self):
        assert _clean_search_title("Song (Intro)") == "Song"

    def test_no_suffix(self):
        assert _clean_search_title("Normal Song") == "Normal Song"

    def test_bracket_variant(self):
        assert _clean_search_title("Song [Extended Mix]") == "Song"

    def test_preserves_non_tag_parens(self):
        assert _clean_search_title("Song (feat. Artist)") == "Song (feat. Artist)"


class TestSelectLrclibResult:
    """Duration-verified search-hit selection — a wrong-duration hit is a
    different version of the song whose synced timestamps are all offset."""

    def _entry(self, duration, synced=True, plain=True, **extra):
        return {
            "duration": duration,
            "syncedLyrics": "[00:01.00] hi" if synced else None,
            "plainLyrics": "hi" if plain else None,
            **extra,
        }

    def test_first_hit_wins_when_duration_unknown(self):
        from lyrics_fetcher import _select_lrclib_result
        entry, matched = _select_lrclib_result([self._entry(147), self._entry(183)], None)
        assert matched is True
        assert entry["duration"] == 147

    def test_all_mismatched_returns_first_flagged(self):
        # The Acronym case: 183s DJ edit vs 147/148s official entries
        from lyrics_fetcher import _select_lrclib_result
        entry, matched = _select_lrclib_result([self._entry(147), self._entry(148)], 182.9)
        assert matched is False
        assert entry["duration"] == 147

    def test_later_matching_candidate_beats_first_mismatch(self):
        from lyrics_fetcher import _select_lrclib_result
        entry, matched = _select_lrclib_result([self._entry(147), self._entry(181)], 182.9)
        assert matched is True
        assert entry["duration"] == 181

    def test_tolerance_boundary(self):
        from lyrics_fetcher import _select_lrclib_result
        entry, matched = _select_lrclib_result([self._entry(178)], 182.9)
        assert matched is True  # |178 - 182.9| = 4.9 <= 5.0

    def test_lyricless_entries_skipped(self):
        from lyrics_fetcher import _select_lrclib_result
        instrumental = self._entry(183, synced=False, plain=False)
        entry, matched = _select_lrclib_result([instrumental, self._entry(183)], 183.0)
        assert matched is True
        assert entry["plainLyrics"]

    def test_no_usable_entries(self):
        from lyrics_fetcher import _select_lrclib_result
        entry, matched = _select_lrclib_result([self._entry(183, synced=False, plain=False)], 183.0)
        assert entry is None

    def test_entry_without_duration_not_trusted_when_duration_known(self):
        from lyrics_fetcher import _select_lrclib_result
        entry, matched = _select_lrclib_result([self._entry(None)], 183.0)
        assert matched is False


class TestFetchLrclibDurationMismatch:
    def test_mismatch_drops_synced_keeps_plain(self, monkeypatch):
        import lyrics_fetcher as lf

        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 404
            if url.endswith("/get"):
                return R()
            r = R()
            r.status_code = 200
            r.json = lambda: [{
                "duration": 147.0,
                "syncedLyrics": "[00:01.63] Nobody pray for me\n[00:05.00] real words",
                "plainLyrics": "Nobody pray for me\nreal words",
            }]
            return r

        monkeypatch.setattr(lf.requests, "get", fake_get)
        result = lf._fetch_lrclib("Ken Carson", "The Acronym", duration=182.9)
        assert result["synced_lyrics"] is None
        assert result["duration_mismatch"] is True
        assert "Nobody pray for me" in result["plain_lyrics"]

    def test_synced_only_mismatch_converts_to_plain(self, monkeypatch):
        import lyrics_fetcher as lf

        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 404
            if url.endswith("/get"):
                return R()
            r = R()
            r.status_code = 200
            r.json = lambda: [{
                "duration": 147.0,
                "syncedLyrics": "[00:01.63] alpha beta\n[00:05.00] gamma",
                "plainLyrics": None,
            }]
            return r

        monkeypatch.setattr(lf.requests, "get", fake_get)
        result = lf._fetch_lrclib("A", "B", duration=182.9)
        assert result["synced_lyrics"] is None
        assert result["plain_lyrics"] == "alpha beta\ngamma"

    def test_matching_duration_keeps_synced(self, monkeypatch):
        import lyrics_fetcher as lf

        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 404
            if url.endswith("/get"):
                return R()
            r = R()
            r.status_code = 200
            r.json = lambda: [{
                "duration": 182.0,
                "syncedLyrics": "[00:01.63] alpha",
                "plainLyrics": "alpha",
            }]
            return r

        monkeypatch.setattr(lf.requests, "get", fake_get)
        result = lf._fetch_lrclib("A", "B", duration=182.9)
        assert result["synced_lyrics"] == "[00:01.63] alpha"
        assert "duration_mismatch" not in result
