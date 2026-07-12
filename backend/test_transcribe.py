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


class TestFindUnattributedVocalRegions:
    """Energy-gap detection driving the ad-lib rescan (pure numpy, no model)."""

    SR = 16000

    def _audio(self, seconds, hot_windows, level=0.3):
        import numpy as np
        n = int(seconds * self.SR)
        rng = np.random.default_rng(3)
        x = np.zeros(n, dtype=np.float32)
        for a, b in hot_windows:
            x[int(a * self.SR):int(b * self.SR)] = level * rng.standard_normal(
                int(b * self.SR) - int(a * self.SR)
            ).astype(np.float32)
        return x

    def _words(self, spans):
        return [{"word": "w", "start": a, "end": b, "confidence": 0.9} for a, b in spans]

    def test_uncovered_energy_found(self):
        from transcribe import find_unattributed_vocal_regions
        # words cover 0-4s and 8-12s; hot vocals also at 5.5-6.5 (the ad-lib)
        audio = self._audio(12, [(0, 4), (5.5, 6.5), (8, 12)])
        regions = find_unattributed_vocal_regions(self._words([(0, 4), (8, 12)]), audio)
        assert len(regions) == 1
        a, b = regions[0]
        assert 5.2 <= a <= 5.8 and 6.2 <= b <= 6.8

    def test_covered_energy_ignored(self):
        from transcribe import find_unattributed_vocal_regions
        audio = self._audio(8, [(0, 8)])
        regions = find_unattributed_vocal_regions(self._words([(0, 8)]), audio)
        assert regions == []

    def test_silence_gap_ignored(self):
        from transcribe import find_unattributed_vocal_regions
        audio = self._audio(12, [(0, 4), (8, 12)])  # nothing sung in the gap
        regions = find_unattributed_vocal_regions(self._words([(0, 4), (8, 12)]), audio)
        assert regions == []

    def test_intermittent_phrase_closed_into_one_region(self):
        from transcribe import find_unattributed_vocal_regions
        # ad-lib with breath gaps: 3 islands 0.25s apart (measured S.M.D shape)
        audio = self._audio(12, [(0, 4), (5.0, 5.3), (5.55, 5.85), (6.1, 6.5), (8, 12)])
        regions = find_unattributed_vocal_regions(self._words([(0, 4), (8, 12)]), audio)
        assert len(regions) == 1
        a, b = regions[0]
        assert b - a >= 1.2, f"islands not merged: {regions}"

    def test_long_region_capped(self):
        from transcribe import find_unattributed_vocal_regions, _RESCAN_MAX_REGION_S
        audio = self._audio(30, [(0, 2), (4, 26), (27, 30)])
        regions = find_unattributed_vocal_regions(self._words([(0, 2), (27, 30)]), audio)
        assert regions and all(b - a <= _RESCAN_MAX_REGION_S + 1e-6 for a, b in regions)

    def test_empty_inputs(self):
        import numpy as np
        from transcribe import find_unattributed_vocal_regions
        assert find_unattributed_vocal_regions([], np.zeros(0, dtype=np.float32)) == []
