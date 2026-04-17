"""Vocal separation using Meta's Demucs (htdemucs model)."""

import json
import os
import subprocess
import sys

import numpy as np

# Load model once at module level (cached after first download)
_model = None


def _decode_audio_ffmpeg(file_path: str, sampling_rate: int, channels: int = 2) -> np.ndarray:
    """Decode any audio file to float32 PCM [channels, samples] via ffmpeg.

    torchaudio 2.7's soundfile backend cannot read MP3/M4A/AAC, and we do not
    bundle the sox or ffmpeg shared libraries (they trigger macOS-14-only
    AVFoundation symbols on macOS 13). Using the ffmpeg executable shipped by
    imageio-ffmpeg sidesteps both problems.
    """
    import imageio_ffmpeg

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ffmpeg_exe,
        "-nostdin",
        "-threads", "0",
        "-i", file_path,
        "-f", "f32le",
        "-ac", str(channels),
        "-acodec", "pcm_f32le",
        "-ar", str(sampling_rate),
        "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"ffmpeg failed to decode audio: {e.stderr.decode(errors='replace')}"
        ) from e

    return np.frombuffer(result.stdout, dtype=np.float32).reshape(-1, channels).T.copy()


def _write_wav(path: str, tensor, sample_rate: int) -> None:
    """Write a [channels, samples] float tensor to a 16-bit PCM WAV file."""
    from scipy.io import wavfile

    data = tensor.detach().cpu().numpy().T  # -> [samples, channels]
    clipped = np.clip(data, -1.0, 1.0)
    wavfile.write(path, sample_rate, (clipped * 32767.0).astype(np.int16))


def _report_progress(step: str, progress: float, message: str):
    """Print a JSON progress line to stdout for the Electron main process to parse."""
    print(json.dumps({
        "type": "separation-progress",
        "step": step,
        "progress": progress,
        "message": message,
    }))
    sys.stdout.flush()


class ProgressReporter:
    """Drop-in replacement for tqdm.tqdm that reports progress via JSON stdout.

    Maps iteration progress to the 10%-90% range of overall separation.
    """

    def __init__(self, iterable, **kwargs):
        self._iterable = list(iterable)
        self._total = len(self._iterable)
        self._current = 0

    def __iter__(self):
        for item in self._iterable:
            self._current += 1
            mapped = 10 + (self._current / self._total) * 80
            _report_progress(
                "applying_model",
                round(mapped, 1),
                f"Processing segment {self._current}/{self._total}..."
            )
            yield item

    def __len__(self):
        return self._total


def _get_model():
    global _model
    if _model is None:
        from demucs.pretrained import get_model
        _report_progress("loading_model", 0, "Loading separation model...")
        _model = get_model("htdemucs")
        _model.eval()
    return _model


def separate(input_path: str, output_dir: str, turbo: bool = False) -> dict:
    """
    Separate an audio file into vocals and accompaniment.

    Args:
        input_path: Path to the input audio file
        output_dir: Directory to save the separated tracks
        turbo: If True, use GPU acceleration when available

    Returns:
        {"vocals_path": str, "accompaniment_path": str}
    """
    import torch
    import tqdm as tqdm_module
    from demucs.apply import apply_model

    model = _get_model()
    sr = model.samplerate

    _report_progress("loading_audio", 5, "Loading audio file...")
    audio = _decode_audio_ffmpeg(input_path, sampling_rate=sr, channels=2)
    wav = torch.from_numpy(audio)

    # Always use the best available device for separation (demucs supports MPS)
    from device_info import get_device_string
    device = get_device_string()

    print(f"[Separator] Using device={device}, turbo={turbo}", file=sys.stderr)

    # Monkey-patch tqdm to report progress, then apply model
    _report_progress("applying_model", 10, "Applying separation model...")
    original_tqdm = tqdm_module.tqdm
    try:
        tqdm_module.tqdm = ProgressReporter
        with torch.no_grad():
            try:
                sources = apply_model(model, wav.unsqueeze(0), device=device, progress=True)
            except (NotImplementedError, RuntimeError) as e:
                if device != "cpu" and ("65536" in str(e) or "MPS" in str(e)):
                    print(f"[Separator] {device} failed ({e}), falling back to CPU", file=sys.stderr)
                    model.to("cpu")
                    _report_progress("applying_model", 10, "GPU unavailable for this file, using CPU...")
                    sources = apply_model(model, wav.unsqueeze(0), device="cpu", progress=True)
                else:
                    raise
    finally:
        tqdm_module.tqdm = original_tqdm

    _report_progress("saving", 92, "Saving separated tracks...")

    # htdemucs source order: drums=0, bass=1, other=2, vocals=3
    vocals = sources[0, 3]
    accompaniment = sources[0, 0] + sources[0, 1] + sources[0, 2]

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(input_path))[0]

    vocals_path = os.path.join(output_dir, f"{base}_vocals.wav")
    accompaniment_path = os.path.join(output_dir, f"{base}_accompaniment.wav")

    _write_wav(vocals_path, vocals, sr)
    _write_wav(accompaniment_path, accompaniment, sr)

    _report_progress("complete", 100, "Separation complete!")

    return {"vocals_path": vocals_path, "accompaniment_path": accompaniment_path}
