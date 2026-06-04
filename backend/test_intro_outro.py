"""Tests for intro_outro: bar math, loop-source picking, and seamless tiling."""

import numpy as np
import pytest

from intro_outro import (
    Beatgrid,
    build_beat_loop,
    pick_loop_source,
    seam_discontinuity,
    assemble_edit,
    _crossfade_join,
    load_stem,
    write_wav,
)

SR = 44100


def _grid(bpm: float, n_bars: int, sr: int = SR) -> tuple[Beatgrid, int]:
    """A perfectly steady grid; returns the grid and its bar length in samples."""
    spb = int(round((60.0 / bpm) * 4 * sr))
    downbeats = [i * spb for i in range(n_bars + 1)]
    return Beatgrid(bpm=bpm, sample_rate=sr, downbeats_samples=downbeats), spb


def _sine_stem(n: int, freq: float = 110.0, sr: int = SR, ch: int = 2) -> np.ndarray:
    x = (0.6 * np.sin(2 * np.pi * freq * np.arange(n) / sr)).astype(np.float32)
    return np.repeat(x[:, None], ch, axis=1)


class TestBarMath:
    def test_samples_per_bar(self):
        grid, _ = _grid(120.0, 8)
        # 120 BPM -> 0.5 s/beat -> 2.0 s/bar -> 88200 samples
        assert grid.samples_per_bar() == pytest.approx(88200.0)


class TestTiling:
    def test_length_is_exact_total_bars(self):
        grid, spb = _grid(128.0, 32)
        stem = _sine_stem(grid.downbeats_samples[-1] + spb)
        out = build_beat_loop(stem, grid, source_idx=0, loop_bars=2, total_bars=16)
        loop_len = grid.downbeats_samples[2] - grid.downbeats_samples[0]
        assert out.shape[0] == (16 // 2) * loop_len  # exact, no drift

    def test_total_must_be_multiple_of_loop_bars(self):
        grid, spb = _grid(120.0, 16)
        stem = _sine_stem(grid.downbeats_samples[-1] + spb)
        with pytest.raises(ValueError, match="multiple of loop_bars"):
            build_beat_loop(stem, grid, source_idx=0, loop_bars=4, total_bars=10)

    def test_source_past_end_raises(self):
        grid, spb = _grid(120.0, 4)
        stem = _sine_stem(grid.downbeats_samples[-1] + spb)
        with pytest.raises(ValueError, match="past the last"):
            build_beat_loop(stem, grid, source_idx=3, loop_bars=2, total_bars=8)

    def test_seam_is_click_free(self):
        """The sample step at each tile boundary must not be an outlier vs. the
        signal's normal steps — a click would show up as a large discontinuity."""
        grid, spb = _grid(124.0, 24)
        stem = _sine_stem(grid.downbeats_samples[-1] + spb, freq=90.0)
        loop_bars, total_bars = 2, 16
        out = build_beat_loop(stem, grid, source_idx=0, loop_bars=loop_bars, total_bars=total_bars)

        loop_len = grid.downbeats_samples[loop_bars] - grid.downbeats_samples[0]
        n_tiles = total_bars // loop_bars
        seam = seam_discontinuity(out, loop_len, n_tiles)

        mono = out.mean(axis=1)
        normal_steps = np.abs(np.diff(mono))
        # seam step should be on the order of normal steps, not a spike
        assert seam <= 5 * float(np.percentile(normal_steps, 99.9))

    def test_tiled_output_is_finite_and_bounded(self):
        grid, spb = _grid(140.0, 16)
        stem = _sine_stem(grid.downbeats_samples[-1] + spb)
        out = build_beat_loop(stem, grid, source_idx=0, loop_bars=4, total_bars=8)
        assert np.all(np.isfinite(out))
        assert np.max(np.abs(out)) <= 1.0


class TestPickLoopSource:
    def test_picks_first_full_energy_bar(self):
        """First two bars are silent, the rest are loud -> picker should skip to
        the first strong 2-bar window (index 2)."""
        grid, spb = _grid(120.0, 6)
        stem = _sine_stem(grid.downbeats_samples[-1])
        # silence the first two bars
        stem[: grid.downbeats_samples[2]] = 0.0
        idx = pick_loop_source(stem, grid, loop_bars=2, energy_quantile=0.6)
        assert idx == 2

    def test_returns_zero_when_too_few_bars(self):
        grid, _ = _grid(120.0, 1)
        stem = _sine_stem(grid.downbeats_samples[-1])
        assert pick_loop_source(stem, grid, loop_bars=2) == 0


class TestAssembleEdit:
    def test_intro_then_body_structure(self):
        """Intro beats prepend the original body, which enters on the drop downbeat."""
        grid, spb = _grid(120.0, 32)
        n = grid.downbeats_samples[-1] + spb
        # distinct signals so we can tell intro (loop) from body (original)
        loop_stem = _sine_stem(n, freq=110.0)
        original = _sine_stem(n, freq=440.0)

        res = assemble_edit(
            original, loop_stem, grid,
            loop_source_idx=4, loop_bars=2, intro_bars=8, drop_idx=4,
        )
        loop_len = grid.downbeats_samples[6] - grid.downbeats_samples[4]
        intro_len = (8 // 2) * loop_len
        body_len = len(original) - grid.downbeats_samples[4]
        # length ~= intro + body minus one crossfade overlap
        assert abs(res.audio.shape[0] - (intro_len + body_len)) <= int(0.01 * SR)
        assert res.drop_sample is not None and res.drop_sample > 0
        assert np.all(np.isfinite(res.audio))

    def test_body_is_the_original_not_the_stem(self):
        """The body region must come from `original`, never the loop stem."""
        grid, spb = _grid(120.0, 16)
        n = grid.downbeats_samples[-1] + spb
        loop_stem = np.zeros((n, 2), dtype=np.float32)          # silent stem
        original = _sine_stem(n, freq=440.0)                    # audible original

        res = assemble_edit(
            original, loop_stem, grid,
            loop_source_idx=2, loop_bars=2, intro_bars=4, drop_idx=2,
        )
        # well past the drop, audio must be the (audible) original, not silence
        tail = res.audio[res.drop_sample + SR:]
        assert np.max(np.abs(tail)) > 0.1

    def test_outro_requires_index(self):
        grid, spb = _grid(120.0, 16)
        n = grid.downbeats_samples[-1] + spb
        stem = _sine_stem(n)
        with pytest.raises(ValueError, match="outro_idx is required"):
            assemble_edit(stem, stem, grid, loop_source_idx=0, intro_bars=4, outro_bars=4)

    def test_full_intro_body_outro(self):
        grid, spb = _grid(128.0, 40)
        n = grid.downbeats_samples[-1] + spb
        loop_stem = _sine_stem(n, freq=110.0)
        original = _sine_stem(n, freq=440.0)
        res = assemble_edit(
            original, loop_stem, grid,
            loop_source_idx=2, loop_bars=2,
            intro_bars=8, drop_idx=2,
            outro_bars=8, outro_idx=30,
        )
        assert res.drop_sample is not None and res.outro_sample is not None
        assert res.outro_sample > res.drop_sample
        assert np.max(np.abs(res.audio)) <= 1.0

    def test_crossfade_join_declicks(self):
        """A join between two offset DC-ish blocks should not leave a hard step."""
        a = np.ones((1000, 1), dtype=np.float32) * 0.5
        b = np.ones((1000, 1), dtype=np.float32) * -0.5
        c = 64
        joined = _crossfade_join(a, b, c)
        # max step anywhere should be far below the raw 1.0 butt-join discontinuity
        assert float(np.max(np.abs(np.diff(joined[:, 0])))) < 0.1


class TestIO:
    def test_wav_round_trip(self, tmp_path):
        out = str(tmp_path / "loop.wav")
        audio = _sine_stem(SR)  # 1 s stereo
        write_wav(out, audio, SR)
        back, sr = load_stem(out)
        assert sr == SR
        assert back.shape == audio.shape
        assert np.max(np.abs(back - audio)) < 1e-3  # 16-bit quantization tolerance
