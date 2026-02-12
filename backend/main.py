import argparse
import asyncio
import json as json_module
import multiprocessing
import os
import sys
import tempfile
import threading

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
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from transcribe import transcribe_audio
from profanity_detector import flag_profanity
from audio_processor import censor_audio, censor_audio_vocals_only
from vocal_separator import separate as separate_vocals
from device_info import detect_device
from lyrics_fetcher import extract_metadata, fetch_lyrics, find_lyrics_profanity

# Configuration: Dual-pass transcription (transcribe both mix + vocals)
# Set CLEANSE_DUAL_PASS=true to enable for higher accuracy (slower)
# TODO: Add dual-pass toggle in settings UI
ENABLE_DUAL_PASS = os.environ.get("CLEANSE_DUAL_PASS", "false").lower() == "true"

app = FastAPI(title="Cleanse Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _streaming_heartbeat_wrapper(sync_fn, *args, **kwargs):
    """Run sync_fn in a background thread, yielding NDJSON heartbeats until done.

    Yields JSON lines: {"type":"heartbeat"}, {"type":"result","data":...},
    or {"type":"error","detail":...}.

    Uses run_in_executor (default ThreadPoolExecutor) instead of raw
    threading.Thread to preserve macOS/Apple Silicon QoS scheduling —
    raw daemon threads get lower QoS and run on efficiency cores.
    """
    result_holder = {}
    done_event = threading.Event()
    worker_thread = None

    def run():
        nonlocal worker_thread
        worker_thread = threading.current_thread()
        try:
            result_holder["data"] = sync_fn(*args, **kwargs)
        except Exception as e:
            result_holder["error"] = str(e)
        finally:
            done_event.set()

    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, run)

    while not done_event.is_set():
        if worker_thread is not None and not worker_thread.is_alive():
            detail = result_holder.get("error", "Worker thread died unexpectedly")
            yield json_module.dumps({"type": "error", "detail": detail}) + "\n"
            return

        yield json_module.dumps({"type": "heartbeat"}) + "\n"
        for _ in range(4):
            if done_event.is_set():
                break
            await asyncio.sleep(0.5)

    if "error" in result_holder:
        yield json_module.dumps({"type": "error", "detail": result_holder["error"]}) + "\n"
    else:
        yield json_module.dumps({"type": "result", "data": result_holder["data"]}) + "\n"


class MetadataRequest(BaseModel):
    path: str


class TranscribeRequest(BaseModel):
    path: str
    turbo: bool = False
    vocals_path: str | None = None
    lyrics: str | None = None
    synced_lyrics: str | None = None


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
    crossfade_ms: int = 30


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/device-info")
async def device_info():
    return detect_device()


class FetchLyricsRequest(BaseModel):
    artist: str
    title: str
    duration: float | None = None


@app.post("/metadata")
def metadata(req: MetadataRequest):
    if not os.path.isfile(req.path):
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")
    return extract_metadata(req.path)


@app.post("/fetch-lyrics")
def fetch_lyrics_endpoint(req: FetchLyricsRequest):
    result = fetch_lyrics(req.artist, req.title, req.duration)
    if result is None:
        return {"plain_lyrics": None, "synced_lyrics": None}
    return result


def merge_word_lists(
    primary_words: list[dict],
    secondary_words: list[dict],
    overlap_threshold: float = 0.3,
) -> list[dict]:
    """Merge two transcription word lists, importing new profanity detections from secondary."""
    merged = [w.copy() for w in primary_words]

    for sec_word in secondary_words:
        if not sec_word.get("is_profanity"):
            continue  # Only import profanity detections from vocals pass

        is_duplicate = False
        for i, pri_word in enumerate(merged):
            # Check temporal overlap
            overlap = min(sec_word["end"], pri_word["end"]) - max(sec_word["start"], pri_word["start"])
            if overlap > 0:
                merged[i]["is_profanity"] = True
                merged[i]["detection_source"] = "vocals"
                is_duplicate = True
                break
            # Check near-miss with same word text
            gap = min(
                abs(sec_word["start"] - pri_word["end"]),
                abs(pri_word["start"] - sec_word["end"]),
            )
            if gap < overlap_threshold and sec_word["word"].lower() == pri_word["word"].lower():
                merged[i]["is_profanity"] = True
                merged[i]["detection_source"] = "vocals"
                is_duplicate = True
                break

        if not is_duplicate:
            merged.append({**sec_word, "detection_source": "adlib"})

    merged.sort(key=lambda w: w["start"])
    return merged


@app.post("/transcribe")
async def transcribe(req: TranscribeRequest):
    if not os.path.isfile(req.path):
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")

    dual_pass = ENABLE_DUAL_PASS and req.vocals_path and os.path.isfile(req.vocals_path)

    def _do_transcribe():
        # Pass 1: Transcribe the full mix
        if dual_pass:
            result = transcribe_audio(
                req.path, turbo=req.turbo, initial_prompt=req.lyrics,
                progress_offset=0, progress_scale=45,
            )
        else:
            result = transcribe_audio(req.path, turbo=req.turbo, initial_prompt=req.lyrics)

        primary_words = flag_profanity(result["words"])
        detected_language = result["language"]

        # Pass 2: Transcribe isolated vocals (if available)
        if dual_pass:
            vocals_result = transcribe_audio(
                req.vocals_path,
                turbo=req.turbo,
                language=detected_language,
                initial_prompt=req.lyrics,
                progress_offset=50,
                progress_scale=45,
            )
            secondary_words = flag_profanity(vocals_result["words"])
            final_words = merge_word_lists(primary_words, secondary_words)
        else:
            final_words = primary_words

        # Cross-reference with synced lyrics to find missed profanities
        if req.synced_lyrics:
            lyrics_detections = find_lyrics_profanity(req.synced_lyrics, final_words)
            if lyrics_detections:
                final_words = final_words + lyrics_detections
                final_words.sort(key=lambda w: w["start"])

        return {
            "words": final_words,
            "duration": result["duration"],
            "language": detected_language,
        }

    return StreamingResponse(
        _streaming_heartbeat_wrapper(_do_transcribe),
        media_type="application/x-ndjson",
    )


@app.post("/separate")
async def separate(req: SeparateRequest):
    if not os.path.isfile(req.path):
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")

    output_dir = os.path.join(tempfile.gettempdir(), "cleanse-separated")
    return StreamingResponse(
        _streaming_heartbeat_wrapper(separate_vocals, req.path, output_dir, turbo=req.turbo),
        media_type="application/x-ndjson",
    )


@app.post("/preview")
def preview(req: CensorRequest):
    """Generate temporary censored preview for reviewing before export."""
    if not os.path.isfile(req.path):
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")

    if not req.words:
        raise HTTPException(status_code=400, detail="No words to censor")

    try:
        # Generate temp output path
        temp_dir = os.path.join(tempfile.gettempdir(), "cleanse-preview")
        os.makedirs(temp_dir, exist_ok=True)

        # Create preview filename with timestamp to handle edits
        base = os.path.basename(req.path)
        name, ext = os.path.splitext(base)
        import time
        preview_path = os.path.join(temp_dir, f"{name}_preview_{int(time.time())}{ext}")

        words_dicts = [w.model_dump() for w in req.words]

        # Censor audio (same as export)
        if req.vocals_path and req.accompaniment_path:
            result_path = censor_audio_vocals_only(
                req.vocals_path, req.accompaniment_path, words_dicts, preview_path,
                crossfade_ms=req.crossfade_ms,
            )
        else:
            result_path = censor_audio(req.path, words_dicts, preview_path, crossfade_ms=req.crossfade_ms)

        return {"output_path": result_path}
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
                req.vocals_path, req.accompaniment_path, words_dicts, output_path,
                crossfade_ms=req.crossfade_ms,
            )
        else:
            result_path = censor_audio(req.path, words_dicts, output_path, crossfade_ms=req.crossfade_ms)

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
