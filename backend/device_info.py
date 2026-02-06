"""GPU detection module for turbo processing."""

import sys

_cached_info: dict | None = None


def detect_device() -> dict:
    """Detect available GPU and return device info. Caches after first call."""
    global _cached_info
    if _cached_info is not None:
        return _cached_info

    import torch

    gpu_available = False
    device_type = "cpu"
    device_name = "CPU"

    if torch.cuda.is_available():
        gpu_available = True
        device_type = "cuda"
        device_name = torch.cuda.get_device_name(0)
    elif torch.backends.mps.is_available():
        gpu_available = True
        device_type = "mps"
        device_name = "Apple Silicon GPU"

    _cached_info = {
        "gpu_available": gpu_available,
        "device_type": device_type,
        "device_name": device_name,
        "turbo_supported": gpu_available,
    }

    print(f"[DeviceInfo] Detected: {_cached_info}", file=sys.stderr)
    return _cached_info


def get_device_string() -> str:
    """Return the best available device string: 'cuda', 'mps', or 'cpu'."""
    info = detect_device()
    return info["device_type"]
