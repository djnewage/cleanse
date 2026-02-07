import argparse
import multiprocessing
import os
import sys
import tempfile

# Required for PyInstaller: without this, multiprocessing child processes
# re-execute main.py and crash on argparse (they receive internal args like
# -B -S -I that argparse doesn't recognise). Must be called before anything else.
multiprocessing.freeze_support()

# Fix SSL certificate verification in PyInstaller bundles (macOS can't find
# the system cert store from a frozen app, so point at certifi's CA bundle).
import certifi
os.environ.setdefault('SSL_CERT_FILE', certifi.where())
os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())

import imageio_ffmpeg
from pydub import AudioSegment

# Configure pydub to use the bundled ffmpeg (so end users don't need it installed)
AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()
AudioSegment.ffprobe = imageio_ffmpeg.get_ffmpeg_exe()

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from transcribe import transcribe_audio
from profanity_detector import flag_profanity
from audio_processor import censor_audio, censor_audio_vocals_only
from vocal_separator import separate as separate_vocals
from device_info import detect_device

app = FastAPI(title="Cleanse Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TranscribeRequest(BaseModel):
    path: str
    turbo: bool = False


class CensorWord(BaseModel):
    word: str
    start: float
    end: float
    censor_type: str = "mute"  # "mute", "beep", "reverse", or "tape_stop"


class SeparateRequest(BaseModel):
    path: str
    turbo: bool = False


class CensorRequest(BaseModel):
    path: str
    words: list[CensorWord]
    output_path: str | None = None
    vocals_path: str | None = None
    accompaniment_path: str | None = None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/device-info")
async def device_info():
    return detect_device()


@app.post("/transcribe")
def transcribe(req: TranscribeRequest):
    if not os.path.isfile(req.path):
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")

    try:
        result = transcribe_audio(req.path, turbo=req.turbo)
        words_with_flags = flag_profanity(result["words"])
        return {
            "words": words_with_flags,
            "duration": result["duration"],
            "language": result["language"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/separate")
def separate(req: SeparateRequest):
    if not os.path.isfile(req.path):
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")

    try:
        output_dir = os.path.join(tempfile.gettempdir(), "cleanse-separated")
        result = separate_vocals(req.path, output_dir, turbo=req.turbo)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/censor")
def censor(req: CensorRequest):
    if not os.path.isfile(req.path):
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")

    if not req.words:
        raise HTTPException(status_code=400, detail="No words to censor")

    try:
        output_path = req.output_path
        if not output_path:
            base, ext = os.path.splitext(req.path)
            output_path = f"{base}_clean{ext}"

        words_dicts = [w.model_dump() for w in req.words]

        if req.vocals_path and req.accompaniment_path:
            result_path = censor_audio_vocals_only(
                req.vocals_path, req.accompaniment_path, words_dicts, output_path
            )
        else:
            result_path = censor_audio(req.path, words_dicts, output_path)

        return {"output_path": result_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
