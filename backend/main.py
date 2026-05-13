import argparse
import asyncio
import json as json_module
import multiprocessing
import os
import sys
import tempfile
import threading
from urllib.parse import unquote

# Force UTF-8 on Windows so Unicode in log messages doesn't crash with 'charmap'
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Required for PyInstaller: without this, multiprocessing child processes
# re-execute main.py and crash on argparse (they receive internal args like
# -B -S -I that argparse doesn't recognise). Must be called before anything else.
multiprocessing.freeze_support()

# Fix SSL certificate verification in PyInstaller bundles (macOS can't find
# the system cert store from a frozen app, so point at certifi's CA bundle).
import certifi
os.environ.setdefault('SSL_CERT_FILE', certifi.where())
os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())

import shutil
import imageio_ffmpeg
from pydub import AudioSegment

# Configure pydub to use the bundled ffmpeg (so end users don't need it installed)
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
AudioSegment.converter = ffmpeg_exe

# Ensure common binary locations are on PATH so pydub can find ffprobe
_extra_paths = ['/opt/homebrew/bin', '/usr/local/bin', os.path.dirname(ffmpeg_exe)]
_current_path = os.environ.get('PATH', '')
for _p in _extra_paths:
    if _p not in _current_path:
        _current_path = _p + os.pathsep + _current_path
os.environ['PATH'] = _current_path

# Pydub requires ffprobe for audio metadata, but it may not be installed.
# If ffprobe is missing, monkey-patch pydub to probe via `ffmpeg -i` instead.
if not shutil.which('ffprobe'):
    import re as _re
    from subprocess import Popen as _Popen, PIPE as _PIPE

    _CHANNEL_MAP = {
        "mono": 1, "stereo": 2, "2.1": 3,
        "3.0": 3, "4.0": 4, "quad": 4, "5.0": 5,
        "5.1": 6, "5.1(side)": 6, "5.1(back)": 6,
        "6.1": 7, "7.1": 8, "7.1(wide)": 8,
    }

    def _ffmpeg_mediainfo_json(filepath, read_ahead_limit=-1):
        """Probe audio metadata using ffmpeg -i (fallback when ffprobe is absent)."""
        from pydub.utils import fsdecode
        try:
            path = fsdecode(filepath)
        except TypeError:
            path = "-"
        proc = _Popen(
            [ffmpeg_exe, "-i", path, "-hide_banner", "-f", "null", "-"],
            stdout=_PIPE, stderr=_PIPE,
        )
        _, stderr_bytes = proc.communicate()
        stderr = stderr_bytes.decode("utf-8", "ignore")

        info = {"streams": [], "format": {}}

        # Parse duration (bitrate may be absent for some formats)
        dur_m = _re.search(
            r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", stderr
        )
        if dur_m:
            duration = int(dur_m.group(1)) * 3600 + int(dur_m.group(2)) * 60 + float(dur_m.group(3))
            info["format"]["duration"] = str(duration)
        br_m = _re.search(r"bitrate:\s*(\d+)\s*kb/s", stderr)
        if br_m:
            info["format"]["bit_rate"] = str(int(br_m.group(1)) * 1000)

        # Parse first audio stream by capturing everything after "Audio:" to EOL,
        # then splitting on ", " to get positional fields:
        #   codec (extra), sample_rate Hz, layout, sample_fmt, bitrate kb/s
        stream_m = _re.search(
            r"Stream #(\d+):(\d+)[^:]*: Audio:\s*(.+)", stderr
        )
        if stream_m:
            idx = int(stream_m.group(2))
            parts = [p.strip() for p in stream_m.group(3).split(", ")]
            # First part is always codec (may include parenthetical like "pcm_s16le ([1][0]...)")
            codec = parts[0].split()[0].rstrip(",") if parts else "unknown"

            sample_rate = "44100"
            channels = 2
            sample_fmt = ""
            stream_bitrate = None

            for part in parts[1:]:
                if part.endswith("Hz"):
                    sample_rate = _re.search(r"(\d+)\s*Hz", part).group(1)
                elif part.endswith("kb/s"):
                    m = _re.search(r"(\d+)\s*kb/s", part)
                    if m:
                        stream_bitrate = str(int(m.group(1)) * 1000)
                elif part.lower() in _CHANNEL_MAP:
                    channels = _CHANNEL_MAP[part.lower()]
                elif _re.match(r"^[su]\d+p?$", part):
                    # Integer sample format: s16, s32, u8, s16p, etc.
                    sample_fmt = part
                elif part in ("flt", "fltp", "dbl", "dblp"):
                    sample_fmt = part
                elif _re.match(r"^(mono|stereo)$", part, _re.IGNORECASE):
                    channels = _CHANNEL_MAP[part.lower()]

            # Extract bits_per_sample from sample_fmt
            _FMT_BITS = {"flt": 32, "fltp": 32, "dbl": 64, "dblp": 64}
            if sample_fmt in _FMT_BITS:
                bits_per_sample = _FMT_BITS[sample_fmt]
            else:
                bits_m = _re.search(r"(\d+)", sample_fmt)
                bits_per_sample = int(bits_m.group(1)) if bits_m else 0

            stream = {
                "index": idx,
                "codec_type": "audio",
                "codec_name": codec,
                "sample_rate": sample_rate,
                "channels": channels,
                "bits_per_sample": bits_per_sample,
                "bits_per_raw_sample": bits_per_sample,
                "sample_fmt": sample_fmt,
                "duration": info["format"].get("duration", "0"),
            }
            if stream_bitrate:
                stream["bit_rate"] = stream_bitrate
            info["streams"].append(stream)

        return info

    import pydub.utils
    import pydub.audio_segment
    pydub.utils.mediainfo_json = _ffmpeg_mediainfo_json
    pydub.audio_segment.mediainfo_json = _ffmpeg_mediainfo_json
    print(f"[Info] ffprobe not found - using ffmpeg-based probe fallback", file=sys.stderr)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from transcribe import transcribe_audio, warmup_model
from profanity_detector import flag_profanity
from audio_processor import censor_audio, censor_audio_vocals_only
from vocal_separator import separate as separate_vocals
from device_info import detect_device
from lyrics_fetcher import extract_metadata, fetch_lyrics, find_lyrics_profanity, parse_synced_lyrics
from lyrics_corrector import (
    correct_words_with_lyrics, fill_gaps_with_lyrics, fill_gaps_with_plain_lyrics,
    extract_profanity_vocab, flag_with_profanity_vocab,
)


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
    dual_pass: bool = True
    vocals_path: str | None = None
    lyrics: str | None = None
    synced_lyrics: str | None = None


class CensorWord(BaseModel):
    word: str
    start: float
    end: float
    censor_type: str = "mute"  # "mute", "beep", "reverse", or "tape_stop"
    detection_source: str | None = None


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
    padding_before_ms: int = 50
    padding_after_ms: int = 250


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/warmup")
async def warmup():
    """Pre-download and load the transcription model with progress reporting."""
    return StreamingResponse(
        _streaming_heartbeat_wrapper(warmup_model),
        media_type="application/x-ndjson",
    )


@app.get("/device-info")
async def device_info():
    return detect_device()


class FetchLyricsRequest(BaseModel):
    artist: str
    title: str
    duration: float | None = None


@app.post("/metadata")
def metadata(req: MetadataRequest):
    req.path = unquote(req.path)
    if not os.path.isfile(req.path):
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")
    return extract_metadata(req.path)


@app.post("/fetch-lyrics")
def fetch_lyrics_endpoint(req: FetchLyricsRequest):
    result = fetch_lyrics(req.artist, req.title, req.duration)
    if result is None:
        return {"plain_lyrics": None, "synced_lyrics": None, "lyrics_source": None}
    return result


def merge_word_lists(
    primary_words: list[dict],
    secondary_words: list[dict],
    overlap_threshold: float = 0.3,
    import_all: bool = False,
) -> list[dict]:
    """Merge two transcription word lists, importing detections from secondary.

    When import_all is False (default), only profanity from the secondary pass
    is imported. When True, all non-overlapping words are imported — used when
    the primary pass produced very few words (sparse transcription).
    """
    merged = [w.copy() for w in primary_words]

    for sec_word in secondary_words:
        if not import_all and not sec_word.get("is_profanity"):
            continue  # Only import profanity detections from vocals pass

        is_duplicate = False
        for i, pri_word in enumerate(merged):
            # Check temporal overlap
            overlap = min(sec_word["end"], pri_word["end"]) - max(sec_word["start"], pri_word["start"])
            if overlap > 0:
                if sec_word.get("is_profanity"):
                    # Only absorb as duplicate if the words match or primary is already profanity
                    if (sec_word["word"].lower().strip() == pri_word["word"].lower().strip()
                            or pri_word.get("is_profanity")):
                        merged[i]["is_profanity"] = True
                        merged[i]["detection_source"] = "vocals"
                        merged[i]["start"] = sec_word["start"]
                        merged[i]["end"] = sec_word["end"]
                        is_duplicate = True
                        break
                else:
                    # Non-profane word overlaps with existing — skip it
                    is_duplicate = True
                    break
            # Check near-miss with same word text
            gap = min(
                abs(sec_word["start"] - pri_word["end"]),
                abs(pri_word["start"] - sec_word["end"]),
            )
            if gap < overlap_threshold and sec_word["word"].lower() == pri_word["word"].lower():
                if sec_word.get("is_profanity"):
                    merged[i]["is_profanity"] = True
                    merged[i]["detection_source"] = "vocals"
                    merged[i]["start"] = sec_word["start"]
                    merged[i]["end"] = sec_word["end"]
                is_duplicate = True
                break

        if not is_duplicate:
            source = "adlib" if sec_word.get("is_profanity") else "vocals_fill"
            merged.append({**sec_word, "detection_source": source})

    merged.sort(key=lambda w: w["start"])
    return merged


@app.post("/transcribe")
async def transcribe(req: TranscribeRequest):
    req.path = unquote(req.path)
    if req.vocals_path:
        req.vocals_path = unquote(req.vocals_path)
    if not os.path.isfile(req.path):
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")

    dual_pass = req.dual_pass and req.vocals_path and os.path.isfile(req.vocals_path)

    def _strip_intro_hallucinations(words: list[dict], min_confidence: float = 0.5) -> list[dict]:
        """Remove low-confidence words from the start that are likely
        Whisper hallucinations during an instrumental intro."""
        first_confident_idx = 0
        for i, w in enumerate(words):
            if w.get("confidence", 0) >= min_confidence:
                first_confident_idx = i
                break
        else:
            return words  # No confident words at all, keep everything

        if first_confident_idx >= 3:
            stripped = words[first_confident_idx:]
            print(
                f"[Pipeline] Stripped {first_confident_idx} intro hallucinations "
                f"(first confident word at {stripped[0].get('start', 0):.1f}s: '{stripped[0].get('word', '')}')",
                file=sys.stderr,
            )
            return stripped
        return words

    def _do_transcribe():
        # Pass 1: Transcribe the full mix
        if dual_pass:
            result = transcribe_audio(
                req.path, turbo=req.turbo, initial_prompt=req.lyrics,
                progress_offset=0, progress_scale=45,
            )
        else:
            result = transcribe_audio(req.path, turbo=req.turbo, initial_prompt=req.lyrics)

        detected_language = result["language"]
        primary_words = flag_profanity(result["words"], language=detected_language)
        primary_words = _strip_intro_hallucinations(primary_words)

        # Pass 2: Transcribe isolated vocals (if available)
        if dual_pass:
            vocals_result = transcribe_audio(
                req.vocals_path,
                turbo=req.turbo,
                language=detected_language,
                initial_prompt=req.lyrics,
                progress_offset=50,
                progress_scale=45,
                sensitive_mode=True,
            )
            secondary_words = flag_profanity(vocals_result["words"], language=detected_language)
            raw_count = len(secondary_words)
            raw_profanity = sum(1 for w in secondary_words if w.get("is_profanity"))
            secondary_words = [w for w in secondary_words if w.get("confidence", 1.0) >= 0.15]
            # If the primary pass produced very few words relative to audio
            # duration, import ALL vocals-pass words (not just profanity) to
            # fill in the missing lyrics.
            word_density = len(primary_words) / max(result["duration"], 1.0)
            sparse = word_density < 0.5
            print(
                f"[Dual-Pass] Vocals pass: {len(vocals_result['words'])} words, "
                f"{raw_profanity} profanity, "
                f"{len(secondary_words)} after confidence filter (removed {raw_count - len(secondary_words)})"
                f"{' - PRIMARY SPARSE, importing all vocals words' if sparse else ''}",
                file=sys.stderr,
            )
            final_words = merge_word_lists(primary_words, secondary_words, import_all=sparse)
        else:
            final_words = primary_words

        # Correct misheard words using synced lyrics (fuzzy matching)
        alignment_score = 0.0
        if req.synced_lyrics:
            final_words, alignment_score = correct_words_with_lyrics(final_words, req.synced_lyrics)

        # Gate timing-dependent features on alignment quality.
        # Low alignment (<25%) indicates lyrics don't match the audio
        # (e.g., remix with reordered/chopped vocals) — skip gap-fill and
        # lyrics-based profanity discovery that would inject garbage.
        # Alignment gating only applies to synced lyrics (which have timestamps).
        # Plain lyrics gap-fill uses its own alignment detection and is always attempted.
        lyrics_aligned = alignment_score >= 0.25

        if req.synced_lyrics and lyrics_aligned:
            pre_count = len(final_words)
            final_words = fill_gaps_with_lyrics(
                final_words, req.synced_lyrics, audio_duration=result["duration"]
            )
            if len(final_words) == pre_count:
                # Synced gap-fill bailed (typically a remix/edit where the original
                # lyrics span longer than the audio, tripping its 2x-word safeguard).
                # Plain gap-fill uses anchor interpolation between matched words,
                # which adapts to whatever the audio's actual timing is.
                plain_from_synced = "\n".join(
                    line["text"] for line in parse_synced_lyrics(req.synced_lyrics)
                )
                if plain_from_synced.strip():
                    print(
                        "[Pipeline] Synced gap-fill bailed; falling back to plain gap-fill (anchor-based).",
                        file=sys.stderr,
                    )
                    final_words = fill_gaps_with_plain_lyrics(
                        final_words, plain_from_synced, result["duration"]
                    )
        elif not req.synced_lyrics and req.lyrics:
            # Fallback: use plain lyrics (no timestamps) with sequence alignment
            final_words = fill_gaps_with_plain_lyrics(
                final_words, req.lyrics, result["duration"]
            )
        elif req.synced_lyrics and not lyrics_aligned:
            print(
                f"[Pipeline] Poor lyrics alignment ({alignment_score:.0%}), "
                f"skipping gap-fill and lyrics profanity discovery",
                file=sys.stderr,
            )

        # Re-flag profanity on all words (corrected words may now be profane,
        # gap-filled words haven't been checked yet)
        if req.synced_lyrics or req.lyrics:
            final_words = flag_profanity(final_words)

        # Cross-reference with synced lyrics to find missed profanities
        if req.synced_lyrics and lyrics_aligned:
            lyrics_detections = find_lyrics_profanity(req.synced_lyrics, final_words)
            if lyrics_detections:
                final_words = final_words + lyrics_detections
                final_words.sort(key=lambda w: w["start"])

        # Time-agnostic profanity vocab check — works even for remixes
        # where lyrics timing doesn't match. Uses plain lyrics (or synced
        # lyrics text) to extract profanity vocabulary and fuzzy-match
        # against transcribed words.
        lyrics_for_vocab = req.lyrics or req.synced_lyrics
        if lyrics_for_vocab:
            profanity_vocab = extract_profanity_vocab(lyrics_for_vocab)
            if profanity_vocab:
                final_words = flag_with_profanity_vocab(final_words, profanity_vocab)

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
    req.path = unquote(req.path)
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
    req.path = unquote(req.path)
    if req.vocals_path:
        req.vocals_path = unquote(req.vocals_path)
    if req.accompaniment_path:
        req.accompaniment_path = unquote(req.accompaniment_path)
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
                padding_before_ms=req.padding_before_ms,
                padding_after_ms=req.padding_after_ms,
                source_path=req.path,
            )
        else:
            result_path = censor_audio(
                req.path, words_dicts, preview_path,
                crossfade_ms=req.crossfade_ms,
                padding_before_ms=req.padding_before_ms,
                padding_after_ms=req.padding_after_ms,
            )

        return {"output_path": result_path}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/censor")
def censor(req: CensorRequest):
    req.path = unquote(req.path)
    if req.vocals_path:
        req.vocals_path = unquote(req.vocals_path)
    if req.accompaniment_path:
        req.accompaniment_path = unquote(req.accompaniment_path)
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
                padding_before_ms=req.padding_before_ms,
                padding_after_ms=req.padding_after_ms,
                source_path=req.path,
            )
        else:
            result_path = censor_audio(
                req.path, words_dicts, output_path,
                crossfade_ms=req.crossfade_ms,
                padding_before_ms=req.padding_before_ms,
                padding_after_ms=req.padding_after_ms,
            )

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
