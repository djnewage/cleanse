#!/usr/bin/env python3
"""Tests for choose_language() — the language-detection decision logic."""

import sys
from transcribe import _latin_ratio, choose_language

ENGLISH_LYRICS = """
I just lost my moms, why I need to feel somethin'
Stealing, both my arms went from Marcy to Hollywood
And back again, back again
"""

HANGUL_LYRICS = """
나는 오늘도 걷는다
빛나는 별들 아래서
너를 생각하며 노래해
"""


def run_tests() -> bool:
    cases = [
        {
            "name": "confident en accepted as-is",
            "kwargs": dict(detected="en", probability=0.95,
                           all_probs=[("en", 0.95), ("es", 0.02)]),
            "expect": {"language": "en", "source": "detector", "low_confidence": False},
        },
        {
            "name": "confident es passthrough (genuine Spanish track)",
            "kwargs": dict(detected="es", probability=0.88,
                           all_probs=[("es", 0.88), ("en", 0.05)]),
            "expect": {"language": "es", "source": "detector", "low_confidence": False},
        },
        {
            "name": "km + Latin lyrics -> overridden to best Latin candidate",
            "kwargs": dict(detected="km", probability=0.72,
                           all_probs=[("km", 0.72), ("en", 0.11), ("es", 0.03)],
                           lyrics_text=ENGLISH_LYRICS),
            "expect": {"language": "en", "source": "lyrics_script_override",
                       "low_confidence": True},
        },
        {
            "name": "km + Latin lyrics + no Latin candidates -> en fallback",
            "kwargs": dict(detected="km", probability=0.72,
                           all_probs=[("km", 0.72), ("ko", 0.1)],
                           lyrics_text=ENGLISH_LYRICS),
            "expect": {"language": "en", "source": "lyrics_script_override",
                       "low_confidence": True},
        },
        {
            "name": "confident ko + Hangul lyrics passthrough (K-pop)",
            "kwargs": dict(detected="ko", probability=0.9,
                           all_probs=[("ko", 0.9), ("en", 0.02)],
                           lyrics_text=HANGUL_LYRICS),
            "expect": {"language": "ko", "source": "detector", "low_confidence": False},
        },
        {
            "name": "low confidence, es outranks en -> es",
            "kwargs": dict(detected="km", probability=0.31,
                           all_probs=[("km", 0.31), ("es", 0.25), ("en", 0.15)]),
            "expect": {"language": "es", "source": "low_confidence_fallback",
                       "low_confidence": True},
        },
        {
            "name": "low confidence, en outranks es -> en",
            "kwargs": dict(detected="km", probability=0.31,
                           all_probs=[("km", 0.31), ("en", 0.24), ("es", 0.05)]),
            "expect": {"language": "en", "source": "low_confidence_fallback",
                       "low_confidence": True},
        },
        {
            "name": "low confidence, empty all_probs -> en default",
            "kwargs": dict(detected="km", probability=0.2, all_probs=[]),
            "expect": {"language": "en", "source": "low_confidence_fallback",
                       "low_confidence": True},
        },
        {
            "name": "low confidence, all_probs None -> en default",
            "kwargs": dict(detected="km", probability=0.2, all_probs=None),
            "expect": {"language": "en", "source": "low_confidence_fallback",
                       "low_confidence": True},
        },
        {
            "name": "low-confidence en accepted via fallback (not detector)",
            "kwargs": dict(detected="en", probability=0.45,
                           all_probs=[("en", 0.45), ("es", 0.1)]),
            "expect": {"language": "en", "source": "low_confidence_fallback",
                       "low_confidence": True},
        },
        {
            "name": "accented Spanish lyrics still count as Latin script",
            "kwargs": dict(detected="th", probability=0.7,
                           all_probs=[("th", 0.7), ("es", 0.2)],
                           lyrics_text="Corazón partío, aún me quedan más días"),
            "expect": {"language": "es", "source": "lyrics_script_override",
                       "low_confidence": True},
        },
    ]

    passed = failed = 0
    for case in cases:
        result = choose_language(**case["kwargs"])
        ok = all(result[k] == v for k, v in case["expect"].items())
        print(f"{'✓' if ok else '✗'} {case['name']}")
        if ok:
            passed += 1
        else:
            failed += 1
            print(f"    expected {case['expect']}")
            print(f"    got      {result}")

    # _latin_ratio sanity
    ratio_cases = [
        ("hello world", 1.0, lambda r: r == 1.0),
        ("", 0.0, lambda r: r == 0.0),
        ("123 !!!", 0.0, lambda r: r == 0.0),
        (HANGUL_LYRICS, 0.0, lambda r: r < 0.1),
        ("Corazón", 1.0, lambda r: r == 1.0),
    ]
    for text, label, check in ratio_cases:
        r = _latin_ratio(text)
        ok = check(r)
        print(f"{'✓' if ok else '✗'} _latin_ratio({text[:20]!r}...) = {r:.2f}")
        passed += ok
        failed += not ok

    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
