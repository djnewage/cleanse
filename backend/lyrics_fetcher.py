"""Lyrics fetching from LRCLIB, Genius, and audio metadata extraction."""

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from tinytag import TinyTag

# NOTE: never call better_profanity's profanity.load_censor_words() from this
# module — it resets the shared singleton to defaults and silently drops the
# custom (EN and ES) wordlists that profanity_detector loads at import.

LRCLIB_BASE = "https://lrclib.net/api"
USER_AGENT = "Cleanse Audio Censor App/1.0 (https://github.com/cleanse)"
REQUEST_TIMEOUT = (5, 15)  # (connect, read) — LRCLIB search can take ~10s on slow links

# Max |candidate - audio| duration difference to accept a search hit as the
# same version of the song. LRCLIB's own /get endpoint matches at ±2s; tags
# and encoders disagree by a couple seconds; distinct versions (radio edit,
# DJ edit, extended) differ by 10s+. A wrong-version hit means every synced
# timestamp is offset — worse than no synced lyrics at all.
LRCLIB_DURATION_TOLERANCE_S = 5.0

# Genius API — lazy-initialized client
_GENIUS_TOKEN = os.environ.get(
    "GENIUS_API_TOKEN",
    "GJ250xj50QesijWDbSUdSTFfYaS6bXvVcsrGhgQlS0vrRywaPf6LA4QegQi_pwIT",
)
_genius = None


def _get_genius():
    """Lazy-initialize the Genius client."""
    global _genius
    if _genius is None:
        try:
            import lyricsgenius
            _genius = lyricsgenius.Genius(
                _GENIUS_TOKEN,
                remove_section_headers=True,
                retries=1,
                timeout=8,
            )
        except Exception as e:
            print(f"[Lyrics] Failed to initialize Genius client: {e}", file=sys.stderr)
    return _genius


def _clean_genius_lyrics(raw: str) -> str:
    """Strip contributor header and trailing 'Embed' from Genius lyrics."""
    lines = raw.strip().split("\n")

    # First line is often "N ContributorsSong Title Lyrics" — remove if it matches
    if lines and re.match(r'^\d+\s+Contributor', lines[0]):
        lines = lines[1:]

    # Last line often ends with "...Embed" or just "Embed"
    if lines and lines[-1].rstrip().endswith("Embed"):
        lines[-1] = re.sub(r'\d*Embed$', '', lines[-1]).rstrip()
        if not lines[-1]:
            lines = lines[:-1]

    return "\n".join(lines).strip()


def _clean_search_title(title: str) -> str:
    """Strip version/edit suffixes and production credits that confuse lyrics APIs.

    Handles both simple tags like (remix) and named variants like
    (Red Sip Remix), (DJ Snake Edit), (Cheyenne Giles Remix).
    Also strips [Shot By ...], [Prod By ...], [Official Video], etc.
    """
    # Strip all bracketed tags [anything] — these are almost never part of the song title
    cleaned = re.sub(r'\s*\[[^\]]*\]', '', title)

    # Strip version/edit suffixes in parentheses
    cleaned = re.sub(
        r'\s*\('
        r'(?:[^)]*?\s)?'  # optional prefix words (e.g., "Red Sip ", "DJ Snake ")
        r'(?:intro|outro|edit|remix|deluxe|clean|dirty|explicit|radio|'
        r'extended|original|remaster|remastered|acoustic|live|demo|instrumental|version|'
        r'skit|interlude|bonus|album|single|prod|shot)'
        r'(?:\s*(?:edit|mix|version|cut|by)[^)]*)?'
        r'\s*\)',
        '', cleaned, flags=re.IGNORECASE
    )

    # Clean trailing dashes, spaces, and dots
    cleaned = cleaned.strip(' -.')

    return cleaned or title


def _looks_like_lyrics(text: str) -> bool:
    """Basic heuristic: reject content that doesn't look like song lyrics."""
    lines = [l for l in text.strip().split('\n') if l.strip()]
    if not lines:
        return False

    # Lyrics are typically short lines; prose has long paragraphs
    avg_line_len = sum(len(l) for l in lines) / len(lines)
    if avg_line_len > 120:
        return False

    # Lyrics typically have many short lines (< 80 chars)
    short_lines = sum(1 for l in lines if len(l.strip()) < 80)
    if short_lines / len(lines) < 0.5:
        return False

    return True


def _artist_matches(requested: str, returned: str) -> bool:
    """Check if returned artist reasonably matches requested artist."""
    req = requested.lower().strip()
    ret = returned.lower().strip()
    if req in ret or ret in req:
        return True
    first_req = _extract_first_artist(requested).lower()
    first_ret = _extract_first_artist(returned).lower()
    if first_req in first_ret or first_ret in first_req:
        return True
    return False


def fetch_genius_lyrics(artist: str, title: str) -> str | None:
    """Fetch plain lyrics from Genius. Returns cleaned text or None."""
    genius = _get_genius()
    if genius is None:
        return None

    # Try cleaned title first, then original if different
    titles_to_try = [_clean_search_title(title)]
    if titles_to_try[0] != title:
        titles_to_try.append(title)

    # Try the full artist string first; if Genius returns a translation page or
    # wrong artist (common for multi-artist tags like "X & Y"), retry with just
    # the primary artist. Mirrors LRCLIB's fallback at _fetch_lrclib step 3.
    artists_to_try = [artist]
    first_artist = _extract_first_artist(artist)
    if first_artist and first_artist != artist:
        artists_to_try.append(first_artist)

    for search_artist in artists_to_try:
        for search_title in titles_to_try:
            try:
                song = genius.search_song(search_title, search_artist)
                if song and song.lyrics:
                    # Validate artist match against the ORIGINAL requested artist
                    # (not search_artist) so a first-artist-only search still has
                    # to come back with someone in the original credits.
                    if song.artist and not _artist_matches(artist, song.artist):
                        print(f"[Lyrics] Genius artist mismatch: requested '{search_artist}', got '{song.artist}'", file=sys.stderr)
                        continue

                    cleaned = _clean_genius_lyrics(song.lyrics)
                    if not cleaned:
                        continue

                    # Validate content looks like lyrics (not prose/essays)
                    if not _looks_like_lyrics(cleaned):
                        print(f"[Lyrics] Genius result rejected (doesn't look like lyrics) for '{search_artist} - {search_title}'", file=sys.stderr)
                        continue

                    print(f"[Lyrics] Found Genius lyrics for '{search_artist} - {search_title}'", file=sys.stderr)
                    return cleaned
            except Exception as e:
                print(f"[Lyrics] Genius search failed for '{search_title}': {e}", file=sys.stderr)

    return None


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


def _extract_first_artist(artist: str) -> str:
    """
    Extract the first/primary artist from a multi-artist string.

    Examples:
        "Playboi Carti, Future, & Travis Scott" → "Playboi Carti"
        "Playboi Carti & Future" → "Playboi Carti"
        "Playboi Carti ft. Future" → "Playboi Carti"
        "Playboi Carti feat. Future" → "Playboi Carti"
        "Playboi Carti (feat. Future)" → "Playboi Carti"
    """
    # Remove parenthetical featured artists first: "Artist (feat. Other)" → "Artist"
    # This must be done before splitting to handle cases like "Artist (feat. Other)"
    cleaned = re.sub(r'\s*\([^)]*feat[\.\\s][^)]*\)', '', artist, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*\([^)]*ft[\.\\s][^)]*\)', '', cleaned, flags=re.IGNORECASE)

    # Split on common delimiters and take first part (case-insensitive)
    lower = cleaned.lower()
    for delimiter in [',', ' & ', ' and ', ' ft.', ' ft ', ' feat.', ' feat ', ' featuring ']:
        if delimiter in lower:
            idx = lower.index(delimiter)
            first = cleaned[:idx].strip()
            # Remove trailing parentheses if present
            first = first.rstrip('(').strip()
            return first

    first = cleaned

    return first.strip(' -.').strip()


def _lrclib_search(params: dict, headers: dict) -> list[dict]:
    """GET LRCLIB /search; returns [] on any error."""
    try:
        resp = requests.get(
            f"{LRCLIB_BASE}/search",
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json() or []
    except Exception as e:
        print(f"[Lyrics] LRCLIB search failed ({params.get('artist_name', 'title-only')}): {e}", file=sys.stderr)
    return []


def _select_lrclib_result(
    results: list[dict],
    duration: float | None,
    tolerance: float = LRCLIB_DURATION_TOLERANCE_S,
) -> tuple[dict | None, bool]:
    """Pick the best LRCLIB search hit. Returns (entry, duration_matched).

    Only entries carrying lyrics qualify. When the audio duration is known,
    the first entry within ``tolerance`` seconds wins; if none is, the first
    entry with lyrics is returned flagged as a mismatch so the caller can
    salvage its text without trusting its timestamps. Unknown audio duration
    keeps the legacy first-hit behavior.
    """
    with_lyrics = [r for r in results if r.get("plainLyrics") or r.get("syncedLyrics")]
    if not with_lyrics:
        return None, False
    if duration is None:
        return with_lyrics[0], True
    for r in with_lyrics:
        rd = r.get("duration")
        if isinstance(rd, (int, float)) and abs(rd - duration) <= tolerance:
            return r, True
    return with_lyrics[0], False


def _fetch_lrclib(
    artist: str, title: str, duration: float | None = None,
    allow_title_only: bool = True,
) -> dict | None:
    """Fetch lyrics from LRCLIB with progressive fallback. Returns
    {plain_lyrics, synced_lyrics[, duration_mismatch]} or None.

    ``allow_title_only=False`` disables the title-only search step. Title-only
    ignores the artist entirely, so it must not run for guessed metadata
    interpretations: a swapped-tags guess turned the artist name into a
    "title", and a title-only search returned a different song by the same
    artist whose duration matched the audio by coincidence (measured: a 226s
    mashup fetched 230s 'Hypnotize' synced lyrics, which then poisoned the
    transcription prompt and word corrections)."""
    headers = {"User-Agent": USER_AGENT}

    # Clean title for search (strip version/edit suffixes)
    clean_title = _clean_search_title(title)

    # STEP 1: Try exact match with full artist name
    try:
        params = {"artist_name": artist, "track_name": clean_title}
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
                print(f"[Lyrics] Found LRCLIB exact match for '{artist} - {title}'", file=sys.stderr)
                return {
                    "plain_lyrics": data.get("plainLyrics"),
                    "synced_lyrics": data.get("syncedLyrics"),
                }
    except Exception as e:
        print(f"[Lyrics] LRCLIB exact match failed: {e}", file=sys.stderr)

    # STEPS 2-4: search fallbacks, duration-verified. A hit whose duration
    # doesn't match the audio is a different version/edit of the song — its
    # synced timestamps would misplace every downstream mute (observed: a
    # 183s DJ edit matched against 147s official-single lyrics).
    # A duration-mismatched hit is only trustworthy as "same song, different
    # edit" when the ARTIST matched. A title-only hit with the wrong duration
    # is more likely a different song sharing the title (measured: a punk
    # song's lyrics fetched for a rap track both called 'S.M.D.') — using its
    # text pollutes the karaoke and the profanity vocab.
    attempts = [("search", {"track_name": clean_title, "artist_name": artist}, True)]
    first_artist = _extract_first_artist(artist)
    if first_artist and first_artist != artist:
        attempts.append(("first-artist", {"track_name": clean_title, "artist_name": first_artist}, True))
    if allow_title_only:
        attempts.append(("title-only", {"track_name": clean_title}, False))

    mismatch = None  # first duration-mismatched entry, kept as plain-only fallback
    for label, params, allow_mismatch in attempts:
        entry, duration_matched = _select_lrclib_result(
            _lrclib_search(params, headers), duration
        )
        if entry and duration_matched:
            print(f"[Lyrics] Found LRCLIB {label} match for '{artist} - {title}'", file=sys.stderr)
            return {
                "plain_lyrics": entry.get("plainLyrics"),
                "synced_lyrics": entry.get("syncedLyrics"),
            }
        if entry and allow_mismatch and mismatch is None:
            mismatch = (label, entry)

    if mismatch:
        label, entry = mismatch
        print(
            f"[Lyrics] LRCLIB {label} match for '{artist} - {title}' is a different "
            f"version ({entry.get('duration')}s vs audio {duration:.0f}s) — "
            f"dropping synced timestamps, keeping plain lyrics",
            file=sys.stderr,
        )
        plain = entry.get("plainLyrics")
        if not plain and entry.get("syncedLyrics"):
            # Same-song lyrics text is still useful (the plain-lyrics pipeline
            # aligns by content, not time) — strip the wrong timestamps.
            plain = "\n".join(
                line["text"] for line in parse_synced_lyrics(entry["syncedLyrics"])
            )
        return {
            "plain_lyrics": plain,
            "synced_lyrics": None,
            "duration_mismatch": True,
        }

    return None


# On-disk cache for fetch_lyrics results. LRCLIB regularly takes 15s+ (and the
# 20s future can time out entirely), so re-processing a song re-pays the whole
# fetch. Positive results only — a miss might be filled on LRCLIB/Genius later.
LYRICS_CACHE_TTL_S = 30 * 24 * 3600
_LYRICS_CACHE_DIR = os.path.join(tempfile.gettempdir(), "cleanse-lyrics-cache")


def _lyrics_cache_path(
    artist: str | None, title: str | None, duration: float | None, filename: str | None = None
) -> str:
    # v2: invalidates entries cached before the title-only/fallback-candidate
    # restriction — those can hold a coincidentally-duration-matched wrong song.
    key = (
        f"v2|{(artist or '').lower().strip()}|{(title or '').lower().strip()}"
        f"|{int(duration) if duration else -1}|{(filename or '').lower().strip()}"
    )
    return os.path.join(
        _LYRICS_CACHE_DIR, hashlib.sha1(key.encode("utf-8")).hexdigest() + ".json"
    )


def _lyrics_cache_get(path: str) -> dict | None:
    try:
        if time.time() - os.path.getmtime(path) > LYRICS_CACHE_TTL_S:
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _lyrics_cache_put(path: str, result: dict) -> None:
    try:
        os.makedirs(_LYRICS_CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(result, f)
        os.replace(tmp, path)
    except OSError as e:
        print(f"[Lyrics] Cache write failed: {e}", file=sys.stderr)


# Junk that streaming-rip sites embed in tags/filenames. A domain token, a
# quality marker, or an ®/™ mark is never part of a real artist or title.
_JUNK_TOKEN_RE = re.compile(
    r"""
    \b\S+\.(?:com|net|org|io|cc|co|me|to|xyz)\b   # site domains (SoundLoadMate.com)
    | [®™©]
    | \bofficial\s+(?:music\s+)?(?:video|audio|visualizer)\b
    | \blyrics?\s*(?:video)?\b
    | \b(?:hd|hq|4k|320\s*kbps|128\s*kbps|mp3|flac)\b
    | \bfree\s+download\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _strip_junk(text: str) -> str:
    """Remove rip-site pollution from a tag/filename fragment."""
    cleaned = _JUNK_TOKEN_RE.sub(" ", text)
    cleaned = cleaned.replace("_", " ")
    # NOTE: '.' is deliberately not stripped — titles like "S.M.D." keep it.
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—|")
    return cleaned.strip()


def _split_segments(text: str) -> list[str]:
    """Split 'A - B - C' style strings into cleaned, non-junk segments."""
    segments = []
    for seg in re.split(r"\s+[-–—]\s+", text):
        seg = _strip_junk(seg)
        if not seg:
            continue
        if re.fullmatch(r"\d{1,3}", seg):   # bare track numbers ("05")
            continue
        segments.append(seg)
    return segments


def _metadata_candidates(
    artist: str | None, title: str | None, filename: str | None = None
) -> list[tuple[str, str]]:
    """Plausible (artist, title) interpretations of dirty metadata, best first.

    Streaming-rip files routinely carry the ripping channel as the artist and
    the real 'Artist - Title' crammed into the title field (measured:
    artist='Glo Radio ®', title='Chief Keef - Whos Concerned'), or no tags at
    all with everything in the filename. Search each interpretation — the
    validation layers (Genius artist match, LRCLIB duration gates, and the
    post-transcription content-quality gate) reject wrong guesses, so trying
    more interpretations only adds recall.
    """
    candidates: list[tuple[str, str]] = []

    def add(a: str | None, t: str | None) -> None:
        a, t = _strip_junk(a or ""), _strip_junk(t or "")
        if a and t and (a.lower(), t.lower()) not in [
            (x.lower(), y.lower()) for x, y in candidates
        ]:
            candidates.append((a, t))

    # 1. Tags as-is — correct for well-tagged libraries.
    add(artist, title)

    # 2. Real artist+title crammed into the title field.
    if title and re.search(r"\s+[-–—]\s+", title):
        segs = _split_segments(title)
        if len(segs) >= 2:
            add(segs[0], segs[1])

    # 3. Filename-derived.
    if filename:
        base = os.path.splitext(os.path.basename(filename))[0]
        segs = _split_segments(base)
        if len(segs) >= 2:
            add(segs[0], segs[1])

    # 4. Swapped tag fields (least likely; validation-protected).
    if artist and title and not re.search(r"\s+[-–—]\s+", f"{artist}{title}"):
        add(title, artist)

    return candidates[:4]


def _fetch_lyrics_round(
    artist: str, title: str, duration: float | None,
    allow_title_only: bool = True,
) -> dict | None:
    """One Genius+LRCLIB parallel fetch for a single (artist, title) guess."""
    genius_result = None
    lrclib_result = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        genius_future = executor.submit(fetch_genius_lyrics, artist, title)
        lrclib_future = executor.submit(
            _fetch_lrclib, artist, title, duration, allow_title_only
        )

        try:
            genius_result = genius_future.result(timeout=20)
        except Exception as e:
            print(f"[Lyrics] Genius future failed: {e}", file=sys.stderr)

        try:
            lrclib_result = lrclib_future.result(timeout=20)
        except Exception as e:
            print(f"[Lyrics] LRCLIB future failed: {e}", file=sys.stderr)

    # Merge results: prefer Genius plain lyrics, always use LRCLIB synced
    synced_lyrics = lrclib_result.get("synced_lyrics") if lrclib_result else None
    lrclib_plain = lrclib_result.get("plain_lyrics") if lrclib_result else None

    if genius_result:
        plain_lyrics = genius_result
        lyrics_source = "genius"
    elif lrclib_plain:
        plain_lyrics = lrclib_plain
        lyrics_source = "lrclib"
    else:
        plain_lyrics = None
        lyrics_source = None

    # If we have synced but no plain, source is lrclib
    if not plain_lyrics and synced_lyrics:
        lyrics_source = "lrclib"

    if not plain_lyrics and not synced_lyrics:
        return None

    return {
        "plain_lyrics": plain_lyrics,
        "synced_lyrics": synced_lyrics,
        "lyrics_source": lyrics_source,
        "duration_mismatch": bool(lrclib_result and lrclib_result.get("duration_mismatch")),
    }


def fetch_lyrics(
    artist: str | None,
    title: str | None,
    duration: float | None = None,
    filename: str | None = None,
) -> dict | None:
    """Fetch lyrics from Genius and LRCLIB in parallel, with a 30-day disk cache.

    Tries each plausible (artist, title) interpretation of the metadata (see
    _metadata_candidates) until one yields lyrics — dirty rip-site tags no
    longer kill the fetch. Returns {plain_lyrics, synced_lyrics, lyrics_source}
    or None. Genius plain lyrics preferred over LRCLIB plain; LRCLIB synced
    always used.
    """
    candidates = _metadata_candidates(artist, title, filename)
    if not candidates:
        return None

    cache_path = _lyrics_cache_path(artist, title, duration, filename)
    cached = _lyrics_cache_get(cache_path)
    if cached is not None:
        print(f"[Lyrics] Cache hit for '{artist} - {title}'", file=sys.stderr)
        return cached

    if len(candidates) > 1:
        print(
            f"[Lyrics] Trying {len(candidates)} metadata interpretations: "
            + "; ".join(f"'{a} - {t}'" for a, t in candidates),
            file=sys.stderr,
        )

    for idx, (cand_artist, cand_title) in enumerate(candidates):
        # Title-only search only for the tags-as-is interpretation; guessed
        # interpretations must corroborate the artist (see _fetch_lrclib).
        result = _fetch_lyrics_round(
            cand_artist, cand_title, duration, allow_title_only=(idx == 0)
        )
        if result is not None:
            # Lyrics from a guessed interpretation are validated downstream
            # (content-word gate) but must not bias the transcription itself:
            # the caller only uses them as Whisper's initial_prompt when this
            # flag is True.
            result["from_tag_metadata"] = idx == 0
            _lyrics_cache_put(cache_path, result)
            return result

    print(
        f"[Lyrics] No lyrics found after all attempts for '{artist} - {title}'",
        file=sys.stderr,
    )
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


# find_lyrics_profanity moved to lyrics_corrector.py: it now requires per-line
# corroboration against the transcript (_compute_word_similarity), and
# lyrics_corrector already imports from this module — the reverse import would
# be circular.
