"""Auto intro/outro DJ edits — beat-loop construction (grid-agnostic DSP).

This module builds the looped beat used for a phrase-aligned intro/outro. It is
deliberately decoupled from how the beatgrid is obtained: it consumes a
``Beatgrid`` (BPM + downbeat sample positions) that may be DETECTED (madmom) or
IMPORTED (Serato) — same shape either way (see docs/auto-intro-outro-spec.md).

v1 scope: 4/4, steady tempo, drums-only or drums+bass loop. The body of the edit
is the untouched ORIGINAL audio (assembled elsewhere); only the intro/outro loop
is stem-derived, so the main track inherits zero separation artifacts.

Audio convention in this module: float32 arrays shaped [samples, channels]
(matches scipy.io.wavfile), mono or stereo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.io import wavfile


@dataclass
class Beatgrid:
    """BPM + downbeat positions. Identical shape whether detected or Serato-imported."""
    bpm: float
    sample_rate: int
    downbeats_samples: list[int]            # sample index of each bar's "1", ascending
    source: str = "detected"               # "detected" | "serato"
    beats_samples: list[int] = field(default_factory=list)  # optional: all beats

    def samples_per_bar(self) -> float:
        """Exact 4/4 bar length in samples implied by the BPM."""
        return (60.0 / self.bpm) * 4 * self.sample_rate


def load_stem(path: str) -> tuple[np.ndarray, int]:
    """Read a stem WAV as float32 [samples, channels] in [-1, 1], with its rate."""
    sr, data = wavfile.read(path)
    if data.ndim == 1:
        data = data[:, None]
    if np.issubdtype(data.dtype, np.integer):
        data = data.astype(np.float32) / float(np.iinfo(data.dtype).max)
    else:
        data = data.astype(np.float32)
    return data, sr


def write_wav(path: str, audio: np.ndarray, sample_rate: int) -> None:
    """Write float32 [samples, channels] (or [samples]) to 16-bit PCM WAV."""
    if audio.ndim == 1:
        audio = audio[:, None]
    wavfile.write(path, sample_rate, (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16))


def _bar_rms(stem: np.ndarray, downbeats: list[int]) -> np.ndarray:
    """RMS of each bar (between consecutive downbeats), averaged across channels."""
    out = []
    for a, b in zip(downbeats[:-1], downbeats[1:]):
        seg = stem[a:b]
        out.append(float(np.sqrt(np.mean(seg.astype(np.float64) ** 2))) if len(seg) else 0.0)
    return np.asarray(out)


def pick_loop_source(
    stem: np.ndarray, grid: Beatgrid, loop_bars: int = 2, energy_quantile: float = 0.6
) -> int:
    """Pick the source loop start: the first downbeat where the drum stem is at
    'full energy' (per the spec's first-strong-bar default).

    Returns an index into ``grid.downbeats_samples``. The user can override this
    (the preview/manual nudge) — this is only the default.
    """
    db = grid.downbeats_samples
    if len(db) < loop_bars + 1:
        return 0
    bar_rms = _bar_rms(stem, db)
    # "full energy" = at/above the energy_quantile of all bars (ignoring silent bars)
    nonzero = bar_rms[bar_rms > 0]
    threshold = float(np.quantile(nonzero, energy_quantile)) if len(nonzero) else 0.0
    for i in range(len(bar_rms) - loop_bars + 1):
        if float(np.mean(bar_rms[i:i + loop_bars])) >= threshold:
            return i
    return 0


def _equal_power_ramps(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Equal-power fade-in / fade-out ramps of length n (sum of powers == 1)."""
    t = np.linspace(0.0, np.pi / 2, n, dtype=np.float32)
    return np.sin(t), np.cos(t)  # fade_in, fade_out


def build_beat_loop(
    stem: np.ndarray,
    grid: Beatgrid,
    source_idx: int,
    loop_bars: int,
    total_bars: int,
    crossfade_ms: float = 8.0,
) -> np.ndarray:
    """Tile a ``loop_bars`` phrase (starting at downbeat ``source_idx``) to fill
    ``total_bars``, click-free.

    Seam handling: each tile carries a few ms of the REAL audio that follows the
    loop end, and that tail is equal-power crossfaded over the next tile's head.
    Because the tail and head are consecutive same-phase downbeat audio, the join
    is click-free AND grid-exact — tiles are placed at a stride of the loop's true
    sample length (taken from the detected downbeats, an integer number of bars),
    so no drift accumulates and madmom's ~10 ms grid resolution can't compound.
    """
    if total_bars % loop_bars != 0:
        raise ValueError(f"total_bars ({total_bars}) must be a multiple of loop_bars ({loop_bars})")
    db = grid.downbeats_samples
    if source_idx + loop_bars >= len(db):
        raise ValueError("source loop extends past the last detected downbeat")

    start = db[source_idx]
    end = db[source_idx + loop_bars]
    loop_len = end - start                      # exact integer bars, from the grid
    c = max(1, int(round(crossfade_ms / 1000.0 * grid.sample_rate)))
    ch = stem.shape[1]

    # Segment = the loop plus a short real tail for the crossfade (clamped to audio).
    seg = stem[start:min(end + c, len(stem))]
    tail = len(seg) - loop_len                  # available crossfade samples (<= c)
    fade_in, fade_out = _equal_power_ramps(tail) if tail > 0 else (None, None)

    n_tiles = total_bars // loop_bars
    out = np.zeros((n_tiles * loop_len + max(tail, 0), ch), dtype=np.float32)

    for k in range(n_tiles):
        pos = k * loop_len
        piece = seg.copy()
        if tail > 0:
            # fade the overlapping tail down, and fade this tile's head up so it
            # blends with the previous tile's tail sitting in the same region
            piece[-tail:] *= fade_out[:, None]
            if k > 0:
                piece[:tail] *= fade_in[:, None]
        out[pos:pos + len(piece)] += piece

    # Trim to exactly total_bars (drop the trailing crossfade tail of the last tile).
    return out[: n_tiles * loop_len]


def seam_discontinuity(audio: np.ndarray, loop_len: int, n_tiles: int) -> float:
    """Max abs sample step exactly at the tile boundaries — a click-free loop keeps
    this comparable to the audio's normal sample-to-sample steps. (Test/QA helper.)"""
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    steps = []
    for k in range(1, n_tiles):
        i = k * loop_len
        if 0 < i < len(mono):
            steps.append(abs(float(mono[i] - mono[i - 1])))
    return max(steps) if steps else 0.0
