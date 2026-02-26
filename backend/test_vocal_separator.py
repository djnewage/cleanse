"""Tests for MPS->CPU fallback logic in vocal_separator.separate()."""

import os
from unittest.mock import MagicMock, patch

import pytest

# Heavy deps (torch, torchaudio, demucs, tqdm) are stubbed in conftest.py.
# device_info is a lightweight local module — import it normally.
import sys
sys.modules.setdefault("device_info", MagicMock())

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
@patch("torchaudio.save")
@patch("torchaudio.load")
def test_mps_fallback_on_65536_error(
    mock_load, mock_save, mock_apply, mock_get_model, mock_device, mock_progress, tmp_path
):
    """apply_model raises NotImplementedError with '65536' on MPS, succeeds on CPU retry."""
    fake_wav = MagicMock()
    fake_wav.shape = [2, 44100]
    mock_load.return_value = (fake_wav, 44100)

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
@patch("torchaudio.save")
@patch("torchaudio.load")
def test_mps_fallback_on_mps_runtime_error(
    mock_load, mock_save, mock_apply, mock_get_model, mock_device, mock_progress, tmp_path
):
    """apply_model raises RuntimeError mentioning 'MPS' on MPS, succeeds on CPU retry."""
    fake_wav = MagicMock()
    fake_wav.shape = [2, 44100]
    mock_load.return_value = (fake_wav, 44100)

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
@patch("torchaudio.save")
@patch("torchaudio.load")
def test_no_fallback_when_already_on_cpu(
    mock_load, mock_save, mock_apply, mock_get_model, mock_device, mock_progress, tmp_path
):
    """When already on CPU, the 65536 error propagates (no infinite retry)."""
    fake_wav = MagicMock()
    fake_wav.shape = [2, 44100]
    mock_load.return_value = (fake_wav, 44100)

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
@patch("torchaudio.save")
@patch("torchaudio.load")
def test_unrelated_error_propagates(
    mock_load, mock_save, mock_apply, mock_get_model, mock_device, mock_progress, tmp_path
):
    """Unrelated RuntimeError (no '65536' or 'MPS') propagates unchanged."""
    fake_wav = MagicMock()
    fake_wav.shape = [2, 44100]
    mock_load.return_value = (fake_wav, 44100)

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
@patch("torchaudio.save")
@patch("torchaudio.load")
def test_successful_gpu_no_fallback(
    mock_load, mock_save, mock_apply, mock_get_model, mock_device, mock_progress, tmp_path
):
    """apply_model succeeds on first call -- no fallback, no model.to('cpu')."""
    fake_wav = MagicMock()
    fake_wav.shape = [2, 44100]
    mock_load.return_value = (fake_wav, 44100)

    model = MagicMock()
    model.samplerate = 44100
    mock_get_model.return_value = model

    mock_apply.return_value = _make_fake_sources()

    result = vocal_separator.separate("input.wav", str(tmp_path))

    assert mock_apply.call_count == 1
    model.to.assert_not_called()
    assert "vocals_path" in result
    assert "accompaniment_path" in result
