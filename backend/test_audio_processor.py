"""Tests for audio_processor: _export format mapping, _make_replacement, _splice_with_crossfade."""

import os
from unittest.mock import patch

import pydub

# Heavy deps are stubbed in conftest.py. pydub is installed.
from audio_processor import _make_replacement, _splice_with_crossfade, _export


class TestExport:
    def test_mp3_format(self, tmp_path):
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.mp3")
        result = _export(audio, path)
        assert result == path
        assert os.path.exists(path)

    def test_wav_format(self, tmp_path):
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.wav")
        _export(audio, path)
        assert os.path.exists(path)

    def test_m4a_maps_to_mp4(self, tmp_path):
        """The .m4a extension should use pydub format 'mp4'."""
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.m4a")
        with patch.object(audio, "export") as mock_export:
            _export(audio, path)
            mock_export.assert_called_once_with(path, format="mp4", bitrate="320k")

    def test_unknown_extension_falls_back_to_mp3(self, tmp_path):
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.xyz")
        with patch.object(audio, "export") as mock_export:
            _export(audio, path)
            mock_export.assert_called_once_with(path, format="mp3", bitrate="320k")

    def test_flac_format(self, tmp_path):
        """Lossless formats must NOT receive a bitrate kwarg."""
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.flac")
        with patch.object(audio, "export") as mock_export:
            _export(audio, path)
            mock_export.assert_called_once_with(path, format="flac")

    def test_lossy_default_bitrate_when_no_source(self, tmp_path):
        """With no source_path, lossy outputs default to 320k."""
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.mp3")
        with patch.object(audio, "export") as mock_export:
            _export(audio, path)
            mock_export.assert_called_once_with(path, format="mp3", bitrate="320k")

    def _info(self, bit_rate: str, where: str = "stream"):
        """Build a mediainfo_json-shaped dict with bit_rate on stream or format."""
        if where == "stream":
            return {"streams": [{"codec_type": "audio", "bit_rate": bit_rate}], "format": {}}
        return {"streams": [], "format": {"bit_rate": bit_rate}}

    def test_lossy_uses_source_bitrate(self, tmp_path):
        """When source bitrate is detected, export uses it (capped at 320k)."""
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.mp3")
        src = tmp_path / "song.mp3"
        src.touch()
        with patch("audio_processor.mediainfo_json", return_value=self._info("192000")):
            with patch.object(audio, "export") as mock_export:
                _export(audio, path, source_path=str(src))
                mock_export.assert_called_once_with(path, format="mp3", bitrate="192k")

    def test_lossy_uses_format_bitrate_when_no_stream_bitrate(self, tmp_path):
        """Some containers only report bitrate on the format, not the stream."""
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.mp3")
        src = tmp_path / "song.mp3"
        src.touch()
        with patch("audio_processor.mediainfo_json", return_value=self._info("256000", where="format")):
            with patch.object(audio, "export") as mock_export:
                _export(audio, path, source_path=str(src))
                mock_export.assert_called_once_with(path, format="mp3", bitrate="256k")

    def test_lossy_caps_source_bitrate_at_320k(self, tmp_path):
        """Sources reporting >320k (e.g. lossless WAV) are capped at 320k."""
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.mp3")
        src = tmp_path / "song.wav"
        src.touch()
        with patch("audio_processor.mediainfo_json", return_value=self._info("1411000")):
            with patch.object(audio, "export") as mock_export:
                _export(audio, path, source_path=str(src))
                mock_export.assert_called_once_with(path, format="mp3", bitrate="320k")

    def test_lossless_ignores_source_bitrate(self, tmp_path):
        """WAV/FLAC outputs never get a bitrate kwarg, even with a source path."""
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.wav")
        src = tmp_path / "song.mp3"
        src.touch()
        with patch("audio_processor.mediainfo_json", return_value=self._info("192000")):
            with patch.object(audio, "export") as mock_export:
                _export(audio, path, source_path=str(src))
                mock_export.assert_called_once_with(path, format="wav")

    def test_low_source_bitrate_falls_back_to_default(self, tmp_path):
        """A suspiciously low (or stale) source bitrate falls back to 320k."""
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.mp3")
        src = tmp_path / "song.mp3"
        src.touch()
        with patch("audio_processor.mediainfo_json", return_value=self._info("32000")):
            with patch.object(audio, "export") as mock_export:
                _export(audio, path, source_path=str(src))
                mock_export.assert_called_once_with(path, format="mp3", bitrate="320k")

    def test_missing_source_path_falls_back_to_default(self, tmp_path):
        """A source_path that doesn't exist on disk should fall back to 320k."""
        audio = pydub.AudioSegment.silent(duration=100)
        path = str(tmp_path / "out.mp3")
        with patch.object(audio, "export") as mock_export:
            _export(audio, path, source_path="/does/not/exist.mp3")
            mock_export.assert_called_once_with(path, format="mp3", bitrate="320k")


class TestMakeReplacement:
    def test_mute_returns_silence(self):
        audio = pydub.AudioSegment.silent(duration=1000)
        result = _make_replacement(audio, 100, 500, "mute")
        assert len(result) == 400
        assert result.dBFS == float("-inf")  # silence

    def test_beep_returns_correct_duration(self):
        audio = pydub.AudioSegment.silent(duration=1000)
        result = _make_replacement(audio, 100, 500, "beep")
        assert len(result) == 400

    def test_reverse_returns_correct_duration(self):
        audio = pydub.AudioSegment.silent(duration=1000)
        result = _make_replacement(audio, 100, 500, "reverse")
        assert len(result) == 400

    def test_tape_stop_returns_correct_duration(self):
        audio = pydub.AudioSegment.silent(duration=2000)
        result = _make_replacement(audio, 0, 1000, "tape_stop")
        # tape_stop truncates to duration_ms, so should be <= 1000
        assert len(result) <= 1000

    def test_tape_stop_short_segment_returns_silence(self):
        """Segments shorter than ~200ms (chunk_len < 10) should fall back to silence."""
        audio = pydub.AudioSegment.silent(duration=500)
        # 150ms segment -> chunk_len = 150 // 20 = 7 < 10 -> silence
        result = _make_replacement(audio, 100, 250, "tape_stop")
        assert len(result) == 150
        assert result.dBFS == float("-inf")  # silence fallback

    def test_unknown_censor_type_defaults_to_mute(self):
        audio = pydub.AudioSegment.silent(duration=1000)
        result = _make_replacement(audio, 0, 500, "nonexistent_type")
        assert len(result) == 500
        assert result.dBFS == float("-inf")


class TestSpliceWithCrossfade:
    def test_basic_splice_no_crossfade(self):
        audio = pydub.AudioSegment.silent(duration=1000)
        replacement = pydub.AudioSegment.silent(duration=200)
        result = _splice_with_crossfade(audio, 400, 600, replacement, crossfade_ms=0)
        assert len(result) == 1000  # 400 + 200 + 400

    def test_splice_with_crossfade(self):
        audio = pydub.AudioSegment.silent(duration=1000)
        replacement = pydub.AudioSegment.silent(duration=200)
        result = _splice_with_crossfade(audio, 400, 600, replacement, crossfade_ms=30)
        # With crossfade: before[:-30] + fade_tail(30) + replacement(200) + fade_head(30) + after[30:]
        # = 370 + 30 + 200 + 30 + 370 = 1000
        assert len(result) == 1000

    def test_splice_at_start_skips_crossfade(self):
        """When start_ms=0, 'before' is empty so crossfade is skipped."""
        audio = pydub.AudioSegment.silent(duration=1000)
        replacement = pydub.AudioSegment.silent(duration=200)
        result = _splice_with_crossfade(audio, 0, 200, replacement, crossfade_ms=30)
        # before=0ms (< 30ms) -> plain concat: 0 + 200 + 800 = 1000
        assert len(result) == 1000

    def test_splice_at_end_skips_crossfade(self):
        """When end_ms=len(audio), 'after' is empty so crossfade is skipped."""
        audio = pydub.AudioSegment.silent(duration=1000)
        replacement = pydub.AudioSegment.silent(duration=200)
        result = _splice_with_crossfade(audio, 800, 1000, replacement, crossfade_ms=30)
        # after=0ms (< 30ms) -> plain concat: 800 + 200 + 0 = 1000
        assert len(result) == 1000

    def test_replacement_preserves_overall_structure(self):
        """Replacing a region with same-length silence should produce same-length output."""
        audio = pydub.AudioSegment.silent(duration=2000)
        replacement = pydub.AudioSegment.silent(duration=500)
        result = _splice_with_crossfade(audio, 500, 1000, replacement, crossfade_ms=30)
        assert len(result) == 2000
