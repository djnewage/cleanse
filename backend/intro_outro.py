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

    Block-processed with filter state carried across blocks (so there are no
    per-block discontinuities), cutoff interpolated logarithmically per block.
    Same-length output.
    """
    n = len(audio)
    if n == 0 or open_hz <= start_hz:
        return audio
    x = audio if audio.ndim == 2 else audio[:, None]
    ch = x.shape[1]
    nyq = sr / 2.0
    block = 2048
    out = np.empty_like(x)
    # per-channel filter state, lazily initialised to the first block's steady state
    zi = [None] * ch
    pos = 0
    while pos < n:
        end = min(pos + block, n)
        p = (pos + (end - pos) / 2.0) / n            # progress at block centre
        fc = start_hz * (open_hz / start_hz) ** (p ** curve)  # back-loaded log sweep up
        seg = x[pos:end]
        if fc >= nyq * 0.95:                          # effectively open -> pass through clean
            out[pos:end] = seg
            zi = [None] * ch                          # re-seed state on next filtered block
            pos = end
            continue
        sos = butter(order, fc / nyq, btype="lowpass", output="sos")
        for c in range(ch):
            if zi[c] is None:
                zi[c] = sosfilt_zi(sos) * seg[0, c]
            y, zi[c] = sosfilt(sos, seg[:, c], zi=zi[c])
            out[pos:end, c] = y
        pos = end
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
        grid.beats_samples[1] - grid.beats_samples[0]
        if len(grid.beats_samples) >= 2
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
        out[start:end] += shot[: end - start] * amp

    np.clip(out, -1.0, 1.0, out=out)
    return out if intro.ndim == 2 else out[:, 0]


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
        audio = intro
        # post-join, the body starts one crossfade earlier than the raw intro length
        drop_sample = max(len(intro) - c, 0)
        audio = _crossfade_join(audio, body, c)
    else:
        audio = body

    if outro_bars > 0:
        outro = build_beat_loop(loop_stem, grid, loop_source_idx, loop_bars, outro_bars, crossfade_ms)
        outro_sample = max(len(audio) - c, 0)
        audio = _crossfade_join(audio, outro, c)

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
