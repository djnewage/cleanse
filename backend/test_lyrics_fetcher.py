"""Tests for lyrics_fetcher: _extract_first_artist, parse_synced_lyrics, find_lyrics_profanity."""

# Heavy deps are stubbed in conftest.py.
# tinytag and requests need stubbing here (lightweight but not always installed).
import sys
from unittest.mock import MagicMock

sys.modules.setdefault("tinytag", MagicMock())
sys.modules.setdefault("requests", MagicMock())

from lyrics_fetcher import _extract_first_artist, parse_synced_lyrics, find_lyrics_profanity  # noqa: E402


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
