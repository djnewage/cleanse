"""THROWAWAY SPIKE — beatgrid downbeat detection (NOT wired into the app).

De-risks the linchpin of the auto intro/outro feature: getting a sample-accurate
downbeat (the "1") for a track. Prints BPM + downbeat positions for a few sample
tracks and (optionally) writes a click-marked WAV so a human can EAR-CHECK that the
"1" lands on the real bar start.

Run:
    backend/venv/bin/python backend/spikes/beatgrid_spike.py TRACK1 [TRACK2 ...] [--click]

Notes / caveats (why this is a spike, not production):
  * Uses madmom 0.16.1 (PyPI), which predates Python 3.10 / numpy 1.24. We apply
    import-time compat shims below and monkeypatch one numpy-incompatible line in
    DBNDownBeatTrackingProcessor.process. Productionizing should instead pin a
    patched/git madmom or vendor these fixes deliberately.
  * v1 scope: assumes 4/4, steady tempo (per spec). The spike only REPORTS; it does
    not enforce or correct tempo drift.
  * Designed so a Serato-imported grid can populate the same Beatgrid shape later
    (source="serato") without changing any downstream DSP.
"""

from __future__ import annotations

# --- madmom 0.16.1 compat shims: MUST run before importing madmom ----------------
import collections
import collections.abc
for _n in ("MutableSequence", "MutableMapping", "Sequence", "Mapping", "Iterable", "Callable"):
    if not hasattr(collections, _n):
        setattr(collections, _n, getattr(collections.abc, _n))

import numpy as np
for _n, _t in (("float", float), ("int", int), ("bool", bool), ("object", object), ("complex", complex)):
    if not hasattr(np, _n):
        setattr(np, _n, _t)
# --------------------------------------------------------------------------------

import argparse
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

from scipy.io import wavfile

# Reuse the app's existing ffmpeg decode (handles MP3/M4A/WAV/AIFF) — no new path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vocal_separator import _decode_audio_ffmpeg  # noqa: E402

import madmom.features.downbeats as _db  # noqa: E402
from madmom.features.downbeats import (  # noqa: E402
    RNNDownBeatProcessor,
    DBNDownBeatTrackingProcessor,
    _process_dbn,
)

ANALYSIS_SR = 44100  # matches htdemucs / the app's working sample rate


def _patched_dbn_process(self, activations, **kwargs):
    """Copy of madmom's DBNDownBeatTrackingProcessor.process with the one
    numpy>=1.24 incompatibility fixed (ragged np.asarray on the HMM results).

    Only line changed vs. upstream: pick the best HMM via a plain list of
    log-probs instead of np.asarray(results)[:, 1], which now raises on ragged
    (array, scalar) tuples.
    """
    import itertools as it
    first = 0
    if self.threshold:
        idx = np.nonzero(activations >= self.threshold)[0]
        if idx.any():
            first = max(first, np.min(idx))
            last = min(len(activations), np.max(idx) + 1)
        else:
            last = first
        activations = activations[first:last]
    if not activations.any():
        return np.empty((0, 2))
    results = list(self.map(_process_dbn, zip(self.hmms, it.repeat(activations))))
    # --- FIX: was `np.argmax(np.asarray(results)[:, 1])` (ragged -> ValueError) ---
    best = int(np.argmax([log_prob for _, log_prob in results]))
    path, _ = results[best]
    st = self.hmms[best].transition_model.state_space
    om = self.hmms[best].observation_model
    positions = st.state_positions[path]
    beat_numbers = positions.astype(int) + 1
    if self.correct:
        beats = np.empty(0, dtype=int)
        beat_range = om.pointers[path] >= 1
        idx = np.nonzero(np.diff(beat_range.astype(int)))[0] + 1
        if beat_range[0]:
            idx = np.r_[0, idx]
        if beat_range[-1]:
            idx = np.r_[idx, beat_range.size]
        if idx.any():
            for left, right in idx.reshape((-1, 2)):
                peak = np.argmax(activations[left:right]) // 2 + left
                beats = np.hstack((beats, peak))
    else:
        beats = np.nonzero(np.diff(beat_numbers))[0] + 1
    return np.vstack(((beats + first) / float(self.fps), beat_numbers[beats])).T


DBNDownBeatTrackingProcessor.process = _patched_dbn_process


@dataclass
class Beatgrid:
    """Grid result. Same shape whether detected here or imported from Serato later."""
    bpm: float
    sample_rate: int
    downbeats_samples: list[int]          # sample index of each bar's "1"
    downbeats_sec: list[float]
    beats_sec: list[float] = field(default_factory=list)  # all beats (for sanity checks)
    source: str = "detected"              # "detected" | "serato"


def detect_beatgrid(path: str, sample_rate: int = ANALYSIS_SR) -> Beatgrid:
    """Detect BPM + downbeat positions for a track using madmom's DBN tracker."""
    # Decode to mono float32 at the analysis SR, then hand madmom a temp WAV
    # (avoids madmom's own MP3-decoding path, which is unreliable on this stack).
    audio = _decode_audio_ffmpeg(path, sampling_rate=sample_rate, channels=1)
    mono = audio[0]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        wav_path = tf.name
    try:
        wavfile.write(wav_path, sample_rate, np.clip(mono, -1.0, 1.0).astype(np.float32))
        act = RNNDownBeatProcessor()(wav_path)
        tracker = DBNDownBeatTrackingProcessor(beats_per_bar=[4], fps=100)
        beats = tracker(act)  # rows: [time_sec, position_in_bar (1..4)]
    finally:
        os.unlink(wav_path)

    beat_times = [float(t) for t, _ in beats]
    downbeat_times = [float(t) for t, pos in beats if int(round(pos)) == 1]
    if len(beat_times) > 1:
        bpm = 60.0 / float(np.median(np.diff(beat_times)))
    else:
        bpm = float("nan")
    return Beatgrid(
        bpm=round(bpm, 2),
        sample_rate=sample_rate,
        downbeats_samples=[int(round(t * sample_rate)) for t in downbeat_times],
        downbeats_sec=[round(t, 4) for t in downbeat_times],
        beats_sec=[round(t, 4) for t in beat_times],
        source="detected",
    )


def _voice_one_cue(sr: int) -> np.ndarray:
    """A spoken 'one' marker (macOS `say`). Categorically non-musical so it can't
    be confused with the track's own percussion when ear-checking the downbeat."""
    import tempfile
    aiff = tempfile.mktemp(suffix=".aiff")
    try:
        subprocess.run(["say", "-r", "300", "-o", aiff, "one"], check=True, capture_output=True)
        cue = _decode_audio_ffmpeg(aiff, sampling_rate=sr, channels=1)[0]
    finally:
        if os.path.exists(aiff):
            os.unlink(aiff)
    peak = float(np.max(np.abs(cue))) or 1.0
    return (cue / peak * 0.95).astype(np.float32)


def write_click_track(path: str, grid: Beatgrid, out_path: str) -> None:
    """Overlay a spoken 'one' on the ORIGINAL audio at each detected downbeat so a
    human can ear-check the '1'. The music is ducked hard under each marker so the
    voice is unmistakable even on dense, hat-heavy masters. Stereo/44.1k/16-bit."""
    audio = _decode_audio_ffmpeg(path, sampling_rate=grid.sample_rate, channels=2)
    mix = audio.T.copy()  # [samples, 2]
    sr = grid.sample_rate

    cue = _voice_one_cue(sr)
    n = len(cue)
    duck = np.full(n, 0.18, dtype=np.float32)  # ~-15 dB bed under the spoken marker

    for s in grid.downbeats_samples:
        if s >= len(mix):
            continue
        e = min(s + n, len(mix))
        mix[s:e] *= duck[: e - s, None]
        mix[s:e, 0] += cue[: e - s]
        mix[s:e, 1] += cue[: e - s]
    wavfile.write(out_path, sr, (np.clip(mix, -1, 1) * 32767).astype(np.int16))


def _summarize(grid: Beatgrid) -> None:
    print(f"  BPM (median): {grid.bpm}")
    print(f"  downbeats found: {len(grid.downbeats_samples)}")
    if len(grid.downbeats_sec) >= 2:
        deltas = np.diff(grid.downbeats_sec)
        bar_from_bpm = (60.0 / grid.bpm) * 4 if grid.bpm == grid.bpm else float("nan")
        print(f"  bar length: detected ~{np.median(deltas):.3f}s vs BPM-implied {bar_from_bpm:.3f}s")
        print(f"  downbeat spacing min/max: {deltas.min():.3f}s / {deltas.max():.3f}s (steady => tight)")
    head = list(zip(grid.downbeats_sec[:8], grid.downbeats_samples[:8]))
    print(f"  first downbeats (sec, sample): {head}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Beatgrid downbeat detection spike")
    ap.add_argument("tracks", nargs="+", help="audio file paths")
    ap.add_argument("--click", action="store_true", help="also write *_clicks.wav for ear-checking")
    args = ap.parse_args()

    for path in args.tracks:
        print(f"\n=== {os.path.basename(path)} ===")
        if not os.path.isfile(path):
            print("  !! file not found")
            continue
        try:
            grid = detect_beatgrid(path)
        except Exception as e:  # spike: surface failures loudly, keep going
            print(f"  !! detection failed: {type(e).__name__}: {e}")
            continue
        _summarize(grid)
        if args.click:
            out = os.path.splitext(path)[0] + "_clicks.wav"
            write_click_track(path, grid, out)
            print(f"  wrote click track: {out}")


if __name__ == "__main__":
    main()
