"""Vocal separation using Meta's Demucs (htdemucs model)."""

import json
import os
import sys

# Load model once at module level (cached after first download)
_model = None


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
    import torchaudio
    import tqdm as tqdm_module
    from demucs.apply import apply_model

    model = _get_model()

    _report_progress("loading_audio", 5, "Loading audio file...")
    wav, sr = torchaudio.load(input_path)

    # Resample to model's sample rate if needed
    if sr != model.samplerate:
        _report_progress("resampling", 8, "Resampling audio...")
        wav = torchaudio.transforms.Resample(sr, model.samplerate)(wav)
        sr = model.samplerate

    # Ensure stereo
    if wav.shape[0] == 1:
        wav = wav.repeat(2, 1)

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
            sources = apply_model(model, wav.unsqueeze(0), device=device, progress=True)
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

    torchaudio.save(vocals_path, vocals.cpu(), sr)
    torchaudio.save(accompaniment_path, accompaniment.cpu(), sr)

    _report_progress("complete", 100, "Separation complete!")

    return {"vocals_path": vocals_path, "accompaniment_path": accompaniment_path}
