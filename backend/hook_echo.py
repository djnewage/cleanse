"""Infer profane hook completions that Whisper structurally cannot hear.

Background ad-libs sung CONCURRENTLY with the lead vocal never appear in any
ASR pass — Whisper decodes one voice per timespan (measured: the vocals stem
at 62.5-72.5s of a Biggie mashup decodes only the lead "but you know you love
it", while the background "just me and my bitch" repeats appear at NO
confidence). They also leave no energy gap for rescan_vocal_gaps: the
envelope stays hot under the lead.

But a hook repeats. When "just me and my bitch" is transcribed complete and
flagged N times, and the same prefix appears elsewhere with the completion
missing over hot vocal energy, the completion was sung by the background
voice. This module finds those sites and injects the missing profane word
with timing derived from the pattern's own instances.

Every gate below exists to keep the false-positive surface tiny — injecting
a mute over clean audio is the failure mode this must not have:
  * the pattern needs >= MIN_COMPLETED completed instances,
  * >= DOMINANCE_MIN of full-prefix sites must complete with the profanity
    (blocks "...my girl" / "...my bitch" alternating hooks),
  * the instance timing must be rhythmically stable (MAD gate),
  * the slot must be empty of transcription (except the matched prefix run
    itself — a stretched prefix word blanketing the slot is the signature of
    the exact bug being fixed),
  * and when a vocals stem is available, the slot must carry vocal energy.
"""

import re
import sys
from collections import Counter, defaultdict
from statistics import median

import numpy as np

from lyrics_corrector import _compute_word_similarity
from profanity_detector import scan_token

K_PREFIX = 4              # preceding words captured per flagged instance
MIN_PREFIX_MATCH = 3      # contiguous anchored tokens required at an echo site
MIN_COMPLETED = 3         # completed instances required to trust a pattern
DOMINANCE_MIN = 0.8       # fraction of full-prefix sites completing profane
MAX_HOOK_SPAN_S = 4.0     # prefix[0].start -> prof.start; a hook is one phrase
MAX_DELTA_MAD_S = 0.25    # timing-stability gate on the anchor delta
SLOT_MARGIN_S = 0.1       # occupancy-check margin around the slot
COMPLETION_SIM_MIN = 0.6  # occupant counts as the completion at this sim
DEDUP_WINDOW_S = 0.75     # matches find_plain_lyrics_profanity cover window
ENERGY_FRAC_MIN = 0.6     # fraction of slot frames that must be vocal-hot
ECHO_CONF = 0.5           # matches the lyrics-injection confidence convention
MAX_INJECTIONS = 10


def _norm(text: str) -> str:
    return re.sub(r"[^\w]", "", text).lower()


def _slot_has_vocal_energy(
    rms: np.ndarray, threshold: float, start_s: float, end_s: float, frame_s: float
) -> bool:
    """True when >= ENERGY_FRAC_MIN of the slot's frames are vocal-hot."""
    a = max(0, int(start_s / frame_s))
    b = min(len(rms), int(np.ceil(end_s / frame_s)))
    if b <= a:
        return False
    seg = rms[a:b]
    return float(np.mean(seg >= threshold)) >= ENERGY_FRAC_MIN


def _collect_patterns(words: list[dict], language: str | None) -> dict:
    """Group flagged words by (prefix tuple, profane text) with timing stats.

    NOTE: the prefix is list-order-contiguous; an interleaved rescan ad-lib
    word fragments that instance's prefix tuple. Tolerated, not solved —
    MIN_COMPLETED against a hook's many repeats absorbs the loss.
    """
    patterns: dict = defaultdict(lambda: {"deltas": [], "durs": [], "texts": Counter()})
    for i, w in enumerate(words):
        if not w.get("is_profanity") or i < K_PREFIX:
            continue
        # Whitelist safety: only build patterns from words the tiered detector
        # itself matches, whatever upstream layer set the flag.
        if scan_token(w["word"], language) is None:
            continue
        prefix_words = words[i - K_PREFIX:i]
        prefix = tuple(_norm(pw["word"]) for pw in prefix_words)
        if any(not tok for tok in prefix):
            continue
        span = w["start"] - prefix_words[0]["start"]
        if span <= 0 or span > MAX_HOOK_SPAN_S:
            continue
        rec = patterns[(prefix, _norm(w["word"]))]
        rec["deltas"].append([w["start"] - pw["start"] for pw in prefix_words])
        rec["durs"].append(w["end"] - w["start"])
        rec["texts"][w["word"].strip()] += 1

    kept = {}
    for key, rec in patterns.items():
        if len(rec["durs"]) < MIN_COMPLETED:
            continue
        deltas = rec["deltas"]
        med_delta = [median(d[r] for d in deltas) for r in range(K_PREFIX)]
        mad = [
            median(abs(d[r] - med_delta[r]) for d in deltas)
            for r in range(K_PREFIX)
        ]
        kept[key] = {
            "med_delta": med_delta,
            "mad": mad,
            "med_dur": min(max(median(rec["durs"]), 0.15), 1.0),
            "display": rec["texts"].most_common(1)[0][0],
            "instances": len(rec["durs"]),
        }
    return kept


def infer_hook_echoes(
    words: list[dict],
    vocals_path: str | None = None,
    language: str | None = None,
) -> list[dict]:
    """Return NEW injected word dicts only (caller appends + re-sorts).

    ``words`` must be sorted by start. When ``vocals_path`` is given, echo
    slots additionally require vocal energy in the stem.
    """
    if len(words) <= K_PREFIX:
        return []
    patterns = _collect_patterns(words, language)
    if not patterns:
        return []

    envelope = None
    if vocals_path:
        from transcribe import _RESCAN_FRAME_S, _decode_audio_ffmpeg, compute_vocal_rms_envelope
        try:
            audio = _decode_audio_ffmpeg(vocals_path, sampling_rate=16000)
            envelope = compute_vocal_rms_envelope(words, audio)
        except Exception as ex:
            print(f"[HookEcho] Stem envelope unavailable: {ex}", file=sys.stderr)
        if envelope is None:
            # A stem was promised but unusable — fail closed, don't inject
            # un-corroborated mutes.
            return []

    norm_words = [_norm(w["word"]) for w in words]
    injected: list[dict] = []

    for (prefix, _prof_norm), pat in patterns.items():
        # Pass 1 over sites: classify to compute dominance before injecting.
        sites = []  # (anchor_idx, m, run_indices)
        a = 0
        while a <= len(words) - MIN_PREFIX_MATCH:
            m = 0
            while (
                m < K_PREFIX
                and a + m < len(words)
                and norm_words[a + m] == prefix[m]
            ):
                m += 1
            if m < MIN_PREFIX_MATCH or (
                words[a + m - 1]["start"] - words[a]["start"] > MAX_HOOK_SPAN_S
            ):
                a += max(m, 1)
                continue
            sites.append((a + m - 1, m, set(range(a, a + m))))
            a += m

        completed_full = occupied_full = 0
        candidates = []  # (anchor_idx, m, run_indices, exp_start, exp_end)
        for anchor_idx, m, run in sites:
            exp_start = words[anchor_idx]["start"] + pat["med_delta"][m - 1]
            exp_end = exp_start + pat["med_dur"]
            occupants = [
                w for j, w in enumerate(words)
                if j not in run
                and w["start"] < exp_end + SLOT_MARGIN_S
                and w["end"] > exp_start - SLOT_MARGIN_S
            ]
            if occupants:
                is_completed = any(
                    _compute_word_similarity(o["word"], pat["display"])
                    >= COMPLETION_SIM_MIN
                    for o in occupants
                )
                if m == K_PREFIX:
                    completed_full += is_completed
                    occupied_full += not is_completed
            else:
                candidates.append((anchor_idx, m, exp_start, exp_end))

        if completed_full < MIN_COMPLETED:
            continue
        if completed_full / (completed_full + occupied_full) < DOMINANCE_MIN:
            continue

        for anchor_idx, m, exp_start, exp_end in candidates:
            if pat["mad"][m - 1] > MAX_DELTA_MAD_S:
                continue
            center = (exp_start + exp_end) / 2
            near_flagged = any(
                w.get("is_profanity")
                and abs((w["start"] + w["end"]) / 2 - center) <= DEDUP_WINDOW_S
                for w in words
            ) or any(
                abs((e["start"] + e["end"]) / 2 - center) <= DEDUP_WINDOW_S
                for e in injected
            )
            if near_flagged:
                continue
            if envelope is not None:
                rms, _covered, threshold = envelope
                from transcribe import _RESCAN_FRAME_S
                if not _slot_has_vocal_energy(
                    rms, threshold, exp_start, exp_end, _RESCAN_FRAME_S
                ):
                    continue
            if len(injected) >= MAX_INJECTIONS:
                break
            echo = {
                "word": pat["display"],
                "start": round(exp_start, 3),
                "end": round(exp_end, 3),
                "confidence": ECHO_CONF,
                "is_profanity": True,
                "detection_source": "hook_echo",
            }
            injected.append(echo)
            print(
                f"[HookEcho] Injected '{echo['word']}' at "
                f"{echo['start']:.2f}-{echo['end']:.2f}s: hook "
                f"'{' '.join(prefix)} {pat['display']}' completed "
                f"{pat['instances']}x elsewhere, prefix here ends unfinished",
                file=sys.stderr,
            )

    return injected
