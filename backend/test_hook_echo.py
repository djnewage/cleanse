"""Tests for hook_echo.infer_hook_echoes — inferred concurrent-ad-lib mutes.

Heavy deps are stubbed in conftest.py. All tests run with vocals_path=None
(no energy gate) except the pure-function energy tests.
"""

import numpy as np

from hook_echo import (
    ECHO_CONF, ENERGY_FRAC_MIN, MAX_INJECTIONS, _slot_has_vocal_energy,
    find_acoustic_echoes, infer_hook_echoes,
)

HOOK = ["just", "me", "and", "my", "bitch"]
# Start offsets of the hook words within one phrase (measured shape).
OFFSETS = [0.0, 0.35, 0.6, 0.85, 1.1]
DUR = 0.3


def _word(text, start, end=None, is_profanity=False, **kw):
    return {
        "word": text, "start": round(start, 3),
        "end": round(end if end is not None else start + DUR, 3),
        "confidence": 0.9, "is_profanity": is_profanity, **kw,
    }


def _hook_instance(t0, complete=True, tokens=None, jitter=0.0):
    """One hook phrase starting at t0. complete=False drops the profanity."""
    tokens = tokens or HOOK
    out = []
    for i, tok in enumerate(tokens):
        if not complete and i == len(HOOK) - 1:
            break
        out.append(_word(
            tok, t0 + OFFSETS[i] + (jitter * i),
            is_profanity=(i == len(HOOK) - 1),
        ))
    return out


def _filler(t0, n=3):
    return [_word(f"la{i}", t0 + i * 0.5) for i in range(n)]


def _song(instances):
    words = []
    for inst in instances:
        words.extend(inst)
    return sorted(words, key=lambda w: w["start"])


class TestInferHookEchoes:
    def test_basic_echo_injected(self):
        words = _song([
            _filler(0),
            _hook_instance(10), _hook_instance(20), _hook_instance(30),
            _hook_instance(40, complete=False),
        ])
        echoes = infer_hook_echoes(words)
        assert len(echoes) == 1
        e = echoes[0]
        assert e["word"] == "bitch"
        assert e["is_profanity"] is True
        assert e["detection_source"] == "hook_echo"
        assert e["confidence"] == ECHO_CONF
        # anchor 'my' at 40.85 + median (bitch.start - my.start) = 0.25
        assert abs(e["start"] - 41.1) < 1e-3
        assert abs(e["end"] - (41.1 + DUR)) < 1e-3

    def test_truncated_prefix_site_matches(self):
        # Echo site has only "just me and" (the measured site-1 shape).
        words = _song([
            _filler(0),
            _hook_instance(10), _hook_instance(20), _hook_instance(30),
            _hook_instance(40, tokens=HOOK[:3], complete=False),
        ])
        echoes = infer_hook_echoes(words)
        assert len(echoes) == 1
        # anchor 'and' at 40.6 + median (bitch.start - and.start) = 0.5
        assert abs(echoes[0]["start"] - 41.1) < 1e-3

    def test_stretched_prefix_word_overlap_allowed(self):
        # The run's own last word blankets the slot (clamped-stretch shape).
        words = _song([
            _filler(0),
            _hook_instance(10), _hook_instance(20), _hook_instance(30),
        ])
        words.append(_word("just", 40.0))
        words.append(_word("me", 40.35))
        words.append(_word("and", 40.6, end=42.6))  # stretched over the slot
        words.sort(key=lambda w: w["start"])
        echoes = infer_hook_echoes(words)
        assert len(echoes) == 1
        assert abs(echoes[0]["start"] - 41.1) < 1e-3

    def test_below_min_completed(self):
        words = _song([
            _hook_instance(10), _hook_instance(20),
            _hook_instance(40, complete=False),
        ])
        assert infer_hook_echoes(words) == []

    def test_dominance_gate(self):
        # 3 profane completions but 2 clean "girl" completions -> 3/5 < 0.8.
        clean = [_hook_instance(t)[:-1] + [_word("girl", t + OFFSETS[4])]
                 for t in (50, 60)]
        words = _song([
            _hook_instance(10), _hook_instance(20), _hook_instance(30),
            *clean,
            _hook_instance(70, complete=False),
        ])
        assert infer_hook_echoes(words) == []

    def test_occupied_slot_skipped(self):
        words = _song([
            _hook_instance(10), _hook_instance(20), _hook_instance(30),
            _hook_instance(40, complete=False),
        ])
        words.append(_word("yeah", 41.05))  # unrelated word in the slot
        words.sort(key=lambda w: w["start"])
        assert infer_hook_echoes(words) == []

    def test_fuzzy_completion_counts_as_completed(self):
        # Occupant "beach" (sim >= 0.6 to "bitch") counts toward dominance,
        # no injection at that site, and the empty site still fires.
        beach = _hook_instance(50)[:-1] + [_word("beach", 50 + OFFSETS[4])]
        words = _song([
            _hook_instance(10), _hook_instance(20), _hook_instance(30),
            beach,
            _hook_instance(60, complete=False),
        ])
        echoes = infer_hook_echoes(words)
        assert len(echoes) == 1
        assert abs(echoes[0]["start"] - 61.1) < 1e-3

    def test_timing_instability_gate(self):
        # Anchor deltas 0.25 / 0.55 / 0.85 -> MAD 0.3 > 0.25: not a locked hook.
        words = _song([
            _hook_instance(10, jitter=0.0),
            _hook_instance(20, jitter=0.3),
            _hook_instance(30, jitter=0.6),
            _hook_instance(70, complete=False),
        ])
        assert infer_hook_echoes(words) == []

    def test_whitelist_safety(self):
        # Flags forced on a word scan_token rejects -> no pattern forms.
        hook = ["down", "in", "the", "deep", "well"]
        instances = []
        for t in (10, 20, 30):
            inst = [_word(tok, t + OFFSETS[i]) for i, tok in enumerate(hook)]
            inst[-1]["is_profanity"] = True
            instances.append(inst)
        site = [_word(tok, 40 + OFFSETS[i]) for i, tok in enumerate(hook[:4])]
        words = _song(instances + [site])
        assert infer_hook_echoes(words) == []

    def test_hook_span_cap(self):
        # Prefix spread over 6s per instance -> instances rejected.
        instances = []
        for t in (10, 30, 50):
            inst = [_word(tok, t + i * 1.5) for i, tok in enumerate(HOOK)]
            inst[-1]["is_profanity"] = True
            instances.append(inst)
        site = [_word(tok, 70 + i * 1.5) for i, tok in enumerate(HOOK[:4])]
        words = _song(instances + [site])
        assert infer_hook_echoes(words) == []

    def test_dedup_near_existing_profanity(self):
        words = _song([
            _hook_instance(10), _hook_instance(20), _hook_instance(30),
            _hook_instance(40, complete=False),
        ])
        # A flagged word 0.5s after the slot center (outside the slot itself,
        # inside DEDUP_WINDOW_S) already mutes this moment.
        words.append(_word("shit", 41.75, is_profanity=True))
        words.sort(key=lambda w: w["start"])
        assert infer_hook_echoes(words) == []

    def test_injection_cap(self):
        completed = [_hook_instance(10 + 10 * i) for i in range(4)]
        sites = [_hook_instance(100 + 10 * i, complete=False)
                 for i in range(MAX_INJECTIONS + 2)]
        words = _song(completed + sites)
        assert len(infer_hook_echoes(words)) == MAX_INJECTIONS

    def test_does_not_mutate_input(self):
        words = _song([
            _hook_instance(10), _hook_instance(20), _hook_instance(30),
            _hook_instance(40, complete=False),
        ])
        snapshot = [dict(w) for w in words]
        infer_hook_echoes(words)
        assert words == snapshot

    def test_no_words_no_crash(self):
        assert infer_hook_echoes([]) == []


class TestSlotEnergy:
    def test_hot_slot_passes(self):
        rms = np.array([0.0] * 10 + [1.0] * 10)
        assert _slot_has_vocal_energy(rms, 0.5, 0.5, 1.0, 0.05) is True

    def test_cold_slot_fails(self):
        rms = np.array([1.0] * 10 + [0.0] * 10)
        assert _slot_has_vocal_energy(rms, 0.5, 0.5, 1.0, 0.05) is False

    def test_fraction_boundary(self):
        # Exactly ENERGY_FRAC_MIN of frames hot -> passes (>=).
        n_hot = int(round(ENERGY_FRAC_MIN * 10))
        rms = np.array([1.0] * n_hot + [0.0] * (10 - n_hot))
        assert _slot_has_vocal_energy(rms, 0.5, 0.0, 0.5, 0.05) is True

    def test_empty_slot_fails(self):
        assert _slot_has_vocal_energy(np.array([1.0]), 0.5, 5.0, 5.5, 0.05) is False


class TestAcousticEchoes:
    SR = 16000

    def _burst(self, dur=0.4):
        """A distinctive chirp burst — the 'ad-lib sample'."""
        t = np.arange(int(dur * self.SR)) / self.SR
        return (0.4 * np.sin(2 * np.pi * (400 + 1500 * t / dur) * t)).astype(np.float32)

    def _song(self, seconds, burst_times, noise=0.01, seed=7):
        rng = np.random.default_rng(seed)
        x = (noise * rng.standard_normal(int(seconds * self.SR))).astype(np.float32)
        b = self._burst()
        for t in burst_times:
            a = int(t * self.SR)
            x[a:a + len(b)] += b
        return x

    def _flagged(self, times):
        return [
            _word("bitch", t, end=t + 0.4, is_profanity=True)
            for t in times
        ]

    def test_uncaught_repeats_found(self):
        # Bursts at 10/20/30/40 are flagged; bursts at 15 and 25 are the
        # ad-libs no ASR pass emitted. The correlator must find exactly those.
        audio = self._song(55, [10, 20, 30, 40, 15, 25])
        words = self._flagged([10, 20, 30, 40]) + [_word("la", 5)]
        echoes = find_acoustic_echoes(sorted(words, key=lambda w: w["start"]), audio)
        found = sorted(round(e["start"], 1) for e in echoes)
        assert len(found) == 2, echoes
        assert abs(found[0] - 15.0) < 0.15 and abs(found[1] - 25.0) < 0.15
        assert all(e["detection_source"] == "acoustic_echo" for e in echoes)
        assert all(e["is_profanity"] for e in echoes)

    def test_no_repeats_no_injections(self):
        # Flagged instances exist but nothing else matches -> nothing injected.
        audio = self._song(55, [10, 20, 30, 40])
        words = self._flagged([10, 20, 30, 40])
        assert find_acoustic_echoes(words, audio) == []

    def test_below_min_instances(self):
        audio = self._song(40, [10, 20, 15])
        words = self._flagged([10, 20])
        assert find_acoustic_echoes(words, audio) == []

    def test_dedup_against_flagged_and_injected(self):
        # The burst at 15 is already flagged (e.g. by rescan) -> no double.
        audio = self._song(55, [10, 20, 30, 40, 15])
        words = self._flagged([10, 20, 30, 40, 15])
        assert find_acoustic_echoes(words, audio) == []

    def test_dissimilar_instances_fail_closed(self):
        # "Instances" that are just unrelated noise: self-calibration finds
        # the template can't even match its siblings -> no injections anywhere.
        rng = np.random.default_rng(3)
        audio = (0.2 * rng.standard_normal(40 * self.SR)).astype(np.float32)
        words = self._flagged([10, 15, 20, 25])
        echoes = find_acoustic_echoes(words, audio)
        assert echoes == []


class TestNormalizeInterplay:
    def test_stretched_word_trimmed_to_injection(self):
        # Pins the not-in-SYNTHETIC_SOURCES decision: the real-priority
        # profane injection wins the overlap and the stretched word yields.
        from lyrics_corrector import normalize_word_timeline
        words = [
            _word("and", 40.6, end=42.6),  # stretched over the slot
            {"word": "bitch", "start": 41.1, "end": 41.4, "confidence": ECHO_CONF,
             "is_profanity": True, "detection_source": "hook_echo"},
            _word("later", 43.0),
        ]
        out = normalize_word_timeline(sorted(words, key=lambda w: w["start"]), audio_duration=60)
        echo = [w for w in out if w.get("detection_source") == "hook_echo"][0]
        assert (echo["start"], echo["end"]) == (41.1, 41.4)
        and_w = [w for w in out if w["word"] == "and"][0]
        assert and_w["end"] <= 41.1 + 1e-6
