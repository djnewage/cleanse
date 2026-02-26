"""Tests for merge_word_lists in main.py."""

import sys
from unittest.mock import MagicMock

# Heavy deps (torch, demucs, faster_whisper, fastapi, pydantic, uvicorn)
# are stubbed in conftest.py. transcribe.py imports naturally using the
# mocked faster_whisper.

from main import merge_word_lists  # noqa: E402


def _word(text, start, end, is_profanity=False, **kwargs):
    """Helper to build a word dict."""
    return {"word": text, "start": start, "end": end, "confidence": 0.9, "is_profanity": is_profanity, **kwargs}


class TestMergeWordLists:
    def test_secondary_non_profanity_ignored(self):
        primary = [_word("hello", 0.0, 0.5)]
        secondary = [_word("world", 1.0, 1.5, is_profanity=False)]
        result = merge_word_lists(primary, secondary)
        assert len(result) == 1
        assert result[0]["word"] == "hello"

    def test_overlapping_same_word_absorbed(self):
        primary = [_word("shit", 1.0, 1.5, is_profanity=False)]
        secondary = [_word("shit", 1.1, 1.6, is_profanity=True)]
        result = merge_word_lists(primary, secondary)
        assert len(result) == 1
        assert result[0]["is_profanity"] is True
        assert result[0]["detection_source"] == "vocals"

    def test_overlapping_different_word_not_absorbed(self):
        """The v1.6.0 bug fix: different word + overlap + primary not profanity -> NOT absorbed."""
        primary = [_word("sit", 1.0, 1.5, is_profanity=False)]
        secondary = [_word("shit", 1.1, 1.6, is_profanity=True)]
        result = merge_word_lists(primary, secondary)
        assert len(result) == 2
        adlib = [w for w in result if w.get("detection_source") == "adlib"]
        assert len(adlib) == 1
        assert adlib[0]["word"] == "shit"

    def test_overlapping_primary_already_profanity_absorbed(self):
        """If primary is already profanity, overlapping secondary is absorbed regardless of text."""
        primary = [_word("fck", 1.0, 1.5, is_profanity=True)]
        secondary = [_word("fuck", 1.1, 1.6, is_profanity=True)]
        result = merge_word_lists(primary, secondary)
        assert len(result) == 1
        assert result[0]["detection_source"] == "vocals"

    def test_near_miss_same_word_absorbed(self):
        primary = [_word("shit", 1.0, 1.3)]
        secondary = [_word("shit", 1.4, 1.7, is_profanity=True)]
        result = merge_word_lists(primary, secondary, overlap_threshold=0.3)
        assert len(result) == 1
        assert result[0]["is_profanity"] is True
        assert result[0]["detection_source"] == "vocals"

    def test_no_overlap_appended_as_adlib(self):
        primary = [_word("hello", 0.0, 0.5)]
        secondary = [_word("shit", 5.0, 5.5, is_profanity=True)]
        result = merge_word_lists(primary, secondary)
        assert len(result) == 2
        adlib = [w for w in result if w.get("detection_source") == "adlib"]
        assert len(adlib) == 1
        assert adlib[0]["word"] == "shit"

    def test_empty_primary(self):
        secondary = [_word("shit", 1.0, 1.5, is_profanity=True)]
        result = merge_word_lists([], secondary)
        assert len(result) == 1
        assert result[0]["detection_source"] == "adlib"

    def test_empty_secondary(self):
        primary = [_word("hello", 0.0, 0.5)]
        result = merge_word_lists(primary, [])
        assert len(result) == 1
        assert result[0]["word"] == "hello"

    def test_result_sorted_by_start(self):
        primary = [_word("world", 5.0, 5.5)]
        secondary = [_word("shit", 1.0, 1.5, is_profanity=True)]
        result = merge_word_lists(primary, secondary)
        starts = [w["start"] for w in result]
        assert starts == sorted(starts)

    def test_does_not_mutate_input(self):
        primary = [_word("hello", 0.0, 0.5)]
        secondary = [_word("shit", 0.1, 0.6, is_profanity=True)]
        merge_word_lists(primary, secondary)
        assert "detection_source" not in primary[0]
