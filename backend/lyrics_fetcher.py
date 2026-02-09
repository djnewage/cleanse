"""Lyrics fetching from LRCLIB and audio metadata extraction."""

import re
import sys

import requests
from tinytag import TinyTag

from better_profanity import profanity

profanity.load_censor_words()

LRCLIB_BASE = "https://lrclib.net/api"
USER_AGENT = "Cleanse Audio Censor App/1.0 (https://github.com/cleanse)"
REQUEST_TIMEOUT = 5  # seconds


def extract_metadata(file_path: str) -> dict:
    """Extract artist, title, album, and duration from audio file tags."""
    try:
        tag = TinyTag.get(file_path)
        return {
            "artist": tag.artist,
            "title": tag.title,
            "album": tag.album,
            "duration": round(tag.duration, 3) if tag.duration else None,
        }
    except Exception as e:
        print(f"[Lyrics] Failed to extract metadata: {e}", file=sys.stderr)
        return {"artist": None, "title": None, "album": None, "duration": None}


def fetch_lyrics(artist: str | None, title: str | None, duration: float | None = None) -> dict | None:
    """Fetch lyrics from LRCLIB. Returns {plain_lyrics, synced_lyrics} or None."""
    if not artist or not title:
        return None

    headers = {"User-Agent": USER_AGENT}

    # Try exact match first
    try:
        params = {"artist_name": artist, "track_name": title}
        if duration is not None:
            params["duration"] = str(int(duration))

        resp = requests.get(
            f"{LRCLIB_BASE}/get",
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("plainLyrics") or data.get("syncedLyrics"):
                print(f"[Lyrics] Found exact match for '{artist} - {title}'", file=sys.stderr)
                return {
                    "plain_lyrics": data.get("plainLyrics"),
                    "synced_lyrics": data.get("syncedLyrics"),
                }
    except Exception as e:
        print(f"[Lyrics] Exact match failed: {e}", file=sys.stderr)

    # Fallback to search
    try:
        params = {"track_name": title, "artist_name": artist}
        resp = requests.get(
            f"{LRCLIB_BASE}/search",
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            results = resp.json()
            if results and len(results) > 0:
                best = results[0]
                if best.get("plainLyrics") or best.get("syncedLyrics"):
                    print(f"[Lyrics] Found search match for '{artist} - {title}'", file=sys.stderr)
                    return {
                        "plain_lyrics": best.get("plainLyrics"),
                        "synced_lyrics": best.get("syncedLyrics"),
                    }
    except Exception as e:
        print(f"[Lyrics] Search failed: {e}", file=sys.stderr)

    print(f"[Lyrics] No lyrics found for '{artist} - {title}'", file=sys.stderr)
    return None


def parse_synced_lyrics(synced_lyrics: str) -> list[dict]:
    """Parse LRC format synced lyrics into [{time: float, text: str}]."""
    lines = []
    pattern = re.compile(r"\[(\d+):(\d+\.\d+)\]\s*(.*)")
    for line in synced_lyrics.strip().split("\n"):
        match = pattern.match(line.strip())
        if match:
            minutes = int(match.group(1))
            seconds = float(match.group(2))
            text = match.group(3).strip()
            if text:
                lines.append({"time": minutes * 60 + seconds, "text": text})
    return lines


def find_lyrics_profanity(
    synced_lyrics: str,
    transcribed_words: list[dict],
    overlap_threshold: float = 0.75,
) -> list[dict]:
    """Find profanities in synced lyrics that weren't detected by transcription."""
    lines = parse_synced_lyrics(synced_lyrics)
    if not lines:
        return []

    new_detections = []

    for i, line in enumerate(lines):
        # Determine line duration (time to next line, capped at 5s)
        next_time = lines[i + 1]["time"] if i + 1 < len(lines) else line["time"] + 5.0
        line_duration = min(next_time - line["time"], 5.0)

        words_in_line = line["text"].split()
        num_words = max(len(words_in_line), 1)
        word_duration = line_duration / num_words

        for j, word in enumerate(words_in_line):
            if not profanity.contains_profanity(word):
                continue

            # Estimate word timestamp: center each word in its slot within the line
            estimated_start = line["time"] + j * word_duration
            estimated_end = estimated_start + min(word_duration, 0.35)

            # Check if any transcribed profanity exists near this timestamp
            already_detected = any(
                abs(tw["start"] - estimated_start) < overlap_threshold
                and tw.get("is_profanity")
                for tw in transcribed_words
            )

            if not already_detected:
                # Clean the word for display (remove punctuation)
                clean_word = re.sub(r"[^\w'*@$]", "", word)
                if clean_word:
                    new_detections.append({
                        "word": clean_word,
                        "start": round(estimated_start, 3),
                        "end": round(estimated_end, 3),
                        "confidence": 0.5,
                        "is_profanity": True,
                        "detection_source": "lyrics",
                    })

    return new_detections
