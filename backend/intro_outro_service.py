"""Orchestration for the auto intro/outro edit: detect grid -> separate stems ->
assemble -> render. Ties the pure-DSP intro_outro module to detection (madmom)
and separation (demucs).

Heavy deps (madmom via beatgrid, demucs via vocal_separator) are imported lazily
inside the function so the rest of the backend still starts if they are absent —
only this endpoint fails, not the whole app.
"""

import json
import os
import sys
import tempfile


def _progress(step: str, pct: float, message: str) -> None:
    """Emit a JSON progress line on stdout (same channel the separator uses)."""
    print(json.dumps({"type": "intro-outro-progress", "step": step,
                       "progress": pct, "message": message}))
    sys.stdout.flush()


def build_intro_outro_edit(
    path: str,
    output_path: str,
    *,
    intro_bars: int = 16,
    outro_bars: int = 16,
    loop_bars: int = 2,
    stems: tuple[str, ...] = ("drums",),
    grid=None,
) -> dict:
    """Build a tagged, lossless intro/outro edit for ``path``.

    Args:
        stems: loop source — ("drums",) or ("drums", "bass"). When more than one,
            they are summed into the loop bed.
        grid: optional pre-supplied Beatgrid (e.g. a manual/Serato override from
            the UI). When None, the grid is detected.
    """
    import intro_outro as io
    from vocal_separator import separate

    _progress("detecting", 5, "Detecting beat grid...")
    if grid is None:
        from beatgrid import detect_beatgrid
        grid = detect_beatgrid(path)
    if len(grid.downbeats_samples) < loop_bars + 1:
        raise ValueError("Not enough downbeats detected to build a loop")

    _progress("separating", 20, "Separating stems...")
    out_dir = os.path.join(tempfile.gettempdir(), "cleanse-introoutro")
    stem_res = separate(path, out_dir, extra_stems=list(stems))

    _progress("assembling", 85, "Building edit...")
    loop_stem, _ = io.load_stem(stem_res[f"{stems[0]}_path"])
    for extra in stems[1:]:
        more, _ = io.load_stem(stem_res[f"{extra}_path"])
        n = min(len(loop_stem), len(more))
        loop_stem = loop_stem[:n] + more[:n]
    original = io.load_audio(path, grid.sample_rate, channels=2)

    src = io.pick_loop_source(loop_stem, grid, loop_bars=loop_bars)

    outro_idx = None
    if outro_bars > 0:
        outro_idx = len(grid.downbeats_samples) - 1 - outro_bars
        if outro_idx <= src:
            outro_bars, outro_idx = 0, None  # track too short for an outro after the drop

    res = io.assemble_edit(
        original, loop_stem, grid,
        loop_source_idx=src, loop_bars=loop_bars,
        intro_bars=intro_bars, drop_idx=src,
        outro_bars=outro_bars, outro_idx=outro_idx,
    )

    _progress("rendering", 95, "Rendering output...")
    io.render_edit(res.audio, grid.sample_rate, output_path, path)
    _progress("complete", 100, "Intro edit complete!")
    return {"output_path": output_path}
