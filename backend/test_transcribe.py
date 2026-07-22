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

    def test_long_region_split_not_truncated(self):
        # A 20s+ missed stretch (e.g. an outro the primary pass dropped) must
        # be chunked into cap-sized slices covering ALL of it — truncating to
        # the first slice silently loses the tail's profanity.
        from transcribe import find_unattributed_vocal_regions, _RESCAN_MAX_REGION_S
        audio = self._audio(30, [(0, 2), (4, 26), (27, 30)])
        regions = find_unattributed_vocal_regions(self._words([(0, 2), (27, 30)]), audio)
        assert regions and all(b - a <= _RESCAN_MAX_REGION_S + 1e-6 for a, b in regions)
        assert regions[-1][1] >= 25.0, f"tail discarded: {regions}"
        for (_, prev_end), (next_start, _) in zip(regions, regions[1:]):
            assert next_start - prev_end < 0.5, f"coverage hole: {regions}"

    def test_empty_inputs(self):
        import numpy as np
        from transcribe import find_unattributed_vocal_regions
        assert find_unattributed_vocal_regions([], np.zeros(0, dtype=np.float32)) == []

    def test_stretched_word_suppresses_region_until_clamped(self):
        """The DJ Fly mashup bug: a timestamp-stretched word blankets ad-lib
        energy, so no region is found — until clamp_stretched_words frees it."""
        from transcribe import clamp_stretched_words, find_unattributed_vocal_regions
        # Real vocals 0-2s, ad-libs 3.5-7s; one word stretched across all of it,
        # plus normal covered words so the active-RMS reference is sane.
        audio = self._audio(12, [(0, 2), (3.5, 7), (8, 12)])
        words = self._words([(0, 1), (1, 2)]) + [
            {"word": "and", "start": 0.5, "end": 7.0, "confidence": 0.9}
        ] + self._words([(8, 10), (10, 12)])
        assert find_unattributed_vocal_regions(words, audio) == []
        regions = find_unattributed_vocal_regions(clamp_stretched_words(words), audio)
        assert len(regions) == 1
        a, b = regions[0]
        assert a <= 4.0 and b >= 6.5, f"freed ad-lib tail not detected: {regions}"


class TestClampStretchedWords:
    def _word(self, text, start, end, is_profanity=False):
        return {
            "word": text, "start": start, "end": end,
            "confidence": 0.9, "is_profanity": is_profanity,
        }

    def test_stretched_word_clamped(self):
        # The measured case: 'and' spanning 64.92-70.18 over ad-lib repeats.
        from transcribe import clamp_stretched_words
        out = clamp_stretched_words([self._word("and", 64.92, 70.18)])
        assert out[0]["end"] == 66.92
        assert out[0]["start"] == 64.92

    def test_normal_words_untouched(self):
        from transcribe import clamp_stretched_words
        words = [
            self._word("hey", 0.0, 0.4),
            self._word("looove", 1.0, 3.0),  # exactly 2.0s: allowed
            self._word("yo", 3.5, 3.9),
        ]
        out = clamp_stretched_words(words)
        assert [(w["word"], w["start"], w["end"]) for w in out] == [
            ("hey", 0.0, 0.4), ("looove", 1.0, 3.0), ("yo", 3.5, 3.9),
        ]

    def test_profanity_exempt(self):
        # Shortening a flagged word's end would shorten its mute.
        from transcribe import clamp_stretched_words
        out = clamp_stretched_words([self._word("fuck", 10.0, 15.0, is_profanity=True)])
        assert out[0]["end"] == 15.0

    def test_input_not_mutated(self):
        from transcribe import clamp_stretched_words
        words = [self._word("and", 64.92, 70.18)]
        clamp_stretched_words(words)
        assert words[0]["end"] == 70.18

    def test_interplay_with_collapse(self):
        # Mirrors the real call order: collapse_repetition_loops runs inside
        # transcribe_audio, clamp runs later in main — a crammed repetition run
        # is collapsed and an independent stretched word still gets clamped.
        from transcribe import clamp_stretched_words, collapse_repetition_loops
        crammed = [
            self._word(t, 5.0 + i * 0.05, 5.0 + i * 0.05 + 0.04)
            for i, t in enumerate(["dope", "shit"] * 6)
        ]
        stretched = [self._word("and", 20.0, 26.0)]
        out = clamp_stretched_words(collapse_repetition_loops(crammed + stretched))
        assert len(out) < len(crammed) + 1
        and_w = [w for w in out if w["word"] == "and"][0]
        assert and_w["end"] == 22.0
        assert [w["start"] for w in out] == sorted(w["start"] for w in out)
