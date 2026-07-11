"""THROWAWAY demo — full intro/outro edit end-to-end, with focused renders of the
drop and outro transition zones for ear-checking.

    backend/venv/bin/python backend/spikes/edit_demo.py TRACK
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from beatgrid_spike import detect_beatgrid  # noqa: E402
import vocal_separator as vs  # noqa: E402
import intro_outro as io  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("track")
    ap.add_argument("--intro", type=int, default=8)
    ap.add_argument("--outro", type=int, default=8)
    ap.add_argument("--loop", type=int, default=2)
    args = ap.parse_args()

    g = detect_beatgrid(args.track)
    grid = io.Beatgrid(bpm=g.bpm, sample_rate=g.sample_rate, downbeats_samples=g.downbeats_samples)
    sr = grid.sample_rate
    print(f"BPM={grid.bpm}  downbeats={len(grid.downbeats_samples)}")

    stems = vs.separate(args.track, "/tmp/editdemo_stems", extra_stems=["drums"])
    drums, _ = io.load_stem(stems["drums_path"])
    original = io.load_audio(args.track, sr, channels=2)

    src = io.pick_loop_source(drums, grid, loop_bars=args.loop)
    outro_idx = len(grid.downbeats_samples) - 1 - args.outro
    res = io.assemble_edit(
        original, drums, grid,
        loop_source_idx=src, loop_bars=args.loop,
        intro_bars=args.intro, drop_idx=src,
        outro_bars=args.outro, outro_idx=outro_idx,
    )

    base = os.path.splitext(args.track)[0]
    full = f"{base}_edit.wav"
    io.write_wav(full, res.audio, sr)

    spb = int(grid.samples_per_bar())
    # 4 bars either side of the drop and the outro seam, for quick ear-check
    def clip(center, name):
        a = max(0, center - 4 * spb)
        b = min(len(res.audio), center + 4 * spb)
        out = f"{base}_{name}.wav"
        io.write_wav(out, res.audio[a:b], sr)
        return out

    drop_clip = clip(res.drop_sample, "DROPZONE")
    outro_clip = clip(res.outro_sample, "OUTROZONE")

    print(f"loop source bar #{src} @ {grid.downbeats_samples[src]/sr:.2f}s")
    print(f"full edit: {res.audio.shape[0]/sr:.1f}s -> {full}")
    print(f"drop @ {res.drop_sample/sr:.2f}s  outro @ {res.outro_sample/sr:.2f}s")
    print(f"drop-zone clip:  {drop_clip}")
    print(f"outro-zone clip: {outro_clip}")


if __name__ == "__main__":
    main()
