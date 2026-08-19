"""Carry DJ cue points, loops and beatgrids from the source file onto the export.

Serato, Traktor and Mixed In Key store their performance data inside the audio
file's own tags -- Serato as ID3 GEOB frames named "Serato Markers2" (cues and
saved loops), "Serato BeatGrid", "Serato Overview", "Serato Autotags" and
"Serato Analysis". ffmpeg's muxers write the standard text frames and cover art
but silently drop unknown frames like GEOB, so the remux in
`audio_processor._copy_metadata()` strips every cue point the DJ had set. A DJ
who cleans a track they already prepped gets the file back with all of that
work gone, which is the main reason clean versions don't make it into rotation.

This module copies those frames across verbatim. It deliberately never parses
cue semantics: the censoring pipeline is length-preserving, so every timestamp
inside those payloads is still correct and the blobs only need moving, not
rewriting. That also means this picks up Traktor, Mixed In Key and any future
tagging scheme for free, without knowing anything about their formats.

Cross-container exports cannot carry cues -- Serato encodes the same payload
differently per container (raw GEOB in ID3, base64 in a Vorbis comment, a
`----:com.serato.dj:` freeform atom in MP4) -- so those are reported as not
preserved rather than silently mangled.
"""

import os
import sys

# Substrings identifying a tag as DJ performance data rather than normal metadata.
DJ_TAG_MARKERS = (
    "serato",
    "traktor",
    "native-instruments",
    "mixedinkey",
    "mixed in key",
    "rekordbox",
)

# Frames whose value goes stale after processing. A wrong track length is worse
# than an absent one, so this is dropped rather than copied.
SKIP_KEYS = {"tlen"}

_ID3_EXTS = {"mp3", "aiff", "aif", "wav"}
_FLAC_EXTS = {"flac"}
_MP4_EXTS = {"m4a", "mp4"}

TAG_PASSTHROUGH_EXTS = _ID3_EXTS | _FLAC_EXTS | _MP4_EXTS


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower().lstrip(".")


def _container(ext: str) -> str | None:
    """Group extensions into the tag container family they share."""
    if ext in _ID3_EXTS:
        return "id3"
    if ext in _FLAC_EXTS:
        return "flac"
    if ext in _MP4_EXTS:
        return "mp4"
    return None


def _load_id3(path: str, create: bool = False):
    """Open an ID3-carrying container (MP3, AIFF or WAV)."""
    ext = _ext(path)
    if ext == "mp3":
        from mutagen.mp3 import MP3
        f = MP3(path)
    elif ext in ("aiff", "aif"):
        from mutagen.aiff import AIFF
        f = AIFF(path)
    else:
        from mutagen.wave import WAVE
        f = WAVE(path)
    if f.tags is None and create:
        f.add_tags()
    return f


def _tag_keys(path: str) -> list[str]:
    """Every tag key on a file, as strings. Empty list if unreadable."""
    try:
        import mutagen
        f = mutagen.File(path)
        if f is None or f.tags is None:
            return []
        return [str(k) for k in f.tags.keys()]
    except Exception:
        return []


def describe_dj_tags(path: str) -> dict:
    """Report which DJ-software tags a file carries.

    Presence detection only -- we never decode the payloads, which is enough to
    tell the user their cues will survive and costs almost nothing.
    """
    result = {
        "container": _ext(path),
        "tags": [],
        "serato": False,
        "traktor": False,
        "any_dj": False,
    }
    if not path or not os.path.isfile(path):
        return result

    dj = [k for k in _tag_keys(path) if any(m in k.lower() for m in DJ_TAG_MARKERS)]
    result["tags"] = sorted(dj)
    result["serato"] = any("serato" in k.lower() for k in dj)
    result["traktor"] = any(
        "traktor" in k.lower() or "native-instruments" in k.lower() for k in dj
    )
    result["any_dj"] = bool(dj)
    return result


def _copy_id3(source_path: str, output_path: str) -> list[str]:
    src = _load_id3(source_path)
    if src.tags is None:
        return []
    dst = _load_id3(output_path, create=True)

    # ffmpeg already wrote the standard frames; only add what it dropped. Compare
    # lowered because ffmpeg can round-trip TXXX descriptions with other casing.
    existing = {str(k).lower() for k in dst.tags.keys()}
    copied = []
    for frame in src.tags.values():
        key = str(frame.HashKey)
        if key.split(":", 1)[0].lower() in SKIP_KEYS:
            continue
        if key.lower() in existing:
            continue
        dst.tags.add(frame)
        copied.append(key)

    if copied:
        # Match the ID3 version _copy_metadata's ffmpeg call writes (-id3v2_version 3)
        # so the output doesn't end up with mixed v2.3/v2.4 semantics.
        try:
            dst.save(v2_version=3)
        except TypeError:
            dst.save()
    return copied


def _copy_flac(source_path: str, output_path: str) -> list[str]:
    from mutagen.flac import FLAC

    src = FLAC(source_path)
    dst = FLAC(output_path)
    existing = {str(k).lower() for k in dst.keys()}

    copied = []
    for key, values in src.items():
        if str(key).lower() in SKIP_KEYS or str(key).lower() in existing:
            continue
        dst[key] = values
        copied.append(str(key))

    pictures_added = False
    if not dst.pictures and src.pictures:
        for pic in src.pictures:
            dst.add_picture(pic)
        pictures_added = True

    if copied or pictures_added:
        dst.save()
    return copied


def _copy_mp4(source_path: str, output_path: str) -> list[str]:
    from mutagen.mp4 import MP4

    src = MP4(source_path)
    if src.tags is None:
        return []
    dst = MP4(output_path)
    if dst.tags is None:
        dst.add_tags()
    existing = {str(k).lower() for k in dst.tags.keys()}

    copied = []
    for key, value in src.tags.items():
        if str(key).lower() in SKIP_KEYS or str(key).lower() in existing:
            continue
        dst.tags[key] = value
        copied.append(str(key))

    if copied:
        dst.save()
    return copied


def copy_tags(source_path: str | None, output_path: str) -> dict:
    """Copy tag frames ffmpeg dropped from source onto output.

    Purely additive -- existing keys on the output are never overwritten, so a
    failure here can never regress what the ffmpeg remux already achieved. Must
    run *after* `_copy_metadata()`, which finishes with an os.replace() that
    would otherwise discard this write.

    Returns {"preserved": bool, "copied": [...], "dj_tags": [...], "reason": str|None}.
    `reason` is one of None, "no_source", "format_change", "unsupported_container",
    "write_failed".
    """
    result = {"preserved": False, "copied": [], "dj_tags": [], "reason": None}

    if not source_path or not os.path.isfile(source_path):
        result["reason"] = "no_source"
        return result

    src_container = _container(_ext(source_path))
    dst_container = _container(_ext(output_path))

    if src_container is None or dst_container is None:
        result["reason"] = "unsupported_container"
        return result
    if src_container != dst_container:
        # Same payload, different envelope per container. Translating is a known
        # transform but needs per-format verification against real DJ software,
        # so report it instead of writing something that might not load.
        result["reason"] = "format_change"
        return result

    try:
        if src_container == "id3":
            result["copied"] = _copy_id3(source_path, output_path)
        elif src_container == "flac":
            result["copied"] = _copy_flac(source_path, output_path)
        else:
            result["copied"] = _copy_mp4(source_path, output_path)
    except Exception as e:
        print(f"[TagPreserver] Failed to copy tags to {output_path}: {e}", file=sys.stderr)
        result["reason"] = "write_failed"
        return result

    # Verify by re-reading the output rather than trusting the write.
    out_tags = describe_dj_tags(output_path)
    src_tags = describe_dj_tags(source_path)
    result["dj_tags"] = out_tags["tags"]
    result["preserved"] = set(src_tags["tags"]).issubset(set(out_tags["tags"]))

    if src_tags["any_dj"]:
        print(
            f"[TagPreserver] {len(out_tags['tags'])}/{len(src_tags['tags'])} DJ tags "
            f"carried onto {os.path.basename(output_path)}"
            f"{' (INCOMPLETE)' if not result['preserved'] else ''}",
            file=sys.stderr,
        )
    return result
