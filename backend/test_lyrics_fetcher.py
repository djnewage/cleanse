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


class TestLyricsCache:
    def _setup_cache(self, monkeypatch, tmp_path):
        import lyrics_fetcher as lf
        monkeypatch.setattr(lf, "_LYRICS_CACHE_DIR", str(tmp_path))
        return lf

    def test_roundtrip(self, monkeypatch, tmp_path):
        lf = self._setup_cache(monkeypatch, tmp_path)
        path = lf._lyrics_cache_path("Artist", "Song", 182.9)
        result = {"plain_lyrics": "hi", "synced_lyrics": None,
                  "lyrics_source": "genius", "duration_mismatch": False}
        lf._lyrics_cache_put(path, result)
        assert lf._lyrics_cache_get(path) == result

    def test_key_includes_duration(self, monkeypatch, tmp_path):
        # A different edit of the same song must not share a cache entry.
        lf = self._setup_cache(monkeypatch, tmp_path)
        assert lf._lyrics_cache_path("A", "B", 147.0) != lf._lyrics_cache_path("A", "B", 182.9)
        assert lf._lyrics_cache_path("A", "B", 147.0) == lf._lyrics_cache_path("a", "b ", 147.4)

    def test_expired_entry_ignored(self, monkeypatch, tmp_path):
        import os
        lf = self._setup_cache(monkeypatch, tmp_path)
        path = lf._lyrics_cache_path("Artist", "Song", 100.0)
        lf._lyrics_cache_put(path, {"plain_lyrics": "hi"})
        old = __import__("time").time() - lf.LYRICS_CACHE_TTL_S - 60
        os.utime(path, (old, old))
        assert lf._lyrics_cache_get(path) is None

    def test_fetch_lyrics_uses_cache_before_network(self, monkeypatch, tmp_path):
        lf = self._setup_cache(monkeypatch, tmp_path)
        cached = {"plain_lyrics": "cached!", "synced_lyrics": None,
                  "lyrics_source": "genius", "duration_mismatch": False}
        lf._lyrics_cache_put(lf._lyrics_cache_path("Artist", "Song", 100.0), cached)

        def boom(*a, **k):
            raise AssertionError("network hit despite cache")
        monkeypatch.setattr(lf, "fetch_genius_lyrics", boom)
        monkeypatch.setattr(lf, "_fetch_lrclib", boom)
        assert lf.fetch_lyrics("Artist", "Song", 100.0) == cached

    def test_negative_results_not_cached(self, monkeypatch, tmp_path):
        lf = self._setup_cache(monkeypatch, tmp_path)
        monkeypatch.setattr(lf, "fetch_genius_lyrics", lambda *a: None)
        monkeypatch.setattr(lf, "_fetch_lrclib", lambda *a, **k: None)
        assert lf.fetch_lyrics("Nobody", "Nothing", 100.0) is None
        import os
        assert not os.path.exists(lf._lyrics_cache_path("Nobody", "Nothing", 100.0))


class TestTitleOnlyMismatchRejected:
    def test_title_only_duration_mismatch_returns_none(self, monkeypatch):
        # A title-only hit with the wrong duration is likely a DIFFERENT SONG
        # sharing the title — its lyrics must not be used even as plain text.
        import lyrics_fetcher as lf

        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 404
            if url.endswith("/get"):
                return R()
            r = R()
            r.status_code = 200
            if params and params.get("artist_name"):
                r.json = lambda: []  # artist-scoped searches find nothing
            else:
                r.json = lambda: [{
                    "duration": 147.0,  # vs audio 182s
                    "syncedLyrics": "[00:01.00] wrong song words",
                    "plainLyrics": "wrong song words",
                }]
            return r

        monkeypatch.setattr(lf.requests, "get", fake_get)
        assert lf._fetch_lrclib("Dookie Bros", "S.M.D.", duration=181.7) is None

    def test_artist_scoped_mismatch_still_kept_as_plain(self, monkeypatch):
        # Artist matched -> mismatch is plausibly the same song, different edit.
        import lyrics_fetcher as lf

        def fake_get(url, params=None, headers=None, timeout=None):
            class R:
                status_code = 404
            if url.endswith("/get"):
                return R()
            r = R()
            r.status_code = 200
            if params and params.get("artist_name"):
                r.json = lambda: [{
                    "duration": 147.0,
                    "syncedLyrics": "[00:01.00] same song other edit",
                    "plainLyrics": "same song other edit",
                }]
            else:
                r.json = lambda: []
            return r

        monkeypatch.setattr(lf.requests, "get", fake_get)
        result = lf._fetch_lrclib("Ken Carson", "The Acronym", duration=182.9)
        assert result["duration_mismatch"] is True
        assert result["plain_lyrics"] == "same song other edit"
        assert result["synced_lyrics"] is None


class TestMetadataCandidates:
    """(artist, title) interpretations for rip-site polluted metadata."""

    CHIEF_KEEF_FILE = "Chief Keef - Whos Concerned - Glo Radio _ - SoundLoadMate.com.mp3"

    def test_rip_site_tags_yield_embedded_candidate(self):
        # The real case: channel as artist, 'Artist - Title' in the title field.
        from lyrics_fetcher import _metadata_candidates
        cands = _metadata_candidates("Glo Radio ®", "Chief Keef - Whos Concerned",
                                     self.CHIEF_KEEF_FILE)
        assert ("Chief Keef", "Whos Concerned") in cands
        # tags-as-is (junk-cleaned) still tried first
        assert cands[0] == ("Glo Radio", "Chief Keef - Whos Concerned")
        # junk never appears in any candidate
        flat = " ".join(a + " " + t for a, t in cands).lower()
        assert "soundloadmate" not in flat and "®" not in flat

    def test_filename_only_when_tags_missing(self):
        from lyrics_fetcher import _metadata_candidates
        cands = _metadata_candidates(None, None, self.CHIEF_KEEF_FILE)
        assert cands == [("Chief Keef", "Whos Concerned")]

    def test_well_tagged_file_single_candidate(self):
        from lyrics_fetcher import _metadata_candidates
        cands = _metadata_candidates("Ken Carson", "The Acronym", "05 the acronym.mp3")
        assert cands[0] == ("Ken Carson", "The Acronym")
        # swapped-tags fallback is allowed, but the primary must be unchanged
        assert len(cands) <= 2

    def test_track_number_filename_no_bogus_candidate(self):
        from lyrics_fetcher import _metadata_candidates
        cands = _metadata_candidates("Dookie Bros", "S.M.D.", "05 - S.M.D..mp3")
        # '05' is junk-filtered -> only one filename segment -> no filename candidate
        assert all(a != "05" for a, _ in cands)
        assert cands[0] == ("Dookie Bros", "S.M.D.")

    def test_no_inputs_no_candidates(self):
        from lyrics_fetcher import _metadata_candidates
        assert _metadata_candidates(None, None, None) == []

    def test_official_video_junk_stripped(self):
        from lyrics_fetcher import _metadata_candidates
        cands = _metadata_candidates(
            None, None, "Drake - God's Plan (Official Music Video) [HD].mp3"
        )
        assert cands and cands[0][0] == "Drake"
        assert "official" not in cands[0][1].lower()
        assert cands[0][1].startswith("God's Plan")


class TestFetchLyricsCandidateLoop:
    def test_second_candidate_wins(self, monkeypatch, tmp_path):
        import lyrics_fetcher as lf
        monkeypatch.setattr(lf, "_LYRICS_CACHE_DIR", str(tmp_path))
        calls = []

        def fake_round(artist, title, duration):
            calls.append((artist, title))
            if artist == "Chief Keef":
                return {"plain_lyrics": "real lyrics", "synced_lyrics": None,
                        "lyrics_source": "genius", "duration_mismatch": False}
            return None

        monkeypatch.setattr(lf, "_fetch_lyrics_round", fake_round)
        result = lf.fetch_lyrics(
            "Glo Radio ®", "Chief Keef - Whos Concerned", 202.77,
            filename="Chief Keef - Whos Concerned - Glo Radio _ - SoundLoadMate.com.mp3",
        )
        assert result["plain_lyrics"] == "real lyrics"
        assert calls[0] == ("Glo Radio", "Chief Keef - Whos Concerned")
        assert ("Chief Keef", "Whos Concerned") in calls

    def test_result_cached_under_original_inputs(self, monkeypatch, tmp_path):
        import lyrics_fetcher as lf
        monkeypatch.setattr(lf, "_LYRICS_CACHE_DIR", str(tmp_path))
        hits = {"n": 0}

        def fake_round(artist, title, duration):
            hits["n"] += 1
            return {"plain_lyrics": "x", "synced_lyrics": None,
                    "lyrics_source": "genius", "duration_mismatch": False}

        monkeypatch.setattr(lf, "_fetch_lyrics_round", fake_round)
        args = ("A ®", "B - C", 100.0)
        lf.fetch_lyrics(*args, filename="B - C - x.com.mp3")
        lf.fetch_lyrics(*args, filename="B - C - x.com.mp3")
        assert hits["n"] == 1  # second call served from cache

    def test_all_candidates_fail_returns_none(self, monkeypatch, tmp_path):
        import lyrics_fetcher as lf
        monkeypatch.setattr(lf, "_LYRICS_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(lf, "_fetch_lyrics_round", lambda *a: None)
        assert lf.fetch_lyrics("A", "B", 100.0) is None
