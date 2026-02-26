"""Tests for transcribe: get_model caching and MPS handling."""

import sys
from unittest.mock import MagicMock, patch

# Heavy deps (faster_whisper, torch) are stubbed in conftest.py.
import transcribe

# Pin a single WhisperModel mock on the faster_whisper stub so we can track calls.
_whisper_model_mock = MagicMock()
sys.modules["faster_whisper"].WhisperModel = _whisper_model_mock


class TestGetModel:
    def setup_method(self):
        """Reset cached model and WhisperModel mock between tests."""
        transcribe._model = None
        transcribe._model_turbo = False
        _whisper_model_mock.reset_mock()

    def test_returns_cached_model_on_same_turbo(self):
        fake_model = MagicMock()
        transcribe._model = fake_model
        transcribe._model_turbo = False

        result = transcribe.get_model(turbo=False)
        assert result is fake_model
        _whisper_model_mock.assert_not_called()  # Should not reload

    def test_cache_miss_when_turbo_changes(self):
        """Changing the turbo flag should reload the model, not return the cache."""
        fake_model_v1 = MagicMock()
        transcribe._model = fake_model_v1
        transcribe._model_turbo = False

        with patch("device_info.get_device_string", return_value="cpu"):
            result = transcribe.get_model(turbo=True)

        assert result is not fake_model_v1
        assert transcribe._model_turbo is True
        _whisper_model_mock.assert_called_once()

    def test_turbo_with_mps_uses_cpu(self):
        """MPS is not supported by CTranslate2 -- turbo+MPS should use CPU."""
        with patch("device_info.get_device_string", return_value="mps"):
            transcribe.get_model(turbo=True)

        _whisper_model_mock.assert_called_once_with("medium", device="cpu", compute_type="int8")

    def test_turbo_with_cuda_uses_cuda(self):
        """CUDA should be used directly with float16 in turbo mode."""
        with patch("device_info.get_device_string", return_value="cuda"):
            transcribe.get_model(turbo=True)

        _whisper_model_mock.assert_called_once_with("medium", device="cuda", compute_type="float16")

    def test_non_turbo_with_cuda(self):
        """Non-turbo CUDA should use int8_float16 mixed precision."""
        with patch("device_info.detect_device", return_value={
            "device_type": "cuda", "gpu_available": True, "turbo_supported": True, "device_name": "GPU"
        }):
            transcribe.get_model(turbo=False)

        _whisper_model_mock.assert_called_once_with("medium", device="cuda", compute_type="int8_float16")

    def test_non_turbo_with_mps_uses_cpu(self):
        """Non-turbo on MPS should fall back to CPU (CTranslate2 doesn't support MPS)."""
        with patch("device_info.detect_device", return_value={
            "device_type": "mps", "gpu_available": True, "turbo_supported": True, "device_name": "Apple Silicon GPU"
        }):
            transcribe.get_model(turbo=False)

        _whisper_model_mock.assert_called_once_with("medium", device="cpu", compute_type="int8")
