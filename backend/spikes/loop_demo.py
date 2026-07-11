"""THROWAWAY demo — build a real beat loop end-to-end (detect grid -> separate
drums -> tile a click-free loop) so a human can hear the seam quality.

    backend/venv/bin/python backend/spikes/loop_demo.py TRACK [--bars 16] [--loop 2]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402

from beatgrid_spike import detect_beatgrid  # applies madmom shims  # noqa: E402
import vocal_separator as vs  # noqa: E402
import intro_outro as io  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("track")
    ap.add_argument("--bars", type=int, default=16, help="total intro bars")
    ap.add_argument("--loop", type=int, default=2, help="source loop length in bars")
    args = ap.parse_args()

    print(f"[1/3] detecting grid: {os.path.basename(args.track)}")
    g = detect_beatgrid(args.track)
    grid = io.Beatgrid(bpm=g.bpm, sample_rate=g.sample_rate, downbeats_samples=g.downbeats_samples)
    print(f"      BPM={grid.bpm}  downbeats={len(grid.downbeats_samples)}")

    print("[2/3] separating drums stem...")
    stems = vs.separate(args.track, "/tmp/loopdemo_stems", extra_stems=["drums"])
    drums, sr = io.load_stem(stems["drums_path"])
    print(f"      drums stem: {drums.shape[0]/sr:.1f}s @ {sr}Hz")

    print("[3/3] building loop...")
    src = io.pick_loop_source(drums, grid, loop_bars=args.loop)
    src_t = grid.downbeats_samples[src] / sr
    loop = io.build_beat_loop(drums, grid, src, loop_bars=args.loop, total_bars=args.bars)

    loop_len = grid.downbeats_samples[src + args.loop] - grid.downbeats_samples[src]
    n_tiles = args.bars // args.loop
    seam = io.seam_discontinuity(loop, loop_len, n_tiles)
    normal = np.abs(np.diff(loop.mean(axis=1)))
    p999 = float(np.percentile(normal, 99.9))

    out = os.path.splitext(args.track)[0] + f"_introloop_{args.bars}bar.wav"
    io.write_wav(out, loop, sr)

    print(f"\n  source loop start: bar #{src} @ {src_t:.2f}s")
    print(f"  loop length: {loop_len} samples ({loop_len/sr:.3f}s = {args.loop} bars)")
    print(f"  tiled to {args.bars} bars -> {loop.shape[0]/sr:.2f}s")
    print(f"  SEAM discontinuity: {seam:.5f}  vs normal 99.9pct step {p999:.5f}  "
          f"(ratio {seam/p999 if p999 else float('nan'):.2f}x -> ~1x = click-free)")
    print(f"  wrote: {out}")


if __name__ == "__main__":
    main()
