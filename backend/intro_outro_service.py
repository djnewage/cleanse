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
    stem_paths: dict | None = None,
    intro_build: bool = True,
    loop_source_idx: int | None = None,
    drop_idx: int | None = None,
) -> dict:
    """Build a tagged, lossless intro/outro edit for ``path``.

    Args:
        stems: loop source — ("drums",) or ("drums", "bass"). When more than one,
            they are summed into the loop bed.
        grid: optional grid override (a dict with bpm/sample_rate/downbeats_samples,
            e.g. a nudged grid from the UI). When None, the grid is detected.
        stem_paths: optional dict of already-separated stem files (keys like
            "drums_path"). When provided, separation is SKIPPED — this is what makes
            a UI "nudge + regenerate" fast (no re-detect, no re-separate).
        intro_build: apply the buildup treatment (filter sweep + snare roll) to the
            intro. Off = a clean dry loop, what you beatmatch over.
        loop_source_idx / drop_idx: manual bar overrides from the UI nudge buttons.
            None = auto (first sustained-strong bar; drop follows the loop bar).

    Returns dict with output_path plus the grid, stem paths, and chosen bars, so
    the caller can nudge any of them and regenerate cheaply.
    """
    import intro_outro as io
    from vocal_separator import separate

    _progress("detecting", 5, "Detecting beat grid...")
    if grid is None:
        try:
            from beatgrid import detect_beatgrid
        except ImportError as e:
            raise RuntimeError(
                "Beat detection unavailable: madmom is not installed in this build"
            ) from e
        grid = detect_beatgrid(path)
    elif not isinstance(grid, io.Beatgrid):
        grid = io.Beatgrid(
            bpm=grid["bpm"],
            sample_rate=grid["sample_rate"],
            downbeats_samples=list(grid["downbeats_samples"]),
            beats_samples=list(grid.get("beats_samples", [])),
            source=grid.get("source", "detected"),
        )
    if grid.source == "detected":
        # madmom's 100 fps lattice gives ±10 ms bar jitter — enough to make a
        # 16-bar loop audibly drift. Refit to constant tempo (v1 = steady 4/4).
        grid = io.regularize_grid(grid)
    if len(grid.downbeats_samples) < loop_bars + 1:
        raise ValueError("Not enough downbeats detected to build a loop")

    if stem_paths and all(f"{s}_path" in stem_paths for s in stems):
        _progress("separating", 20, "Reusing separated stems...")
        stem_res = dict(stem_paths)
    else:
        _progress("separating", 20, "Separating stems...")
        out_dir = os.path.join(tempfile.gettempdir(), "cleanse-introoutro")
        stem_res = separate(path, out_dir, extra_stems=list(stems))

    _progress("assembling", 85, "Building edit...")
    loop_stem, _ = io.load_stem(stem_res[f"{stems[0]}_path"])
    # Drums-only stem drives the snare-roll build, so bass never muddies the roll.
    build_stem = loop_stem if stems[0] == "drums" else None
    for extra in stems[1:]:
        more, _ = io.load_stem(stem_res[f"{extra}_path"])
        n = min(len(loop_stem), len(more))
        loop_stem = loop_stem[:n] + more[:n]
    original = io.load_audio(path, grid.sample_rate, channels=2)

    if grid.source == "detected":
        # The grid is a model; the drum stem is ground truth. Snap each downbeat
        # to the nearest actual transient so loop cuts / the drop are sample-true.
        grid = io.snap_downbeats_to_transients(grid, loop_stem)

    # Pick the loop bar by DRUM steadiness only: bass patterns often hit just one
    # bar of a phrase, which reads as "weak bars" and pushes the pick deep into
    # the song (measured: bar 0 on drums vs bar 19 on drums+bass, same track).
    pick_stem = build_stem if build_stem is not None else loop_stem
    src = loop_source_idx if loop_source_idx is not None else io.pick_loop_source(
        pick_stem, grid, loop_bars=loop_bars
    )
    src = max(0, min(src, len(grid.downbeats_samples) - loop_bars - 1))
    drop = drop_idx if drop_idx is not None else src
    drop = max(0, min(drop, len(grid.downbeats_samples) - 1))

    outro_idx = None
    if outro_bars > 0:
        # End the body right after its last strong bar — the naive "last downbeat
        # minus outro length" lands mid-fade and the loop slams in after silence.
        outro_idx = io.pick_outro_point(original, grid)
        if outro_idx <= drop:
            outro_bars, outro_idx = 0, None  # track too short for an outro after the drop

    res = io.assemble_edit(
        original, loop_stem, grid,
        loop_source_idx=src, loop_bars=loop_bars,
        intro_bars=intro_bars, drop_idx=drop,
        outro_bars=outro_bars, outro_idx=outro_idx,
        build_stem=build_stem,
        intro_sweep=intro_build,
        intro_build_bars=1 if intro_build else 0,
    )

    _progress("rendering", 95, "Rendering output...")
    io.render_edit(res.audio, grid.sample_rate, output_path, path)
    _progress("complete", 100, "Intro edit complete!")
    return {
        "output_path": output_path,
        "grid": {
            "bpm": grid.bpm,
            "sample_rate": grid.sample_rate,
            "downbeats_samples": grid.downbeats_samples,
            "beats_samples": grid.beats_samples,
            "source": grid.source,
        },
        "stem_paths": {k: v for k, v in stem_res.items()},
        "loop_source_idx": src,
        "drop_idx": drop,
    }
