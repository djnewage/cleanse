"""Downbeat + BPM detection -> Beatgrid (production path for the auto intro/outro
feature).

This is the productionized form of the throwaway spike
(backend/spikes/beatgrid_spike.py); that spike will be removed once the feature
is fully wired. Detection uses madmom's DBNDownBeatTrackingProcessor — the gold
standard for the downbeat ("the 1"), which is the linchpin of the feature.

PACKAGING NOTE: madmom 0.16.1 (PyPI) builds a working wheel against numpy<2 but
is NOT yet declared in requirements.txt — it needs `pip install cython wheel`
then `pip install --no-build-isolation madmom`, which a plain `pip install -r`
can't express. Wiring it into the build is a deliberate packaging step. It also
predates Python 3.10 / numpy 1.24, so the compat shims below MUST run before
madmom is imported, and one numpy-incompatible line in the DBN tracker is
patched at import time.

The grid source is intentionally swappable: detect_beatgrid() returns the same
Beatgrid shape a Serato import would, so downstream DSP is source-agnostic.
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

import os
import tempfile

from scipy.io import wavfile

from intro_outro import Beatgrid
from vocal_separator import _decode_audio_ffmpeg

import madmom.features.downbeats as _db
from madmom.features.downbeats import (
    RNNDownBeatProcessor,
    DBNDownBeatTrackingProcessor,
    _process_dbn,
)

ANALYSIS_SR = 44100  # matches htdemucs / the rest of the pipeline


def _patched_dbn_process(self, activations, **kwargs):
    """madmom's DBNDownBeatTrackingProcessor.process with the one numpy>=1.24
    incompatibility fixed: `np.asarray(results)[:, 1]` raises on the ragged list
    of (path, log_prob) tuples, so pick the best HMM from a plain list instead."""
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
    best = int(np.argmax([log_prob for _, log_prob in results]))  # FIX
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


def detect_beatgrid(path: str, sample_rate: int = ANALYSIS_SR) -> Beatgrid:
    """Detect BPM + downbeat sample positions for a track. v1: assumes 4/4.

    NOTE (verified during the spike): reliable on rhythmically strong material,
    but can lock the wrong grid on soft/ambiguous tracks — the feature's preview
    + manual downbeat override is therefore required, not optional.
    """
    audio = _decode_audio_ffmpeg(path, sampling_rate=sample_rate, channels=1)
    mono = audio[0]
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
        wav_path = tf.name
    try:
        wavfile.write(wav_path, sample_rate, np.clip(mono, -1.0, 1.0).astype(np.float32))
        act = RNNDownBeatProcessor()(wav_path)
        beats = DBNDownBeatTrackingProcessor(beats_per_bar=[4], fps=100)(act)
    finally:
        os.unlink(wav_path)

    beat_times = [float(t) for t, _ in beats]
    downbeat_times = [float(t) for t, pos in beats if int(round(pos)) == 1]
    bpm = 60.0 / float(np.median(np.diff(beat_times))) if len(beat_times) > 1 else float("nan")
    return Beatgrid(
        bpm=round(bpm, 2),
        sample_rate=sample_rate,
        downbeats_samples=[int(round(t * sample_rate)) for t in downbeat_times],
        beats_samples=[int(round(t * sample_rate)) for t in beat_times],
        source="detected",
    )
