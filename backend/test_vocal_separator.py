"""Tests for vocal_separator — MPS->CPU fallback logic and ffmpeg decode path."""

import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Heavy deps (torch, torchaudio, demucs, tqdm) are stubbed in conftest.py.
# device_info is a lightweight local module — import it normally.
sys.modules.setdefault("device_info", MagicMock())

# Try to load real torch once at module import time. Torch's C-extension init
# registers global TORCH_LIBRARY entries that cannot be re-registered, so we
# cannot pop+reimport per-test. If this load fails (e.g. in a lightweight
# test env where torch is absent), _real_torch stays None and the round-trip
# tests below get skipped.
_real_torch = None
_saved_stubs = {mod: sys.modules.pop(mod, None) for mod in ("torch", "torchaudio", "torchaudio.transforms")}
try:
    import torch as _real_torch  # noqa: F401
except ImportError:
    # Restore stubs so the mocked tests still work.
    for mod, stub in _saved_stubs.items():
        if stub is not None:
            sys.modules[mod] = stub

import vocal_separator  # noqa: E402


def _make_fake_sources():
    """Return a mock tensor that supports [0, i] indexing and .cpu()."""
    src = MagicMock()
    channel = MagicMock()
    channel.cpu.return_value = channel
    channel.__add__ = lambda self, other: channel
    channel.__radd__ = lambda self, other: channel
    src.__getitem__ = lambda self, key: channel
    return src


@pytest.fixture(autouse=True)
def _reset_model_cache():
    """Clear the cached model between tests."""
    vocal_separator._model = None
    yield
    vocal_separator._model = None


@patch("vocal_separator._report_progress")
@patch("device_info.get_device_string", return_value="mps")
@patch("vocal_separator._get_model")
@patch("demucs.apply.apply_model")
@patch("vocal_separator._write_wav")
@patch("vocal_separator._decode_audio_ffmpeg")
def test_mps_fallback_on_65536_error(
    mock_decode, mock_write, mock_apply, mock_get_model, mock_device, mock_progress, tmp_path
):
    """apply_model raises NotImplementedError with '65536' on MPS, succeeds on CPU retry."""
    mock_decode.return_value = np.zeros((2, 44100), dtype=np.float32)

    model = MagicMock()
    model.samplerate = 44100
    mock_get_model.return_value = model

    sources = _make_fake_sources()
    mock_apply.side_effect = [
        NotImplementedError("Output channels > 65536 not supported on MPS"),
        sources,
    ]

    result = vocal_separator.separate("input.wav", str(tmp_path))

    assert mock_apply.call_count == 2
    model.to.assert_called_once_with("cpu")
    assert "vocals_path" in result
    assert "accompaniment_path" in result


@patch("vocal_separator._report_progress")
@patch("device_info.get_device_string", return_value="mps")
@patch("vocal_separator._get_model")
@patch("demucs.apply.apply_model")
@patch("vocal_separator._write_wav")
@patch("vocal_separator._decode_audio_ffmpeg")
def test_mps_fallback_on_mps_runtime_error(
    mock_decode, mock_write, mock_apply, mock_get_model, mock_device, mock_progress, tmp_path
):
    """apply_model raises RuntimeError mentioning 'MPS' on MPS, succeeds on CPU retry."""
    mock_decode.return_value = np.zeros((2, 44100), dtype=np.float32)

    model = MagicMock()
    model.samplerate = 44100
    mock_get_model.return_value = model

    sources = _make_fake_sources()
    mock_apply.side_effect = [
        RuntimeError("MPS backend out of memory"),
        sources,
    ]

    result = vocal_separator.separate("input.wav", str(tmp_path))

    assert mock_apply.call_count == 2
    model.to.assert_called_once_with("cpu")
    assert "vocals_path" in result


@patch("vocal_separator._report_progress")
@patch("device_info.get_device_string", return_value="cpu")
@patch("vocal_separator._get_model")
@patch("demucs.apply.apply_model")
@patch("vocal_separator._write_wav")
@patch("vocal_separator._decode_audio_ffmpeg")
def test_no_fallback_when_already_on_cpu(
    mock_decode, mock_write, mock_apply, mock_get_model, mock_device, mock_progress, tmp_path
):
    """When already on CPU, the 65536 error propagates (no infinite retry)."""
    mock_decode.return_value = np.zeros((2, 44100), dtype=np.float32)

    model = MagicMock()
    model.samplerate = 44100
    mock_get_model.return_value = model

    mock_apply.side_effect = NotImplementedError("Output channels > 65536 not supported")

    with pytest.raises(NotImplementedError, match="65536"):
        vocal_separator.separate("input.wav", str(tmp_path))

    assert mock_apply.call_count == 1
    model.to.assert_not_called()


@patch("vocal_separator._report_progress")
@patch("device_info.get_device_string", return_value="mps")
@patch("vocal_separator._get_model")
@patch("demucs.apply.apply_model")
@patch("vocal_separator._write_wav")
@patch("vocal_separator._decode_audio_ffmpeg")
def test_unrelated_error_propagates(
    mock_decode, mock_write, mock_apply, mock_get_model, mock_device, mock_progress, tmp_path
):
    """Unrelated RuntimeError (no '65536' or 'MPS') propagates unchanged."""
    mock_decode.return_value = np.zeros((2, 44100), dtype=np.float32)

    model = MagicMock()
    model.samplerate = 44100
    mock_get_model.return_value = model

    mock_apply.side_effect = RuntimeError("out of memory")

    with pytest.raises(RuntimeError, match="out of memory"):
        vocal_separator.separate("input.wav", str(tmp_path))

    assert mock_apply.call_count == 1
    model.to.assert_not_called()


@patch("vocal_separator._report_progress")
@patch("device_info.get_device_string", return_value="mps")
@patch("vocal_separator._get_model")
@patch("demucs.apply.apply_model")
@patch("vocal_separator._write_wav")
@patch("vocal_separator._decode_audio_ffmpeg")
def test_successful_gpu_no_fallback(
    mock_decode, mock_write, mock_apply, mock_get_model, mock_device, mock_progress, tmp_path
):
    """apply_model succeeds on first call -- no fallback, no model.to('cpu')."""
    mock_decode.return_value = np.zeros((2, 44100), dtype=np.float32)

    model = MagicMock()
    model.samplerate = 44100
    mock_get_model.return_value = model

    mock_apply.return_value = _make_fake_sources()

    result = vocal_separator.separate("input.wav", str(tmp_path))

    assert mock_apply.call_count == 1
    model.to.assert_not_called()
    assert "vocals_path" in result
    assert "accompaniment_path" in result


# ---------------------------------------------------------------------------
# Integration test for the ffmpeg decode path itself.
#
# Requires real torch (not the conftest MagicMock stub) because _write_wav
# calls tensor.detach().cpu().numpy(). Skipped in the lightweight test env.
# ---------------------------------------------------------------------------
requires_torch = pytest.mark.skipif(
    _real_torch is None, reason="Requires real torch (backend venv)"
)


@pytest.fixture
def stereo_mp3(tmp_path):
    import imageio_ffmpeg

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    path = tmp_path / "silence.mp3"
    subprocess.run(
        [
            ffmpeg, "-y", "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "2", "-c:a", "libmp3lame",
            str(path),
        ],
        check=True, capture_output=True,
    )
    return str(path)


@requires_torch
def test_decode_mp3_shape_and_dtype(stereo_mp3):
    audio = vocal_separator._decode_audio_ffmpeg(stereo_mp3, sampling_rate=44100, channels=2)
    assert audio.dtype == np.float32
    assert audio.shape[0] == 2
    # 2 s × 44100 Hz; MP3 encoder adds ~10 ms padding
    assert abs(audio.shape[1] - 88200) < 441


@requires_torch
def test_write_wav_round_trip(stereo_mp3, tmp_path):
    audio = vocal_separator._decode_audio_ffmpeg(stereo_mp3, sampling_rate=44100, channels=2)
    out = tmp_path / "out.wav"
    vocal_separator._write_wav(str(out), _real_torch.from_numpy(audio), 44100)
    assert out.exists() and out.stat().st_size > 0

    back = vocal_separator._decode_audio_ffmpeg(str(out), sampling_rate=44100, channels=2)
    assert back.shape == audio.shape
    assert back.dtype == np.float32


@requires_torch
def test_decode_ffmpeg_error_raises(tmp_path):
    bogus = tmp_path / "not-audio.txt"
    bogus.write_text("not an audio file")
    with pytest.raises(RuntimeError, match="ffmpeg failed to decode audio"):
        vocal_separator._decode_audio_ffmpeg(str(bogus), sampling_rate=44100, channels=2)


@patch("vocal_separator._clear_torch_hub_checkpoints")
@patch("vocal_separator._report_progress")
@patch("demucs.pretrained.get_model")
def test_hash_mismatch_clears_cache_and_retries(mock_get_model, mock_progress, mock_clear):
    """First get_model() fails with 'invalid hash value'; retry succeeds after cache clear."""
    good = MagicMock()
    mock_get_model.side_effect = [
        RuntimeError('invalid hash value (expected "8726e21a", got "b5c5614d")'),
        good,
    ]
    model = vocal_separator._get_model()
    assert model is good
    assert mock_get_model.call_count == 2
    mock_clear.assert_called_once()
    good.eval.assert_called_once()


@patch("vocal_separator._clear_torch_hub_checkpoints")
@patch("vocal_separator._report_progress")
@patch("demucs.pretrained.get_model")
def test_non_hash_runtime_error_propagates(mock_get_model, mock_progress, mock_clear):
    """RuntimeErrors unrelated to hash mismatch are not retried."""
    mock_get_model.side_effect = RuntimeError("unrelated CUDA error")
    with pytest.raises(RuntimeError, match="unrelated CUDA error"):
        vocal_separator._get_model()
    assert mock_get_model.call_count == 1
    mock_clear.assert_not_called()
