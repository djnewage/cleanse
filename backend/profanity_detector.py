"""Profanity detection using better-profanity library."""

import re
import unicodedata
from pathlib import Path

from rapidfuzz import fuzz
from better_profanity import profanity

# Load the default word list (916 words)
profanity.load_censor_words()

# Load custom words for music/rap context
custom_words_file = Path(__file__).parent / "custom_profanity.txt"
if custom_words_file.exists():
    with open(custom_words_file, 'r', encoding='utf-8') as f:
        custom_words = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        profanity.add_censor_words(custom_words)

# Load Spanish profanity words
custom_words_es_file = Path(__file__).parent / "custom_profanity_es.txt"
if custom_words_es_file.exists():
    with open(custom_words_es_file, 'r', encoding='utf-8') as f:
        custom_words_es = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        profanity.add_censor_words(custom_words_es)


def _normalize_word(word: str) -> list[str]:
    """
    Generate normalized variations of a word for profanity detection.

    Returns list of variations to check, ordered from most to least specific.
    """
    variations = set()

    # Original word
    variations.add(word)
    variations.add(word.lower())

    # Strip trailing punctuation but keep internal apostrophes
    # Handles: "fuck!", "shit.", "damn?"
    no_trailing_punct = re.sub(r'[^\w\']$', '', word)
    if no_trailing_punct != word:
        variations.add(no_trailing_punct)
        variations.add(no_trailing_punct.lower())

    # Strip ALL punctuation including apostrophes
    # Handles: "fuckin'", "f*ck", "sh1t!"
    no_punct = re.sub(r'[^\w]', '', word)
    if no_punct != word:
        variations.add(no_punct)
        variations.add(no_punct.lower())

    # Strip only trailing apostrophes (common in contractions)
    # Handles: "fuckin'", "lovin'"
    no_trailing_apos = word.rstrip("'")
    if no_trailing_apos != word:
        variations.add(no_trailing_apos)
        variations.add(no_trailing_apos.lower())

    # Add accent-stripped versions of all variations (e.g. "cabrón" -> "cabron")
    accent_stripped = set()
    for v in variations:
        stripped = unicodedata.normalize('NFD', v)
        stripped = ''.join(c for c in stripped if unicodedata.category(c) != 'Mn')
        if stripped != v:
            accent_stripped.add(stripped)
    variations.update(accent_stripped)

    # Remove empty strings
    return [v for v in variations if v]


# Compound profanity: adjacent tokens that form profanity together.
# Whisper often splits these into separate words (e.g., "mother" + "fucker").
# Both halves are flagged so the full compound is censored in audio.
COMPOUND_PROFANITY = {
    ("mother", "fucker"), ("mother", "fuckers"), ("mother", "fuckin"),
    ("mother", "fucking"), ("mother", "fucka"), ("mother", "fuckas"),
    ("bull", "shit"), ("horse", "shit"), ("bat", "shit"), ("dip", "shit"),
    ("god", "damn"), ("god", "dammit"), ("god", "damit"),
    ("jack", "ass"), ("dumb", "ass"), ("bad", "ass"),
    ("kick", "ass"), ("smart", "ass"), ("fat", "ass"),
    ("cock", "sucker"), ("cock", "suckers"), ("cock", "sucking"),
    ("dick", "head"), ("dick", "heads"),
}

# Words that better-profanity falsely matches as profanity.
# These are checked post-detection to override false positives.
WHITELIST = {
    "dame",    # Spanish for "give me", falsely matches "damn"
    "damo",    # Spanish slang for "we give" (damos), falsely matched
    "woody",   # Name / Toy Story reference, falsely matches substring
    "dummy",   # Not profanity, falsely matched
    "god",     # Common in songs ("oh my god", "thank god")
    "lord",    # Religious/exclamation, not profanity
    "hell",    # Common emphasis ("hell yeah", "what the hell")
    "fat",     # Descriptor, not profanity
    "slave",   # Historical/political context, not profanity
    "slaves",  # Plural form
    "panty",   # Clothing reference
    "opium",   # Proper noun (record label) and common drug reference
}

COMPOUND_PROFANITY_ES = {
    ("hijo", "puta"), ("hija", "puta"),
    ("puta", "madre"), ("puto", "madre"),
    ("come", "mierda"),
    ("mama", "guevo"), ("mama", "gueva"),
    ("mama", "vicho"), ("mama", "bicho"),
    ("lame", "culo"),
    ("chupa", "pinga"), ("chupa", "pija"), ("chupa", "pollas"),
    ("cara", "verga"), ("care", "monda"), ("care", "chimba"),
    ("concha", "madre"), ("conche", "madre"),
}

# Filler words allowed between compound halves: "hijo DE puta", "cara DE verga".
# The filler is flagged too so the resulting mute is contiguous.
COMPOUND_GAP_WORDS = {"de", "of", "a", "la", "tu"}


# ---------------------------------------------------------------------------
# Fuzzy + phonetic recall layer (stylized spellings + ASR soft-substitutes).
#
# The EXACT tier (better-profanity + custom lists) already covers most stylized
# spellings (shyt, biatch, azz, fck...). These extra tiers chase the long tail,
# at real false-positive risk: metaphone drops vowels, so a bare key match
# collides with everyday words (shot/sheet->shit, beach/batch->bitch,
# fake->fuck, can't->cunt). So phonetic requires metaphone-equality AND a
# secondary edit-distance guard, which rejects those real words (they differ by
# enough edits) while keeping near-identical stylings. Thresholds are tuned by
# the negatives table in test_profanity_detector.py — that table is the spec.
# ---------------------------------------------------------------------------

# Small, high-value root set. Fuzzy against the full 916-word list would be pure
# noise; these are the roots that actually get misheard/transposed by ASR.
_STYLE_TARGETS: tuple[str, ...] = (
    "fuck", "fucker", "fuckers", "fucking", "fuckin", "motherfucker", "motherfucking",
    "shit", "bullshit", "bitch", "bitches",
    "nigga", "niggas", "nigger", "niggers",
    "cunt", "pussy", "whore", "faggot", "asshole",
)
_FUZZY_MIN = 90          # fuzzy-tier ratio floor (test-table tuned)
_STYLE_MIN_LEN = 4       # never approximate-match very short tokens


def _deelongate(norm: str) -> set[str]:
    """Collapse runs of a repeated char (>=3) to 1 and to 2, e.g.
    'biiitch'->{'bitch','biitch'}, 'pusssy'->{'pusy','pussy'}. Catches elongated
    stylings ('fuuuck', 'shiii') with near-zero FP risk — real words almost never
    have 3+ repeated letters. The collapsed forms are checked by the EXACT list."""
    out = {
        re.sub(r"(.)\1+", r"\1", norm),          # any run (>=2) -> 1  (fuuck->fuck)
        re.sub(r"(.)\1{2,}", r"\1", norm),       # run (>=3)  -> 1     (niggaaa->nigga)
        re.sub(r"(.)\1{2,}", r"\1\1", norm),     # run (>=3)  -> 2     (pusssy->pussy)
    }
    return {v for v in out if v and v != norm}


def _style_match(token: str) -> dict | None:
    """Approximate profanity match (de-elongation + fuzzy) against the stylized
    roots. Returns {"matched", "match_type"} or None. Additive recall only — the
    plain exact tier is handled by the caller. Whitelist-protected."""
    norm = re.sub(r"[^\w]", "", token).lower()
    if len(norm) < _STYLE_MIN_LEN or norm in WHITELIST:
        return None

    # De-elongation: collapse repeated chars, then check the EXACT list.
    for collapsed in _deelongate(norm):
        if collapsed not in WHITELIST and profanity.contains_profanity(collapsed):
            return {"matched": collapsed, "match_type": "deelongate"}

    # Fuzzy: high-ratio match to a root (catches transpositions/substitutions).
    # Threshold set by the negatives table so shirt/count/glass stay clean.
    best_tgt, best = None, 0.0
    for tgt in _STYLE_TARGETS:
        r = fuzz.ratio(norm, tgt)
        if r > best:
            best, best_tgt = r, tgt
    if best >= _FUZZY_MIN:
        return {"matched": best_tgt, "match_type": "fuzzy"}
    return None


def scan_token(token: str, language: str | None = None) -> dict | None:
    """Tiered profanity match for a single token: exact -> de-elongation -> fuzzy.
    Returns a hit dict ({"matched", "match_type"}) or None. Whitelisted tokens
    never match. Used for both ASR words and lyric tokens."""
    variations = _normalize_word(token)
    if any(v.lower() in WHITELIST for v in variations):
        return None
    if any(profanity.contains_profanity(v) for v in variations):
        return {"matched": token, "match_type": "exact"}
    return _style_match(token)


def flag_profanity(words: list[dict], language: str | None = None) -> list[dict]:
    """
    Take a list of transcribed words and add an `is_profanity` flag to each.

    Enhanced version that checks multiple normalized variations of each word
    to catch contractions, punctuation, and common variations. Also detects
    compound profanity split across adjacent tokens (e.g., "mother" + "fucker").

    Args:
        words: List of {"word": str, "start": float, "end": float, "confidence": float}
        language: Detected language code (e.g. "es" for Spanish). Used to
                  include language-specific compound profanity patterns.

    Returns:
        Same list with added "is_profanity": bool field
    """
    flagged = []
    for w in words:
        word_text = w["word"]

        # Generate normalized variations and check if any are profane
        variations = _normalize_word(word_text)
        is_profane = any(profanity.contains_profanity(variant) for variant in variations)

        # Override false positives from whitelist
        if is_profane and any(v.lower() in WHITELIST for v in variations):
            is_profane = False

        # Additive recall: stylized spellings / ASR soft-substitutes the exact
        # tier missed (e.g. "phuck", novel spellings). Gated to avoid FPs.
        if not is_profane and _style_match(word_text) is not None:
            is_profane = True

        flagged.append({**w, "is_profanity": is_profane})

    # Second pass: check adjacent word pairs for compound profanity
    compounds = COMPOUND_PROFANITY
    if language == "es":
        compounds = COMPOUND_PROFANITY | COMPOUND_PROFANITY_ES
    for i in range(len(flagged) - 1):
        w1 = re.sub(r'[^\w]', '', flagged[i]["word"]).lower()
        w2 = re.sub(r'[^\w]', '', flagged[i + 1]["word"]).lower()
        # Beyond the explicit pair list, also flag pairs whose joined form is in
        # the exact profanity list ("blow"+"job" -> "blowjob"), where neither
        # half alone is profane. Min length 3 per half so stray short tokens
        # can't assemble into a hit ("s"+"hit").
        joined_hit = (
            len(w1) >= 3 and len(w2) >= 3
            and (w1 + w2) not in WHITELIST
            and profanity.contains_profanity(w1 + w2)
        )
        if (w1, w2) in compounds or joined_hit:
            flagged[i]["is_profanity"] = True
            flagged[i + 1]["is_profanity"] = True

    # Third pass: compound halves separated by one filler word ("hijo de puta").
    for i in range(len(flagged) - 2):
        w1 = re.sub(r'[^\w]', '', flagged[i]["word"]).lower()
        mid = re.sub(r'[^\w]', '', flagged[i + 1]["word"]).lower()
        w3 = re.sub(r'[^\w]', '', flagged[i + 2]["word"]).lower()
        if mid in COMPOUND_GAP_WORDS and (w1, w3) in compounds:
            flagged[i]["is_profanity"] = True
            flagged[i + 1]["is_profanity"] = True
            flagged[i + 2]["is_profanity"] = True

    return flagged
