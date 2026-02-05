"""Vocal separation using Meta's Demucs (htdemucs model)."""

import os
import torch
import torchaudio
from demucs.pretrained import get_model
from demucs.apply import apply_model

# Load model once at module level (cached after first download)
_model = None


def _get_model():
    global _model
    if _model is None:
        _model = get_model("htdemucs")
        _model.eval()
    return _model


def separate(input_path: str, output_dir: str) -> dict:
    """
    Separate an audio file into vocals and accompaniment.

    Args:
        input_path: Path to the input audio file
        output_dir: Directory to save the separated tracks

    Returns:
        {"vocals_path": str, "accompaniment_path": str}
    """
    model = _get_model()

    wav, sr = torchaudio.load(input_path)

    # Resample to model's sample rate if needed
    if sr != model.samplerate:
        wav = torchaudio.transforms.Resample(sr, model.samplerate)(wav)
        sr = model.samplerate

    # Ensure stereo
    if wav.shape[0] == 1:
        wav = wav.repeat(2, 1)

    # Apply model: returns (1, num_sources, channels, samples)
    with torch.no_grad():
        sources = apply_model(model, wav.unsqueeze(0), device="cpu")

    # htdemucs source order: drums=0, bass=1, other=2, vocals=3
    vocals = sources[0, 3]
    accompaniment = sources[0, 0] + sources[0, 1] + sources[0, 2]

    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(input_path))[0]

    vocals_path = os.path.join(output_dir, f"{base}_vocals.wav")
    accompaniment_path = os.path.join(output_dir, f"{base}_accompaniment.wav")

    torchaudio.save(vocals_path, vocals.cpu(), sr)
    torchaudio.save(accompaniment_path, accompaniment.cpu(), sr)

    return {"vocals_path": vocals_path, "accompaniment_path": accompaniment_path}
