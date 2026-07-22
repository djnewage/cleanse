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

# --- Acoustic echo matching (template correlation on the vocals stem) -------
MIN_TEMPLATE_INSTANCES = 4   # flagged repeats required before matching
MAX_TEMPLATES = 12           # time-partitioned instances used as templates;
                             # per-template validation discards useless ones,
                             # so breadth beats curation (a lone background-
                             # voice instance must make the bank to find its
                             # own ghosts)
SEARCH_PAD_S = 8.0           # search this far beyond the instance cluster
SCORE_FLOOR = 0.35           # absolute correlation floor
CALIBRATION_FRAC = 0.75      # accept >= this fraction of median known score
ACOUSTIC_DEDUP_S = 0.45      # min spacing from flagged words AND other peaks
MAX_ACOUSTIC_INJECTIONS = 32  # per-group ceiling; real cap is 2x confirmed count
_SPEC_N_FFT = 512            # 32ms @ 16kHz
_SPEC_HOP = 160              # 10ms

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


def _log_spectrogram(x: np.ndarray) -> np.ndarray:
    """Log-magnitude STFT, frames x bins (10ms hop, 32ms window @ 16kHz)."""
    n = 1 + (len(x) - _SPEC_N_FFT) // _SPEC_HOP
    if n <= 0:
        return np.zeros((0, _SPEC_N_FFT // 2 + 1))
    idx = np.arange(_SPEC_N_FFT)[None, :] + _SPEC_HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(_SPEC_N_FFT)
    return np.log1p(np.abs(np.fft.rfft(frames, axis=1)))


def _template_scores(
    template_spec: np.ndarray, search_spec: np.ndarray
) -> np.ndarray:
    """Normalized cross-correlation of the template over every offset.

    Vectorized: with the template z-normalized (mean 0), the per-offset score
    reduces to corr[i] / (M * window_std[i]) where corr is a plain sliding
    dot-product and window stats come from cumulative sums.
    """
    T = len(template_spec)
    n = len(search_spec) - T
    if n <= 0 or T == 0:
        return np.zeros(0)
    tpl = (template_spec - template_spec.mean()) / (template_spec.std() + 1e-9)
    M = tpl.size

    corr = np.zeros(n)
    for j in range(T):
        corr += search_spec[j:j + n] @ tpl[j]

    # Sliding window mean/std over the T-row windows via cumulative sums.
    row_sum = search_spec.sum(axis=1)
    row_sumsq = (search_spec ** 2).sum(axis=1)
    cs = np.concatenate([[0.0], np.cumsum(row_sum)])
    cs2 = np.concatenate([[0.0], np.cumsum(row_sumsq)])
    win_sum = cs[T:T + n] - cs[:n]
    win_sumsq = cs2[T:T + n] - cs2[:n]
    win_var = np.maximum(win_sumsq / M - (win_sum / M) ** 2, 0.0)
    return corr / (M * np.sqrt(win_var) + 1e-9)


def find_acoustic_echoes(
    words: list[dict],
    vocals_audio: np.ndarray,
    sample_rate: int = 16000,
    already_injected: list[dict] | None = None,
    language: str | None = None,
) -> list[dict]:
    """Find repeats of a flagged ad-lib by ACOUSTIC similarity, not transcript.

    A DJ-edit ad-lib bed is usually the same vocal loop: instances Whisper
    never emits (sung under the lead, zero transcript evidence) still
    correlate spectrally with the instances it did catch. For each profane
    word flagged >= MIN_TEMPLATE_INSTANCES times by ASR-derived sources,
    correlate its strongest instances over the cluster's span and inject
    matches at peaks. The accept threshold is self-calibrated per song from
    the correlation scores AT the known instances — a template that doesn't
    even match its own siblings never fires (measured on the reported mashup:
    known instances score 0.31-0.55 vs a <0.3 noise floor, and the new peaks
    at 64.0s / 71.6s / 76.7s are exactly the ad-libs every ASR pass missed).
    """
    hop_s = _SPEC_HOP / sample_rate
    inferred = list(already_injected or [])

    # Group ASR-confirmed flagged instances by normalized text.
    groups: dict = defaultdict(list)
    for w in words:
        if not w.get("is_profanity"):
            continue
        if w.get("detection_source") in ("hook_echo", "acoustic_echo", "lyrics", "lyrics_gap"):
            continue
        if scan_token(w["word"], language) is None:
            continue
        if not 0.15 <= w["end"] - w["start"] <= 1.0:
            continue
        groups[_norm(w["word"])].append(w)

    injected: list[dict] = []
    for _text, instances in groups.items():
        if len(instances) < MIN_TEMPLATE_INSTANCES:
            continue
        instances.sort(key=lambda w: w["start"])
        span_a = max(0.0, instances[0]["start"] - SEARCH_PAD_S)
        span_b = min(
            len(vocals_audio) / sample_rate,
            instances[-1]["end"] + SEARCH_PAD_S,
        )
        search = vocals_audio[int(span_a * sample_rate):int(span_b * sample_rate)]
        search_spec = _log_spectrogram(search)
        if not len(search_spec):
            continue

        # Template selection: DIVERSITY over confidence. The same profane word
        # often exists in two takes — the lead's and the background loop's —
        # and top-confidence picks only lead instances, which score the faint
        # background ghosts under the floor (measured: background instances at
        # 76.7/77.4s matched 0.43-0.47 against a background template but were
        # invisible to a lead-only bank). Partition the instances across time
        # and take the strongest from each partition; beds cluster temporally,
        # so temporal spread captures take diversity.
        # Leave >= 2 non-template instances for the self-calibration below.
        n_templates = min(MAX_TEMPLATES, len(instances) - 2)
        templates = []
        if n_templates > 0:
            bounds = np.linspace(0, len(instances), n_templates + 1).astype(int)
            for k in range(n_templates):
                part = instances[bounds[k]:bounds[k + 1]]
                if part:
                    templates.append(
                        max(part, key=lambda w: w.get("confidence", 0))
                    )

        # Per-template validation + calibration. Each template must prove it
        # DISCRIMINATES: its median score at sibling instances must clear both
        # the absolute floor and the template's own 95th-percentile background
        # level (a promiscuous template that lights up everywhere calibrates
        # itself out; a lead-voice template simply won't fire on background
        # ghosts while a background template will). Each surviving template
        # fires against its own threshold — combining RAW scores across
        # templates lets one bad template poison the bank.
        qual = None  # max over templates of score/threshold ratio
        for t in templates:
            a = int(t["start"] * sample_rate)
            b = int(t["end"] * sample_rate)
            spec = _log_spectrogram(vocals_audio[a:b])
            s = _template_scores(spec, search_spec)
            if not len(s):
                continue
            sib_scores = []
            for inst in instances:
                if abs(inst["start"] - t["start"]) < 0.2:
                    continue
                i = int((inst["start"] - span_a) / hop_s)
                lo, hi = max(0, i - 5), min(len(s), i + 6)
                if lo < hi:
                    sib_scores.append(float(np.max(s[lo:hi])))
            if len(sib_scores) < 2:
                continue
            sib_med = float(median(sib_scores))
            if sib_med < max(SCORE_FLOOR, float(np.percentile(s, 95))):
                continue  # non-discriminative template
            threshold = max(SCORE_FLOOR, CALIBRATION_FRAC * sib_med)
            ratio = s / threshold
            if qual is None:
                qual = np.full(len(search_spec), -np.inf)
            n = min(len(qual), len(ratio))
            qual[:n] = np.maximum(qual[:n], ratio[:n])
        if qual is None:
            continue

        med_dur = min(max(median(w["end"] - w["start"] for w in instances), 0.15), 1.0)
        display = Counter(w["word"].strip() for w in instances).most_common(1)[0][0]

        flagged_times = [
            (w["start"] + w["end"]) / 2 for w in words if w.get("is_profanity")
        ] + [(e["start"] + e["end"]) / 2 for e in inferred]

        # Greedy peak-pick, strongest first. The cap scales with how often the
        # ad-lib is CONFIRMED: a hook looped 21 times can echo well beyond a
        # flat dozen (measured: a flat cap of 12 truncated real 0.35-0.39
        # matches at 76.7/77.4/83.7s while accepting 0.39+ ones).
        group_cap = min(MAX_ACOUSTIC_INJECTIONS, 2 * len(instances))
        group_injected = 0
        for i in np.argsort(qual)[::-1]:
            if qual[i] < 1.0:
                break
            if group_injected >= group_cap:
                break
            t = span_a + i * hop_s
            center = t + med_dur / 2
            if any(abs(center - ft) <= ACOUSTIC_DEDUP_S for ft in flagged_times):
                continue
            flagged_times.append(center)
            echo = {
                "word": display,
                "start": round(t, 3),
                "end": round(t + med_dur, 3),
                "confidence": ECHO_CONF,
                "is_profanity": True,
                "detection_source": "acoustic_echo",
            }
            injected.append(echo)
            inferred.append(echo)
            group_injected += 1
            print(
                f"[HookEcho] Acoustic match '{display}' at {t:.2f}-{t + med_dur:.2f}s "
                f"({qual[i]:.2f}x its template's calibrated threshold, "
                f"{len(instances)} confirmed instances)",
                file=sys.stderr,
            )
    injected.sort(key=lambda w: w["start"])
    return injected


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

    envelope = None
    audio = None
    if vocals_path:
        from transcribe import _decode_audio_ffmpeg, compute_vocal_rms_envelope
        try:
            audio = _decode_audio_ffmpeg(vocals_path, sampling_rate=16000)
            envelope = compute_vocal_rms_envelope(words, audio)
        except Exception as ex:
            print(f"[HookEcho] Stem envelope unavailable: {ex}", file=sys.stderr)
        if envelope is None:
            # A stem was promised but unusable — fail closed, don't inject
            # un-corroborated mutes.
            return []

    patterns = _collect_patterns(words, language)
    if not patterns:
        # No prefix patterns — the acoustic layer may still apply.
        if audio is None:
            return []
        return find_acoustic_echoes(words, audio, language=language)

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

    # Acoustic pass: catches instances with ZERO transcript evidence (sung
    # fully under the lead), which no prefix run can ever reach.
    if audio is not None:
        injected += find_acoustic_echoes(
            words, audio, already_injected=injected, language=language
        )

    return injected
