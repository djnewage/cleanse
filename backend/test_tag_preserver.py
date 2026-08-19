"""Tests for tag_preserver: DJ cue tags must survive the export."""

import os

import pydub
import pytest
from pydub.generators import Sine

from audio_processor import _export, _copy_metadata
from tag_preserver import copy_tags, describe_dj_tags

# A stand-in for Serato's cue/loop payload. Contents are never parsed, so the
# only thing that matters is that the exact bytes come out the other side.
MARKERS_BLOB = bytes(range(256)) * 4
BEATGRID_BLOB = b"\x00\x01\x02\x03beatgrid-payload\xff\xfe"


def _seg(duration_ms: int = 500):
    """Stand-in for censored audio.

    Deliberately synthesized rather than decoded from the source file: pydub's
    from_file() shells out to ffprobe, which isn't bundled (main.py monkey-patches
    an ffmpeg-based fallback at runtime, but that module isn't loaded here). The
    audio content is irrelevant to tag passthrough anyway.
    """
    return Sine(880).to_audio_segment(duration=duration_ms)


def _mp3_with_serato(path: str, duration_ms: int = 500) -> str:
    from mutagen.id3 import ID3, GEOB, TLEN

    Sine(440).to_audio_segment(duration=duration_ms).export(path, format="mp3")
    try:
        tags = ID3(path)
    except Exception:
        tags = ID3()
    tags.add(GEOB(encoding=0, mime="application/octet-stream",
                  desc="Serato Markers2", data=MARKERS_BLOB))
    tags.add(GEOB(encoding=0, mime="application/octet-stream",
                  desc="Serato BeatGrid", data=BEATGRID_BLOB))
    tags.add(TLEN(encoding=0, text=["999999"]))
    tags.save(path, v2_version=3)
    return path


def _flac_with_serato(path: str, duration_ms: int = 500) -> str:
    from mutagen.flac import FLAC

    Sine(440).to_audio_segment(duration=duration_ms).export(path, format="flac")
    f = FLAC(path)
    f["SERATO_MARKERS_V2"] = ["dGVzdC1wYXlsb2Fk"]
    f.save()
    return path


class TestDescribeDjTags:
    def test_detects_serato_frames(self, tmp_path):
        p = _mp3_with_serato(str(tmp_path / "src.mp3"))
        info = describe_dj_tags(p)
        assert info["serato"] is True
        assert info["any_dj"] is True
        assert "GEOB:Serato Markers2" in info["tags"]

    def test_plain_file_has_no_dj_tags(self, tmp_path):
        p = str(tmp_path / "plain.mp3")
        Sine(440).to_audio_segment(duration=300).export(p, format="mp3")
        info = describe_dj_tags(p)
        assert info["any_dj"] is False
        assert info["tags"] == []

    def test_missing_file_is_handled(self, tmp_path):
        info = describe_dj_tags(str(tmp_path / "nope.mp3"))
        assert info["any_dj"] is False


class TestFfmpegDropsGeob:
    """Documents why this module exists at all."""

    def test_copy_metadata_alone_loses_serato_frames(self, tmp_path):
        from mutagen.id3 import ID3

        src = _mp3_with_serato(str(tmp_path / "src.mp3"))
        out = str(tmp_path / "out.mp3")
        Sine(880).to_audio_segment(duration=500).export(out, format="mp3")

        _copy_metadata(src, out, "mp3")

        try:
            keys = set(ID3(out).keys())
        except Exception:
            keys = set()
        assert not any(k.startswith("GEOB") for k in keys), (
            "ffmpeg unexpectedly preserved GEOB - tag_preserver may be redundant"
        )


class TestCopyTagsRoundTrip:
    def test_mp3_serato_frames_survive_export(self, tmp_path):
        from mutagen.id3 import ID3

        src = _mp3_with_serato(str(tmp_path / "src.mp3"))
        out = str(tmp_path / "out.mp3")

        _export(_seg(), out, source_path=src)

        tags = ID3(out)
        assert tags["GEOB:Serato Markers2"].data == MARKERS_BLOB
        assert tags["GEOB:Serato BeatGrid"].data == BEATGRID_BLOB

    def test_flac_serato_comment_survives_export(self, tmp_path):
        from mutagen.flac import FLAC

        src = _flac_with_serato(str(tmp_path / "src.flac"))
        out = str(tmp_path / "out.flac")

        _export(_seg(), out, source_path=src)

        assert FLAC(out)["SERATO_MARKERS_V2"] == ["dGVzdC1wYXlsb2Fk"]

    def test_reports_preserved(self, tmp_path):
        src = _mp3_with_serato(str(tmp_path / "src.mp3"))
        out = str(tmp_path / "out.mp3")
        _seg().export(out, format="mp3")

        result = copy_tags(src, out)
        assert result["preserved"] is True
        assert result["reason"] is None
        assert "GEOB:Serato Markers2" in result["dj_tags"]

    def test_stale_tlen_is_dropped(self, tmp_path):
        from mutagen.id3 import ID3

        src = _mp3_with_serato(str(tmp_path / "src.mp3"))
        out = str(tmp_path / "out.mp3")
        _seg().export(out, format="mp3")

        copy_tags(src, out)

        try:
            keys = set(ID3(out).keys())
        except Exception:
            keys = set()
        assert "TLEN" not in keys


class TestCopyTagsGuards:
    def test_cross_format_reports_format_change(self, tmp_path):
        src = _mp3_with_serato(str(tmp_path / "src.mp3"))
        out = str(tmp_path / "out.flac")
        Sine(440).to_audio_segment(duration=500).export(out, format="flac")

        result = copy_tags(src, out)
        assert result["preserved"] is False
        assert result["reason"] == "format_change"

    def test_missing_source_reports_no_source(self, tmp_path):
        out = str(tmp_path / "out.mp3")
        Sine(440).to_audio_segment(duration=300).export(out, format="mp3")
        assert copy_tags(str(tmp_path / "nope.mp3"), out)["reason"] == "no_source"
        assert copy_tags(None, out)["reason"] == "no_source"

    def test_unsupported_container_is_reported(self, tmp_path):
        src = str(tmp_path / "src.ogg")
        out = str(tmp_path / "out.ogg")
        Sine(440).to_audio_segment(duration=300).export(src, format="ogg")
        Sine(440).to_audio_segment(duration=300).export(out, format="ogg")
        assert copy_tags(src, out)["reason"] == "unsupported_container"

    def test_corrupt_source_does_not_raise(self, tmp_path):
        src = str(tmp_path / "corrupt.mp3")
        with open(src, "wb") as fh:
            fh.write(b"this is not an mp3")
        out = str(tmp_path / "out.mp3")
        Sine(440).to_audio_segment(duration=300).export(out, format="mp3")

        result = copy_tags(src, out)
        assert result["preserved"] is False

    def test_does_not_overwrite_existing_output_tags(self, tmp_path):
        """Purely additive: whatever ffmpeg already wrote must win."""
        from mutagen.id3 import ID3, TIT2

        src = _mp3_with_serato(str(tmp_path / "src.mp3"))
        try:
            stags = ID3(src)
        except Exception:
            stags = ID3()
        stags.add(TIT2(encoding=3, text=["Source Title"]))
        stags.save(src, v2_version=3)

        out = str(tmp_path / "out.mp3")
        _seg().export(out, format="mp3")
        otags = ID3()
        otags.add(TIT2(encoding=3, text=["Existing Title"]))
        otags.save(out, v2_version=3)

        copy_tags(src, out)

        assert ID3(out)["TIT2"].text == ["Existing Title"]
        assert ID3(out)["GEOB:Serato Markers2"].data == MARKERS_BLOB
