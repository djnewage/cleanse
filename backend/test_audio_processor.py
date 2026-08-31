"""Tests for audio_processor: _export format mapping, _make_replacement, _splice_with_crossfade, _copy_metadata."""

import os
import subprocess
from unittest.mock import patch

import imageio_ffmpeg
import pydub

# Heavy deps are stubbed in conftest.py. pydub is installed.
from audio_processor import _make_replacement, _splice_with_crossfade, _export, _copy_metadata


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


class TestCopyMetadata:
    """_copy_metadata remuxes source tags + cover art onto the exported file.

    These are integration tests: they shell out to the bundled ffmpeg (the same
    binary the feature uses) to build a fixture with embedded art and to probe
    the result, since ffprobe is not assumed present in the environment.
    """

    def _ffmpeg(self):
        return imageio_ffmpeg.get_ffmpeg_exe()

    def _make_source_with_art(self, path):
        """Create a 1s MP3 with embedded cover art + an artist tag via ffmpeg."""
        ff = self._ffmpeg()
        art = os.path.splitext(path)[0] + "_art.png"
        subprocess.run(
            [ff, "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-frames:v", "1", art],
            capture_output=True, check=True,
        )
        subprocess.run(
            [ff, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-i", art,
             "-map", "0:a", "-map", "1:v", "-c:a", "libmp3lame", "-id3v2_version", "3",
             "-metadata", "artist=TestArtist", "-disposition:v:0", "attached_pic", path],
            capture_output=True, check=True,
        )

    def _probe(self, path):
        return subprocess.run([self._ffmpeg(), "-i", path], capture_output=True).stderr

    def test_copies_cover_art_and_tags_to_mp3(self, tmp_path):
        src = str(tmp_path / "src.mp3")
        self._make_source_with_art(src)
        # A freshly exported output carries no metadata (as pydub produces).
        out = str(tmp_path / "out.mp3")
        pydub.AudioSegment.silent(duration=1000).export(out, format="mp3")
        assert b"attached pic" not in self._probe(out)  # sanity: starts bare

        _copy_metadata(src, out, "mp3")

        info = self._probe(out)
        assert b"attached pic" in info  # cover art carried over
        assert b"TestArtist" in info    # text tags carried over

    def test_no_leftover_temp_file_on_success(self, tmp_path):
        src = str(tmp_path / "src.mp3")
        self._make_source_with_art(src)
        out = str(tmp_path / "out.mp3")
        pydub.AudioSegment.silent(duration=1000).export(out, format="mp3")
        _copy_metadata(src, out, "mp3")
        assert not os.path.exists(str(tmp_path / "out.meta.mp3"))

    def test_unsupported_format_is_noop(self, tmp_path):
        """WAV/AIFF have no cover-art container -> skip the remux entirely."""
        src = str(tmp_path / "src.mp3")
        open(src, "w").close()
        with patch("audio_processor.subprocess.run") as mock_run:
            _copy_metadata(src, str(tmp_path / "out.wav"), "wav")
            mock_run.assert_not_called()

    def test_missing_source_is_noop(self, tmp_path):
        with patch("audio_processor.subprocess.run") as mock_run:
            _copy_metadata("/does/not/exist.mp3", str(tmp_path / "out.mp3"), "mp3")
            mock_run.assert_not_called()

    def test_ffmpeg_failure_leaves_output_intact(self, tmp_path):
        """A failed remux must leave the original exported file untouched."""
        src = str(tmp_path / "src.mp3")
        open(src, "w").close()  # empty/invalid source -> ffmpeg returns nonzero
        out = str(tmp_path / "out.mp3")
        pydub.AudioSegment.silent(duration=500).export(out, format="mp3")
        before = os.path.getsize(out)

        _copy_metadata(src, out, "mp3")  # error is swallowed

        assert os.path.exists(out)
        assert os.path.getsize(out) == before
        assert not os.path.exists(str(tmp_path / "out.meta.mp3"))


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

    def test_splice_at_start_still_crossfades(self):
        """A region at t=0 has no 'before', but the fade lives inside the
        region now, so the boundary is still smoothed rather than hard-cut."""
        audio = pydub.AudioSegment.silent(duration=1000)
        replacement = pydub.AudioSegment.silent(duration=200)
        result = _splice_with_crossfade(audio, 0, 200, replacement, crossfade_ms=30)
        assert len(result) == 1000

    def test_splice_at_end_still_crossfades(self):
        """Same at the tail: no 'after' to borrow from, fade stays in-region."""
        audio = pydub.AudioSegment.silent(duration=1000)
        replacement = pydub.AudioSegment.silent(duration=200)
        result = _splice_with_crossfade(audio, 800, 1000, replacement, crossfade_ms=30)
        assert len(result) == 1000

    def test_short_region_halves_the_crossfade(self):
        """The two fades must not overlap on a region shorter than 2x crossfade."""
        audio = pydub.AudioSegment.silent(duration=1000)
        replacement = pydub.AudioSegment.silent(duration=20)
        result = _splice_with_crossfade(audio, 400, 420, replacement, crossfade_ms=30)
        assert len(result) == 1000

    def _envelope_dbfs(self, seg, step_ms=2):
        """Per-step RMS in dBFS across a segment."""
        import math
        out = []
        for t in range(0, len(seg) - step_ms, step_ms):
            chunk = seg[t:t + step_ms]
            out.append((t, chunk.dBFS if chunk.rms > 0 else -math.inf))
        return out

    def test_no_level_hole_or_step_at_boundaries(self):
        """Regression: the splice must not punch a hole in the outgoing audio.

        The old implementation faded the outgoing audio to digital silence and
        then hard-cut to the replacement at full level, which put a ~23 dB
        hole and a ~25 dB single-sample step into the mix at every censored
        word -- the "mute pops" reported against 1.20.0. A replacement at the
        same level as the surrounding audio must splice in inaudibly.
        """
        from pydub.generators import Sine

        # Same tone at the same level either side of the splice: a correct
        # crossfade is then a no-op on the envelope.
        audio = Sine(440).to_audio_segment(duration=2000)
        replacement = Sine(440).to_audio_segment(duration=400)
        result = _splice_with_crossfade(audio, 800, 1200, replacement, crossfade_ms=30)

        reference = audio.dBFS
        for boundary in (800, 1200):
            window = result[boundary - 60:boundary + 60]
            for offset, level in self._envelope_dbfs(window):
                assert level > reference - 6.0, (
                    f"{reference - level:.1f} dB hole at "
                    f"{boundary - 60 + offset}ms (boundary {boundary}ms)"
                )

    def test_boundary_is_continuous_for_a_full_level_replacement(self):
        """No abrupt level step across either edge of the spliced region."""
        from pydub.generators import Sine

        audio = Sine(440).to_audio_segment(duration=2000)
        # A different tone at the same level stands in for the accompaniment
        # stem the vocals-only path splices in.
        replacement = Sine(330).to_audio_segment(duration=400)
        result = _splice_with_crossfade(audio, 800, 1200, replacement, crossfade_ms=30)

        for boundary in (800, 1200):
            before = result[boundary - 5:boundary]
            after = result[boundary:boundary + 5]
            assert abs(before.dBFS - after.dBFS) < 3.0, (
                f"{abs(before.dBFS - after.dBFS):.1f} dB step at {boundary}ms"
            )

    def test_replacement_preserves_overall_structure(self):
        """Replacing a region with same-length silence should produce same-length output."""
        audio = pydub.AudioSegment.silent(duration=2000)
        replacement = pydub.AudioSegment.silent(duration=500)
        result = _splice_with_crossfade(audio, 500, 1000, replacement, crossfade_ms=30)
        assert len(result) == 2000


class TestBuildCensorRegions:
    """Padded per-word intervals merge into regions; padding is additive for
    lyrics-sourced words (the old 3x/2x multiplier chained blanket mutes)."""

    def _w(self, word, start, end, source=None, censor_type="mute"):
        d = {"word": word, "start": start, "end": end, "censor_type": censor_type}
        if source:
            d["detection_source"] = source
        return d

    def test_isolated_words_stay_separate(self):
        from audio_processor import _build_censor_regions
        regions = _build_censor_regions(
            [self._w("a", 10.0, 10.4), self._w("b", 20.0, 20.4)],
            audio_len_ms=180_000, padding_before_ms=150, padding_after_ms=100,
        )
        assert len(regions) == 2
        assert regions[0]["start_ms"] == 10_000 - 150
        assert regions[0]["end_ms"] == 10_400 + 100

    def test_overlapping_padded_words_merge(self):
        from audio_processor import _build_censor_regions
        # padded intervals: [9850, 10500] and [10450, 11100] -> one region
        regions = _build_censor_regions(
            [self._w("a", 10.0, 10.4), self._w("b", 10.6, 11.0)],
            audio_len_ms=180_000, padding_before_ms=150, padding_after_ms=100,
        )
        assert len(regions) == 1
        assert regions[0]["words"] == ["a", "b"]
        assert regions[0]["start_ms"] == 9850
        assert regions[0]["end_ms"] == 11_100

    def test_lyrics_padding_is_additive_not_multiplicative(self):
        from audio_processor import _build_censor_regions, ESTIMATED_PAD_EXTRA_MS
        regions = _build_censor_regions(
            [self._w("a", 10.0, 10.4, source="lyrics")],
            audio_len_ms=180_000, padding_before_ms=150, padding_after_ms=100,
        )
        assert regions[0]["start_ms"] == 10_000 - 150 - ESTIMATED_PAD_EXTRA_MS
        assert regions[0]["end_ms"] == 10_400 + 100 + ESTIMATED_PAD_EXTRA_MS

    def test_different_censor_types_not_merged(self):
        from audio_processor import _build_censor_regions
        regions = _build_censor_regions(
            [self._w("a", 10.0, 10.4, censor_type="mute"),
             self._w("b", 10.5, 10.9, censor_type="beep")],
            audio_len_ms=180_000, padding_before_ms=150, padding_after_ms=100,
        )
        assert len(regions) == 2
        assert regions[0]["censor_type"] == "mute"
        assert regions[1]["censor_type"] == "beep"
        # the later region is trimmed so the same samples aren't spliced twice
        assert regions[1]["start_ms"] >= regions[0]["end_ms"]

    def test_clamped_to_audio_bounds(self):
        from audio_processor import _build_censor_regions
        regions = _build_censor_regions(
            [self._w("a", 0.05, 0.3), self._w("b", 179.9, 180.5)],
            audio_len_ms=180_000, padding_before_ms=150, padding_after_ms=100,
        )
        assert regions[0]["start_ms"] == 0
        assert regions[-1]["end_ms"] == 180_000

    def test_empty_words(self):
        from audio_processor import _build_censor_regions
        assert _build_censor_regions([], 180_000, 150, 100) == []


class TestCensorVocalsOnly:
    """The output must be the ORIGINAL audio everywhere except censored regions.

    Regression: this used to return accompaniment.overlay(vocals), making the
    whole track a Demucs reconstruction rather than only the censored words.
    """

    def _build(self, tmp_path, duration_ms=3000, stem_duration_ms=None):
        """Write an original plus two stems as three distinguishable tones."""
        from pydub.generators import Sine

        stem_len = stem_duration_ms if stem_duration_ms is not None else duration_ms
        original = Sine(440).to_audio_segment(duration=duration_ms)
        vocals = Sine(880).to_audio_segment(duration=stem_len)
        accomp = Sine(220).to_audio_segment(duration=stem_len)

        paths = {}
        for name, seg in (("original", original), ("vocals", vocals), ("accomp", accomp)):
            p = str(tmp_path / f"{name}.wav")
            seg.export(p, format="wav")
            paths[name] = p
        paths["out"] = str(tmp_path / "out.wav")
        return paths

    def _words(self, start=1.0, end=1.2, censor_type="mute"):
        return [{"word": "damn", "start": start, "end": end, "censor_type": censor_type}]

    def test_output_length_matches_source_exactly(self, tmp_path):
        """Any drift here invalidates every cue point after it."""
        from audio_processor import censor_audio_vocals_only

        p = self._build(tmp_path)
        censor_audio_vocals_only(
            p["vocals"], p["accomp"], self._words(), p["out"], source_path=p["original"]
        )
        assert len(pydub.AudioSegment.from_file(p["out"])) == len(
            pydub.AudioSegment.from_file(p["original"])
        )

    def test_uncensored_audio_is_the_original_not_a_stem_remix(self, tmp_path):
        """Audio away from any censored word must be untouched source."""
        from audio_processor import censor_audio_vocals_only

        p = self._build(tmp_path)
        censor_audio_vocals_only(
            p["vocals"], p["accomp"], self._words(), p["out"], source_path=p["original"]
        )
        out = pydub.AudioSegment.from_file(p["out"])
        original = pydub.AudioSegment.from_file(p["original"])
        # 2.4-2.6s is well clear of the padded+crossfaded region around 1.0-1.2s
        assert out[2400:2600].raw_data == original[2400:2600].raw_data

    def test_censored_region_is_actually_modified(self, tmp_path):
        """Sanity check the splice still happens at all."""
        from audio_processor import censor_audio_vocals_only

        p = self._build(tmp_path)
        censor_audio_vocals_only(
            p["vocals"], p["accomp"], self._words(), p["out"], source_path=p["original"]
        )
        out = pydub.AudioSegment.from_file(p["out"])
        original = pydub.AudioSegment.from_file(p["original"])
        assert out[1050:1150].raw_data != original[1050:1150].raw_data

    def test_short_stems_do_not_shrink_the_output(self, tmp_path):
        """Demucs stems can end a few ms early; a censor at the tail must still fit."""
        from audio_processor import censor_audio_vocals_only

        p = self._build(tmp_path, duration_ms=3000, stem_duration_ms=2950)
        censor_audio_vocals_only(
            p["vocals"], p["accomp"], self._words(start=2.7, end=2.9), p["out"],
            source_path=p["original"],
        )
        assert len(pydub.AudioSegment.from_file(p["out"])) == 3000

    def test_falls_back_to_stem_remix_without_a_source(self, tmp_path):
        """No source_path (shouldn't happen in practice) must still produce output."""
        from audio_processor import censor_audio_vocals_only

        p = self._build(tmp_path)
        censor_audio_vocals_only(p["vocals"], p["accomp"], self._words(), p["out"])
        assert os.path.exists(p["out"])
        assert len(pydub.AudioSegment.from_file(p["out"])) == 3000

    def test_leaked_vocal_triggers_bandreject_without_changing_length(self, tmp_path):
        """Silent vocals mean the word leaked into the accompaniment."""
        from pydub.generators import Sine
        from audio_processor import censor_audio_vocals_only

        p = self._build(tmp_path)
        # Rewrite the vocals stem as silence so is_leaked is True.
        pydub.AudioSegment.silent(duration=3000, frame_rate=44100).export(
            p["vocals"], format="wav"
        )
        censor_audio_vocals_only(
            p["vocals"], p["accomp"], self._words(), p["out"], source_path=p["original"]
        )
        assert len(pydub.AudioSegment.from_file(p["out"])) == 3000
