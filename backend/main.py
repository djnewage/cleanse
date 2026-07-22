import argparse
import asyncio
import json as json_module
import multiprocessing
import os
import sys
import time
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
from typing import Literal

ExportFormat = Literal["mp3", "wav", "flac"]

from transcribe import (
    _report_progress, clamp_stretched_words, rescan_vocal_gaps,
    transcribe_audio, warmup_model,
)
from hook_echo import infer_hook_echoes
from profanity_detector import flag_profanity
from audio_processor import censor_audio, censor_audio_vocals_only
from vocal_separator import separate as separate_vocals
from device_info import detect_device
from lyrics_fetcher import extract_metadata, fetch_lyrics, parse_synced_lyrics
from lyrics_corrector import (
    correct_words_with_lyrics, fill_gaps_with_lyrics, fill_gaps_with_plain_lyrics,
    extract_profanity_vocab, flag_with_profanity_vocab, find_lyrics_profanity,
    find_plain_lyrics_profanity, lyrics_match_transcript, normalize_word_timeline,
)


def _purge_stale_previews() -> None:
    """Delete cleanse-preview files older than 24h on startup.

    Catches orphans from prior sessions where the renderer crashed or quit
    without giving the backend a chance to clean up.
    """
    import glob
    temp_dir = os.path.join(tempfile.gettempdir(), "cleanse-preview")
    if not os.path.isdir(temp_dir):
        return
    cutoff = time.time() - 24 * 3600
    for path in glob.glob(os.path.join(temp_dir, "*_preview_*")):
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError as e:
            print(f"[Startup] Could not remove stale preview {path}: {e}", file=sys.stderr)


_purge_stale_previews()


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
    # False when the lyrics came from a guessed metadata interpretation
    # (fetch_lyrics from_tag_metadata) — such lyrics may be a different song,
    # so they are excluded from Whisper's initial_prompt: a wrong prompt
    # degrades the transcription itself, which no downstream gate can undo.
    lyrics_from_tags: bool = True


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
    output_format: ExportFormat | None = None


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
    artist: str | None = None
    title: str | None = None
    duration: float | None = None
    # Original file name — used to derive (artist, title) candidates when the
    # tags are missing or rip-site polluted.
    file_name: str | None = None


@app.post("/metadata")
def metadata(req: MetadataRequest):
    req.path = unquote(req.path)
    if not os.path.isfile(req.path):
        raise HTTPException(status_code=400, detail=f"File not found: {req.path}")
    return extract_metadata(req.path)


@app.post("/fetch-lyrics")
def fetch_lyrics_endpoint(req: FetchLyricsRequest):
    result = fetch_lyrics(req.artist, req.title, req.duration, filename=req.file_name)
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


# Corrections tolerate mediocre alignment (worst case: a mislabeled word), but
# INJECTING words/mutes from LRC timestamps requires the timeline to really
# match. Repetitive songs score >=0.25 even with offset/wrong-version lyrics.
INJECTOR_ALIGNMENT_THRESHOLD = 0.5


def apply_lyrics_pipeline(
    final_words: list[dict],
    duration: float,
    detected_language: str,
    lyrics: str | None,
    synced_lyrics: str | None,
) -> list[dict]:
    """Post-transcription lyrics pipeline: correction, gap-fill, lyrics-based
    profanity discovery, and vocab flagging. Module-level so it can be run
    headless (tests, diagnostics) without the HTTP endpoint."""
    # Wrong-song guard, BEFORE any correction touches the words: synced lyrics
    # were previously trusted on duration alone, but duration coincidences
    # happen (measured: a 226s Biggie mashup fetched 230s 'Hypnotize' via a
    # swapped-tags title-only search, and its "corrections" rewrote real words
    # — including un-flagging profanity). The content-word gate separates a
    # right-song/shaky-timing fetch (which still aligns by content) from a
    # different song (which doesn't).
    if synced_lyrics:
        synced_text = "\n".join(
            line["text"] for line in parse_synced_lyrics(synced_lyrics)
        )
        if not lyrics_match_transcript(final_words, synced_text):
            print(
                "[Pipeline] Synced lyrics rejected: content doesn't match this "
                "recording — ignoring them entirely",
                file=sys.stderr,
            )
            synced_lyrics = None

    # Correct misheard words using synced lyrics (fuzzy matching)
    alignment_score = 0.0
    if synced_lyrics:
        final_words, alignment_score = correct_words_with_lyrics(final_words, synced_lyrics)

    # Gate timing-dependent features on alignment quality.
    # Low alignment (<25%) indicates lyrics don't match the audio
    # (e.g., remix with reordered/chopped vocals) — skip gap-fill and
    # lyrics-based profanity discovery that would inject garbage.
    # Alignment gating only applies to synced lyrics (which have timestamps).
    # Plain lyrics gap-fill uses its own alignment detection and is always attempted.
    #
    # INJECTORS need a higher bar than corrections: correcting a word can at
    # worst mislabel it, but trusting the lyrics' timestamps to ADD words/mutes
    # over clean audio needs the timeline to actually line up. Repetitive songs
    # clear 25% even when the lyrics are offset. In the 25-50% band we fall
    # back to the anchor-based plain path, which aligns by content, not time.
    lyrics_aligned = alignment_score >= 0.25
    lyrics_injection_ok = alignment_score >= INJECTOR_ALIGNMENT_THRESHOLD

    plain_from_synced = ""
    if synced_lyrics:
        plain_from_synced = "\n".join(
            line["text"] for line in parse_synced_lyrics(synced_lyrics)
        )

    if synced_lyrics and lyrics_injection_ok:
        pre_count = len(final_words)
        final_words = fill_gaps_with_lyrics(
            final_words, synced_lyrics, audio_duration=duration
        )
        if len(final_words) == pre_count and plain_from_synced.strip():
            # Synced gap-fill bailed (typically a remix/edit where the original
            # lyrics span longer than the audio, tripping its 2x-word safeguard).
            # Plain gap-fill uses anchor interpolation between matched words,
            # which adapts to whatever the audio's actual timing is.
            print(
                "[Pipeline] Synced gap-fill bailed; falling back to plain gap-fill (anchor-based).",
                file=sys.stderr,
            )
            final_words = fill_gaps_with_plain_lyrics(
                final_words, plain_from_synced, duration
            )
    elif synced_lyrics and lyrics_aligned:
        # 25-50% band: lyrics text is right but timing is shaky — use the
        # anchor-based plain path instead of trusting LRC timestamps.
        print(
            f"[Pipeline] Moderate lyrics alignment ({alignment_score:.0%}), "
            f"using anchor-based gap-fill instead of synced timestamps",
            file=sys.stderr,
        )
        if plain_from_synced.strip():
            final_words = fill_gaps_with_plain_lyrics(
                final_words, plain_from_synced, duration
            )
    elif not synced_lyrics and lyrics:
        # Fallback: use plain lyrics (no timestamps) with sequence alignment
        final_words = fill_gaps_with_plain_lyrics(
            final_words, lyrics, duration
        )
    elif synced_lyrics and not lyrics_aligned:
        print(
            f"[Pipeline] Poor lyrics alignment ({alignment_score:.0%}), "
            f"skipping gap-fill and lyrics profanity discovery",
            file=sys.stderr,
        )

    # Re-flag profanity on all words (corrected words may now be profane,
    # gap-filled words haven't been checked yet). Must pass language:
    # flag_profanity rebuilds is_profanity from scratch, so omitting it
    # un-flags Spanish compounds that pass 1 already caught.
    if synced_lyrics or lyrics:
        final_words = flag_profanity(final_words, language=detected_language)

    # Cross-reference with lyrics to find missed profanities. Synced lyrics use
    # real timestamps (per-line corroborated); in the moderate-alignment band
    # and for plain-only lyrics (e.g. Genius), the alignment-based plain
    # injector places them by content anchors instead.
    if synced_lyrics and lyrics_injection_ok:
        lyrics_detections = find_lyrics_profanity(synced_lyrics, final_words)
        if lyrics_detections:
            final_words = final_words + lyrics_detections
            final_words.sort(key=lambda w: w["start"])
    elif synced_lyrics and lyrics_aligned:
        if plain_from_synced.strip():
            plain_detections = find_plain_lyrics_profanity(
                final_words, plain_from_synced, duration
            )
            if plain_detections:
                final_words = final_words + plain_detections
                final_words.sort(key=lambda w: w["start"])
    elif not synced_lyrics and lyrics:
        plain_detections = find_plain_lyrics_profanity(
            final_words, lyrics, duration
        )
        if plain_detections:
            final_words = final_words + plain_detections
            final_words.sort(key=lambda w: w["start"])

    # Time-agnostic profanity vocab check — works even for remixes
    # where lyrics timing doesn't match. Uses plain lyrics (or synced
    # lyrics text) to extract profanity vocabulary and fuzzy-match
    # against transcribed words.
    lyrics_for_vocab = lyrics or synced_lyrics
    if lyrics_for_vocab:
        # Plain-only lyrics may be a same-title different song (title-collision
        # fetch); the synced path already passed the content-word gate at the
        # top of this pipeline.
        vocab_ok = True
        if lyrics and not synced_lyrics:
            vocab_ok = lyrics_match_transcript(final_words, lyrics)
            if not vocab_ok:
                print(
                    "[Pipeline] Skipping vocab flagging: lyrics don't match this recording",
                    file=sys.stderr,
                )
        if vocab_ok:
            profanity_vocab = extract_profanity_vocab(lyrics_for_vocab)
            if profanity_vocab:
                final_words = flag_with_profanity_vocab(
                    final_words, profanity_vocab, lyrics_text=lyrics_for_vocab,
                )

    # Last step, after all flags are final: enforce the karaoke timing
    # invariants (sorted, non-overlapping, positive durations). Running it
    # earlier would remove the estimated words the injectors use as dedup
    # anchors, and the profanity-transfer rule needs the final flags.
    final_words = normalize_word_timeline(final_words, audio_duration=duration)

    return final_words


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
        prompt_lyrics = req.lyrics if req.lyrics_from_tags else None
        if req.lyrics and not req.lyrics_from_tags:
            print(
                "[Transcribe] Lyrics came from guessed metadata — not using as "
                "initial_prompt (they still feed the post-transcription pipeline)",
                file=sys.stderr,
            )

        # Pass 1: Transcribe the full mix
        if dual_pass:
            result = transcribe_audio(
                req.path, turbo=req.turbo, initial_prompt=prompt_lyrics,
                progress_offset=0, progress_scale=45,
            )
        else:
            # Cap at 95 like the dual-pass path: the rescan/echo/lyrics stages
            # below own the last 5% and the "complete" message.
            result = transcribe_audio(
                req.path, turbo=req.turbo, initial_prompt=prompt_lyrics,
                progress_offset=0, progress_scale=95,
            )

        detected_language = result["language"]
        primary_words = flag_profanity(result["words"], language=detected_language)
        primary_words = _strip_intro_hallucinations(primary_words)

        # Pass 2: Transcribe isolated vocals (if available)
        if dual_pass:
            vocals_result = transcribe_audio(
                req.vocals_path,
                turbo=req.turbo,
                language=detected_language,
                initial_prompt=prompt_lyrics,
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

        # Cap timestamp-blowout words BEFORE the rescan coverage map is built:
        # a 5s stretched word blankets ad-lib energy and suppresses recovery
        # (and stalls the karaoke highlight). Profanity is exempt inside.
        final_words = clamp_stretched_words(final_words)

        # Vocal-gap rescan: transcribe unattributed-vocal-energy slices in
        # isolation to recover ad-libs both passes missed (Whisper attends to
        # the dominant voice and drops background shouts). Runs whenever a
        # vocals stem exists — separation happens even in single-pass mode.
        if req.vocals_path and os.path.isfile(req.vocals_path):
            _report_progress("analyzing", 95.5, "Scanning for missed ad-libs...")
            recovered = rescan_vocal_gaps(
                final_words, req.vocals_path,
                language=detected_language, turbo=req.turbo,
            )
            if recovered:
                recovered = flag_profanity(recovered, language=detected_language)
                final_words = final_words + recovered
                final_words.sort(key=lambda w: w["start"])

        # Hook-echo completion: ad-libs sung CONCURRENTLY with the lead are
        # invisible to every ASR pass (one voice per timespan) and leave no
        # energy gap for the rescan. Infer them from the hook's own completed
        # instances. Runs after the rescan so recovered words contribute
        # instances / occupy slots, and before the lyrics pipeline so its
        # injectors dedup against these and normalize resolves overlaps.
        vocals_ok = req.vocals_path and os.path.isfile(req.vocals_path)
        _report_progress("analyzing", 97.0, "Matching ad-lib echoes...")
        echoes = infer_hook_echoes(
            final_words,
            vocals_path=req.vocals_path if vocals_ok else None,
            language=detected_language,
        )
        if echoes:
            final_words = sorted(final_words + echoes, key=lambda w: w["start"])

        _report_progress("analyzing", 98.5, "Finalizing censor timeline...")
        final_words = apply_lyrics_pipeline(
            final_words, result["duration"], detected_language,
            req.lyrics, req.synced_lyrics,
        )
        _report_progress("complete", 100.0, "Transcription complete!")

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
        if req.output_format:
            ext = f".{req.output_format}"
        import time
        import glob
        # Cap cleanse-preview/ at one file per source song: every regen leaves
        # an orphaned 5-40 MB preview behind otherwise, which exhausts the temp
        # disk after a few format/crossfade toggles.
        for stale in glob.glob(os.path.join(temp_dir, f"{name}_preview_*")):
            try:
                os.remove(stale)
            except OSError as e:
                print(f"[Preview] Could not remove stale preview {stale}: {e}", file=sys.stderr)
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
            if req.output_format:
                ext = f".{req.output_format}"
            output_path = f"{base}_clean{ext}"
        elif req.output_format:
            # User picked a format but the dialog returned a path without the
            # matching extension — coerce. The dialog's typed extension still
            # wins if it's an explicit audio extension.
            existing_ext = os.path.splitext(output_path)[1].lower().lstrip(".")
            known_exts = {"mp3", "wav", "flac", "aiff", "aif", "ogg", "m4a"}
            if existing_ext not in known_exts:
                output_path = os.path.splitext(output_path)[0] + f".{req.output_format}"

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
