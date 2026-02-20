"""Benchmark script to measure turbo mode speedup for transcription and separation.

Usage:
    cd backend
    python benchmark_turbo.py
"""

import os
import shutil
import statistics
import sys
import tempfile
import time

from pydub import AudioSegment
from pydub.generators import Sine


def generate_test_audio(output_path: str, duration_ms: int = 10000):
    """Generate a 10-second 440Hz sine wave WAV file."""
    tone = Sine(440).to_audio_segment(duration=duration_ms)
    tone.export(output_path, format="wav")
    print(f"Generated {duration_ms / 1000:.0f}s test audio: {output_path}", file=sys.stderr)


def benchmark_transcription(file_path: str, turbo: bool, warmup: int = 1, runs: int = 3) -> float:
    """Run transcription benchmark. Returns median time in seconds."""
    from transcribe import transcribe_audio

    label = "turbo" if turbo else "normal"

    # Warm-up runs (loads/caches model)
    for i in range(warmup):
        print(f"  [{label}] warm-up {i + 1}/{warmup}...", file=sys.stderr)
        transcribe_audio(file_path, turbo=turbo)

    # Timed runs
    times = []
    for i in range(runs):
        print(f"  [{label}] run {i + 1}/{runs}...", file=sys.stderr)
        start = time.perf_counter()
        transcribe_audio(file_path, turbo=turbo)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    median = statistics.median(times)
    return median


def benchmark_separation(file_path: str, output_dir: str, turbo: bool, warmup: int = 1, runs: int = 2) -> float:
    """Run separation benchmark. Returns median time in seconds."""
    from vocal_separator import separate

    label = "turbo" if turbo else "normal"

    # Warm-up runs
    for i in range(warmup):
        print(f"  [{label}] warm-up {i + 1}/{warmup}...", file=sys.stderr)
        separate(file_path, output_dir, turbo=turbo)

    # Timed runs
    times = []
    for i in range(runs):
        print(f"  [{label}] run {i + 1}/{runs}...", file=sys.stderr)
        start = time.perf_counter()
        separate(file_path, output_dir, turbo=turbo)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    median = statistics.median(times)
    return median


def main():
    from device_info import detect_device

    device = detect_device()
    print(f"Device: {device['device_type']} | GPU: {device['gpu_available']}")
    print("=" * 50)

    tmp_dir = tempfile.mkdtemp(prefix="cleanse_bench_")
    audio_path = os.path.join(tmp_dir, "test_tone.wav")
    sep_out_dir = os.path.join(tmp_dir, "separated")

    try:
        generate_test_audio(audio_path)

        # --- Transcription benchmark ---
        print("\n--- Transcription ---")
        normal_t = benchmark_transcription(audio_path, turbo=False)
        turbo_t = benchmark_transcription(audio_path, turbo=True)
        speedup_t = normal_t / turbo_t if turbo_t > 0 else float("inf")
        print(
            f"Normal (beam=3, small model): {normal_t:.2f}s  |  "
            f"Turbo (beam=1, small model): {turbo_t:.2f}s  |  "
            f"Speedup: {speedup_t:.2f}x"
        )

        # --- Separation benchmark ---
        print("\n--- Separation ---")
        normal_s = benchmark_separation(audio_path, sep_out_dir, turbo=False)
        turbo_s = benchmark_separation(audio_path, sep_out_dir, turbo=True)
        speedup_s = normal_s / turbo_s if turbo_s > 0 else float("inf")

        sep_device_normal = "cpu"
        sep_device_turbo = device["device_type"]
        print(
            f"Normal ({sep_device_normal}): {normal_s:.2f}s  |  "
            f"Turbo ({sep_device_turbo}): {turbo_s:.2f}s  |  "
            f"Speedup: {speedup_s:.2f}x"
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print(f"\nCleaned up temp dir: {tmp_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
