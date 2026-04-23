"""Tests that ffprobe is always resolvable, even without a system install.

These tests replicate the ffprobe resolution logic from main.py to verify
that the fallback chain works correctly in all environments.
"""

import os
import shutil
import subprocess

import imageio_ffmpeg
from pydub import AudioSegment


def _resolve_ffprobe():
    """Replicate main.py's ffprobe resolution logic and return the path."""
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    extra_paths = ['/opt/homebrew/bin', '/usr/local/bin', os.path.dirname(ffmpeg_exe)]
    search_path = os.environ.get('PATH', '')
    for p in extra_paths:
        if p not in search_path:
            search_path = p + os.pathsep + search_path

    # Check PATH first
    ffprobe = shutil.which('ffprobe', path=search_path)
    if ffprobe:
        return ffprobe

    # Fallback: static_ffmpeg
    try:
        import static_ffmpeg
        _, sf_ffprobe = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()
        return sf_ffprobe
    except ImportError:
        return None


class TestFfprobeResolution:
    def test_ffprobe_resolvable(self):
        """At least one ffprobe source (PATH or static_ffmpeg) must be available."""
        ffprobe = _resolve_ffprobe()
        assert ffprobe is not None, (
            "ffprobe not found via PATH or static_ffmpeg — "
            "users will hit 'FileNotFoundError: ffprobe' at runtime"
        )
        assert os.path.isfile(ffprobe), f"ffprobe path does not exist: {ffprobe}"

    def test_ffprobe_accepts_version_flag(self):
        """The resolved ffprobe binary should be functional."""
        ffprobe = _resolve_ffprobe()
        if ffprobe is None:
            import pytest
            pytest.skip("no ffprobe available")
        result = subprocess.run(
            [ffprobe, "-version"], capture_output=True, timeout=10
        )
        assert result.returncode == 0, f"ffprobe -version failed: {result.stderr}"

    def test_pydub_can_load_audio(self, tmp_path):
        """End-to-end: pydub can export and re-load audio (exercises ffprobe)."""
        ffprobe = _resolve_ffprobe()
        if ffprobe:
            AudioSegment.ffprobe = ffprobe

        wav_path = str(tmp_path / "test.wav")
        silence = AudioSegment.silent(duration=500)
        silence.export(wav_path, format="wav")
        loaded = AudioSegment.from_file(wav_path)
        assert len(loaded) >= 400  # roughly 500ms

    def test_fallback_works_without_system_ffprobe(self):
        """With ffprobe stripped from PATH, static_ffmpeg fallback must work."""
        try:
            import static_ffmpeg
        except ImportError:
            import pytest
            pytest.skip("static_ffmpeg not installed")

        # Resolve using only the static_ffmpeg fallback (empty PATH)
        _, sf_ffprobe = static_ffmpeg.run.get_or_fetch_platform_executables_else_raise()
        assert os.path.isfile(sf_ffprobe), f"static_ffmpeg ffprobe missing: {sf_ffprobe}"
        result = subprocess.run(
            [sf_ffprobe, "-version"], capture_output=True, timeout=10
        )
        assert result.returncode == 0
