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

import os
from dataclasses import dataclass, field

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt, sosfilt_zi


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


def load_audio(path: str, sample_rate: int, channels: int = 2) -> np.ndarray:
    """Decode any audio file (MP3/M4A/WAV/AIFF) to float32 [samples, channels] at
    the given rate. Reuses the app's ffmpeg decode path (handles formats scipy
    cannot). Used to load the untouched original body."""
    from vocal_separator import _decode_audio_ffmpeg
    return _decode_audio_ffmpeg(path, sampling_rate=sample_rate, channels=channels).T.copy()


def write_wav(path: str, audio: np.ndarray, sample_rate: int) -> None:
    """Write float32 [samples, channels] (or [samples]) to 16-bit PCM WAV."""
    if audio.ndim == 1:
        audio = audio[:, None]
    wavfile.write(path, sample_rate, (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16))


# Lossless render targets. AIFF/FLAC carry full ID3/Vorbis tags incl. cover art;
# WAV is lossless but a poor tag container (no reliable embedded artwork).
_PCM_CODEC = {"wav": "pcm_s16le", "aiff": "pcm_s16be"}
_ART_FORMATS = {"aiff", "flac"}


def _edit_title(source_path: str, suffix: str) -> str:
    """Original title + suffix, e.g. 'Tony Soprano (Intro Edit)'. Falls back to the
    filename when the source has no title tag."""
    title = None
    try:
        from tinytag import TinyTag
        title = TinyTag.get(source_path).title
    except Exception:
        pass
    if not title:
        title = os.path.splitext(os.path.basename(source_path))[0]
    return f"{title} {suffix}".strip()


def render_edit(
    audio: np.ndarray,
    sample_rate: int,
    output_path: str,
    source_path: str,
    title_suffix: str = "(Intro Edit)",
) -> str:
    """Write the assembled edit to a lossless file, carrying the source's tags +
    cover art and appending ``title_suffix`` to the title.

    The audio is written as 16-bit PCM then remuxed via ffmpeg, copying all source
    metadata (-map_metadata, so BPM/key survive if tagged) and the embedded cover
    art (AIFF/FLAC only — WAV has no reliable art container), with the title
    overridden to the edit name. Mirrors the metadata-copy pattern used by the
    censor pipeline's _copy_metadata.
    """
    import subprocess
    import tempfile
    import imageio_ffmpeg

    ext = os.path.splitext(output_path)[1].lower().lstrip(".")
    ext = {"aif": "aiff"}.get(ext, ext)
    if ext not in _PCM_CODEC and ext != "flac":
        raise ValueError(f"Unsupported render format '{ext}'; use wav/aiff/flac")

    tmp = tempfile.mktemp(suffix=".wav")
    write_wav(tmp, audio, sample_rate)
    try:
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        want_art = ext in _ART_FORMATS
        cmd = [ff, "-y", "-i", tmp, "-i", source_path, "-map", "0:a"]
        if want_art:
            cmd += ["-map", "1:v:0?"]
        cmd += ["-c:a", _PCM_CODEC.get(ext, "flac")]
        if want_art:
            cmd += ["-c:v", "copy", "-disposition:v:0", "attached_pic"]
        cmd += ["-map_metadata", "1", "-metadata", f"title={_edit_title(source_path, title_suffix)}"]
        if ext in ("wav", "aiff"):
            cmd += ["-write_id3v2", "1"]
        cmd += [output_path]
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return output_path


def regularize_grid(grid: Beatgrid) -> Beatgrid:
    """Least-squares constant-tempo refit of the detected downbeats.

    madmom reports on a 100 fps lattice, so raw downbeats carry ±10 ms bar-to-bar
    jitter (measured: 1.62-1.71 s bars on a steady 142 BPM track). A loop cut
    between two jittered downbeats has the wrong length and audibly drifts over a
    16-bar intro. v1 scope is steady-tempo 4/4, so the right model is a straight
    line: downbeat[k] ~= phase + k * bar_len, fit with one outlier-rejection pass.
    Also yields a sub-millisecond BPM (the raw one is quantized: 142.86 = 60/0.42).

    Returns the original grid untouched if too few downbeats or the residuals say
    the tempo genuinely isn't steady (out of v1 scope — don't fake a grid).
    """
    db = np.asarray(grid.downbeats_samples, dtype=np.float64)
    if len(db) < 8:
        return grid
    k = np.arange(len(db), dtype=np.float64)
    bar_len, phase = np.polyfit(k, db, 1)
    resid = db - (phase + bar_len * k)
    # One robust pass: refit without outliers (a few mis-tracked bars shouldn't skew).
    mad = float(np.median(np.abs(resid))) or 1.0
    keep = np.abs(resid) <= 5 * mad
    if keep.sum() >= 8:
        bar_len, phase = np.polyfit(k[keep], db[keep], 1)
        resid = db - (phase + bar_len * k)
    if bar_len <= 0 or float(np.median(np.abs(resid))) > 0.03 * bar_len:
        return grid  # not steady tempo; keep the detected grid as-is
    new_db = np.maximum(np.round(phase + bar_len * k), 0).astype(int)
    beat_len = bar_len / 4.0
    new_beats = np.maximum(
        np.round(phase + beat_len * np.arange(len(db) * 4)), 0
    ).astype(int)
    return Beatgrid(
        bpm=round(60.0 * grid.sample_rate / beat_len, 2),
        sample_rate=grid.sample_rate,
        downbeats_samples=new_db.tolist(),
        beats_samples=new_beats.tolist(),
        source=grid.source,
    )


def snap_downbeats_to_transients(
    grid: Beatgrid,
    stem: np.ndarray,
    window_ms: float = 25.0,
    min_rise_ratio: float = 3.0,
    min_votes: int = 4,
) -> Beatgrid:
    """Phase-align the grid to the actual drum transients: shift ALL downbeats by
    the MEDIAN offset between each downbeat and the nearest onset within
    ±``window_ms`` (the spec's transient-snap requirement, applied globally).

    Phase-only on purpose. Snapping each downbeat independently lets two bars
    disagree (a hat grabbed here, a kick there), which corrupts loop lengths —
    measured 97 ms of drift over a 16-bar intro, worse than the 10 ms model
    error it was meant to fix. Modern productions are grid-quantized, so one
    global phase correction aligns every bar; downbeats with no clear onset
    (breakdowns, silence) simply don't vote. Fewer than ``min_votes`` clear
    onsets → grid returned unchanged.
    """
    if not len(stem) or not grid.downbeats_samples:
        return grid
    sr = grid.sample_rate
    mono = np.abs(stem).mean(axis=1) if stem.ndim == 2 else np.abs(stem)
    w = max(1, int(sr * 0.003))
    env = np.convolve(mono.astype(np.float64) ** 2, np.ones(w) / w, mode="same")
    rise = np.maximum(np.diff(env, prepend=env[:1]), 0.0)
    W = max(1, int(sr * window_ms / 1000.0))

    deltas = []
    for d in grid.downbeats_samples:
        a, b = max(d - W, 0), min(d + W, len(rise))
        if b - a < 2:
            continue
        seg = rise[a:b]
        peak = int(np.argmax(seg))
        floor = float(np.median(seg)) + 1e-12
        if seg[peak] >= min_rise_ratio * floor:
            deltas.append((a + peak) - d)
    if len(deltas) < min_votes:
        return grid
    shift = int(round(float(np.median(deltas))))
    if shift == 0:
        return grid
    return Beatgrid(
        bpm=grid.bpm,
        sample_rate=sr,
        downbeats_samples=[max(0, d + shift) for d in grid.downbeats_samples],
        beats_samples=[max(0, b + shift) for b in grid.beats_samples],
        source=grid.source,
    )


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
    # EVERY bar of the window must clear the threshold (a mean can hide a weak
    # bar mid-window — e.g. a half-bar build — which would make an ugly loop).
    for i in range(len(bar_rms) - loop_bars + 1):
        if float(np.min(bar_rms[i:i + loop_bars])) >= threshold:
            return i
    return 0


def pick_outro_point(original: np.ndarray, grid: Beatgrid, min_ratio: float = 0.35) -> int:
    """Pick the downbeat where the body should END and the beat outro take over:
    right after the last 'strong' bar of the ORIGINAL audio.

    The naive default (last downbeat minus outro length) lands mid-fade on most
    commercial tracks — a full-volume beat loop slamming in after the song has
    already gone quiet (measured: body RMS 0.067 vs 0.44 mid-song). Riding out
    of the last full-energy bar is what a DJ outro actually wants.
    """
    db = grid.downbeats_samples
    if len(db) < 2:
        return max(len(db) - 1, 0)
    bar_rms = _bar_rms(original, db)
    nonzero = bar_rms[bar_rms > 0]
    if not len(nonzero):
        return len(db) - 1
    threshold = min_ratio * float(np.quantile(nonzero, 0.8))
    strong = np.nonzero(bar_rms >= threshold)[0]
    if not len(strong):
        return len(db) - 1
    # body ends on the downbeat AFTER the last strong bar
    return min(int(strong[-1]) + 1, len(db) - 1)


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


def _crossfade_join(a: np.ndarray, b: np.ndarray, c: int) -> np.ndarray:
    """Concatenate a + b with a short equal-power crossfade over c samples.

    Used for the hard-drop seams (intro->body, body->outro). The crossfade exists
    ONLY to kill the click at the join — it is a few ms, not a musical fade. The
    join is otherwise a hard cut on the "1".
    """
    if c <= 0 or len(a) < c or len(b) < c:
        return np.concatenate([a, b])
    fade_in, fade_out = _equal_power_ramps(c)
    blended = a[-c:] * fade_out[:, None] + b[:c] * fade_in[:, None]
    return np.concatenate([a[:-c], blended, b[c:]])


def _lowpass_sweep(
    audio: np.ndarray, sr: int, start_hz: float = 450.0, open_hz: float = 20000.0,
    order: int = 2, curve: float = 2.0,
) -> np.ndarray:
    """Open a low-pass filter across ``audio``: cutoff starts muffled at ``start_hz``
    (dark — hats/brightness removed, just the low thump) and sweeps UP to ``open_hz``
    (≈ fully open) by the end, so the loop goes from muffled to bright as it
    approaches the drop. The classic "filter build into the drop."

    Low-pass (not high-pass) because on drum loops the hats carry most of the energy
    and live up high — removing/restoring them is what the ear actually hears, so the
    sweep is clearly audible (a high-pass only swaps the inaudible low end). ``curve``
    > 1 back-loads it: stays muffled for most of the intro and brightens mainly in the
    final bars, so it reads as a build rather than opening by the halfway point.

    Implemented as a **tap-crossfade morph** rather than a time-varying filter: a small
    set of CLEAN, statically-filtered copies of the whole buffer at log-spaced cutoffs are
    crossfaded per sample according to the sweep curve. This is artifact-free — unlike
    swapping filter coefficients block-to-block while carrying state, which spikes at every
    block boundary (large internal state at low cutoffs) and distorts. Same-length output.
    """
    n = len(audio)
    if n == 0 or open_hz <= start_hz:
        return audio
    x = audio if audio.ndim == 2 else audio[:, None]
    ch = x.shape[1]
    nyq = sr / 2.0

    # Tap cutoffs: K-1 static low-passes log-spaced start_hz..open_hz, plus an unfiltered
    # top tap (full fidelity at the drop). Index K-1 == "open" (no filtering).
    K = 12
    cuts = np.logspace(np.log10(start_hz), np.log10(min(open_hz, nyq * 0.99)), K - 1)

    # Per-sample target cutoff from the back-loaded curve, mapped to a fractional tap index.
    p = np.arange(n, dtype=np.float64) / max(n - 1, 1)
    fc = start_hz * (open_hz / start_hz) ** (p ** curve)
    tap_axis = np.concatenate([np.log10(cuts), [np.log10(nyq)]])  # last tap = open
    t = np.interp(np.log10(fc), tap_axis, np.arange(K))           # fractional tap in [0, K-1]

    # Accumulate one tap at a time (triangular crossfade weights sum to 1 between neighbours).
    out = np.zeros_like(x)
    for k in range(K):
        w = np.clip(1.0 - np.abs(t - k), 0.0, 1.0)
        if not w.any():
            continue
        if k == K - 1:                                # open tap = unfiltered
            tap = x
        else:
            sos = butter(order, cuts[k] / nyq, btype="lowpass", output="sos")
            # seed state to the first sample (no startup thump); zi shape (sections, ch, 2)
            zi0 = sosfilt_zi(sos)[:, None, :] * x[0][None, :, None]
            tap, _ = sosfilt(sos, x, axis=0, zi=zi0)
        out += tap * w[:, None]
    return out if audio.ndim == 2 else out[:, 0]


def _snare_build(
    intro: np.ndarray,
    build_stem: np.ndarray,
    grid: Beatgrid,
    loop_source_idx: int,
    sr: int,
    build_bars: int = 1,
    gain: float = 0.6,
) -> np.ndarray:
    """Overlay an accelerating backbeat-snare roll on the LAST ``build_bars`` of the
    intro, in place (same length). The roll releases into the drop, turning a flat
    loop into a buildup. Subtle: 1 bar, 1/8 -> 1/16 with a gentle crescendo.

    The snare one-shot is sliced from beat 2 of the loop's source bar (snare-dominant
    in 4/4; kick sits on 1 & 3), taken from ``build_stem`` (drums-only) so bass doesn't
    muddy it.
    """
    n = len(intro)
    db = grid.downbeats_samples
    if build_bars <= 0 or n == 0 or loop_source_idx >= len(db):
        return intro
    beat_len = (
        int(round(float(np.median(np.diff(grid.beats_samples)))))
        if len(grid.beats_samples) >= 3
        else int(round(sr * 60.0 / grid.bpm))
    )
    bar_len = beat_len * 4
    out = intro if intro.ndim == 2 else intro[:, None]
    ch = out.shape[1]

    # Snare one-shot: beat 2 of the source bar -> +1/2 beat, windowed to avoid clicks.
    bs = build_stem if build_stem.ndim == 2 else build_stem[:, None]
    if bs.shape[1] != ch:                            # mono stem vs stereo intro
        bs = np.repeat(bs[:, :1], ch, axis=1) if bs.shape[1] == 1 else bs[:, :ch]
    snare_at = db[loop_source_idx] + beat_len
    slice_len = max(1, beat_len // 2)
    if snare_at + slice_len > len(bs):
        return intro
    shot = bs[snare_at:snare_at + slice_len].astype(np.float32).copy()
    fade = max(1, int(0.010 * sr))                   # 10 ms fade-out tail
    if fade < len(shot):
        shot[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)[:, None]

    # Hit grid over the build region: 1/8 notes for the first half, 1/16 for the second.
    build_start = n - build_bars * bar_len
    if build_start < 0:
        return intro
    eighth, sixteenth = beat_len // 2, beat_len // 4
    offsets: list[int] = []
    for b in range(build_bars):
        base = b * bar_len
        for k in range(4):                           # beats 1-2: 1/8 notes
            offsets.append(base + k * eighth)
        for k in range(8):                           # beats 3-4: 1/16 notes
            offsets.append(base + 2 * beat_len + k * sixteenth)

    total = build_bars * bar_len
    for off in offsets:
        cres = 0.35 + 0.55 * (off / max(total, 1))   # crescendo 0.35 -> 0.9
        amp = gain * cres
        start = build_start + off
        end = min(start + len(shot), n)
        if start >= n:
            break
        out[start:end] += shot[: end - start] * amp   # clip-safety applied by caller
    return out if intro.ndim == 2 else out[:, 0]


def _limit_peak(audio: np.ndarray, ceil: float = 0.99) -> np.ndarray:
    """Scalar gain-trim so the peak never exceeds ``ceil`` — avoids hard-clip distortion
    from lowpass overshoot / the snare overlay without altering the waveform shape."""
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    return audio * (ceil / peak) if peak > ceil else audio


@dataclass
class EditResult:
    audio: np.ndarray                 # [samples, channels] float32
    sample_rate: int
    drop_sample: int | None           # where the body (original) enters, post-join
    outro_sample: int | None          # where the outro beat begins, post-join


def assemble_edit(
    original: np.ndarray,
    loop_stem: np.ndarray,
    grid: Beatgrid,
    *,
    loop_source_idx: int,
    loop_bars: int = 2,
    intro_bars: int = 16,
    drop_idx: int | None = None,
    outro_bars: int = 0,
    outro_idx: int | None = None,
    crossfade_ms: float = 6.0,
    build_stem: np.ndarray | None = None,
    intro_build_bars: int = 1,
    intro_sweep: bool = True,
    sweep_start_hz: float = 450.0,
) -> EditResult:
    """Assemble a full intro/outro edit: beat intro -> ORIGINAL body -> beat outro.

    The body is the UNTOUCHED original audio (not the stem recombination), entered
    on a downbeat with a hard drop. Only the intro/outro loops are stem-derived.

    Args:
        original: full-fidelity original audio [samples, channels].
        loop_stem: the loop source stem (drums or drums+bass) [samples, channels].
        grid: beatgrid (detected or Serato).
        loop_source_idx: downbeat index the loop phrase is taken from.
        intro_bars / outro_bars: beat-loop lengths (0 disables that side).
        drop_idx: downbeat index where the original body enters. Defaults to
            loop_source_idx so the looped groove flows straight into the real
            track on the same phase.
        outro_idx: downbeat index where the body ends and the outro beat starts.
            Required if outro_bars > 0.
    """
    db = grid.downbeats_samples
    sr = grid.sample_rate
    c = max(1, int(round(crossfade_ms / 1000.0 * sr)))
    if drop_idx is None:
        drop_idx = loop_source_idx
    if outro_bars > 0 and outro_idx is None:
        raise ValueError("outro_idx is required when outro_bars > 0")

    body_start = db[drop_idx]
    body_end = db[outro_idx] if outro_bars > 0 else len(original)
    if body_end <= body_start:
        raise ValueError("body end must come after body start (check drop_idx/outro_idx)")
    body = original[body_start:body_end]

    audio = None
    drop_sample = None
    outro_sample = None

    if intro_bars > 0:
        intro = build_beat_loop(loop_stem, grid, loop_source_idx, loop_bars, intro_bars, crossfade_ms)
        # Subtle "DJ intro" treatment (length-preserving, so the drop stays on the "1"):
        # open a high-pass across the intro, then lift a snare roll into the drop.
        if intro_sweep:
            intro = _lowpass_sweep(intro, sr, start_hz=sweep_start_hz)
        if intro_build_bars > 0:
            intro = _snare_build(
                intro, build_stem if build_stem is not None else loop_stem,
                grid, loop_source_idx, sr, build_bars=intro_build_bars,
            )
        intro = _limit_peak(intro)               # safety: no hard-clip distortion
        audio = intro
        # post-join, the body starts one crossfade earlier than the raw intro length
        drop_sample = max(len(intro) - c, 0)
        audio = _crossfade_join(audio, body, c)
    else:
        audio = body

    if outro_bars > 0:
        outro = build_beat_loop(loop_stem, grid, loop_source_idx, loop_bars, outro_bars, crossfade_ms)
        outro = _limit_peak(outro)               # drums+bass sum can exceed 1.0
        outro_sample = max(len(audio) - c, 0)
        audio = _crossfade_join(audio, outro, c)

    # Final safety: MP3/AAC decodes routinely overshoot 1.0 (intersample peaks —
    # measured 1.077 on a real body), and write_wav would hard-clip ~20k samples.
    # A single scalar trim preserves all relative levels and kills the clipping.
    audio = _limit_peak(audio)

    return EditResult(audio=audio.astype(np.float32), sample_rate=sr,
                      drop_sample=drop_sample, outro_sample=outro_sample)


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
