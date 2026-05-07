"""Profanity detection using better-profanity library."""

import re
import unicodedata
from pathlib import Path
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

        flagged.append({**w, "is_profanity": is_profane})

    # Second pass: check adjacent word pairs for compound profanity
    compounds = COMPOUND_PROFANITY
    if language == "es":
        compounds = COMPOUND_PROFANITY | COMPOUND_PROFANITY_ES
    for i in range(len(flagged) - 1):
        w1 = re.sub(r'[^\w]', '', flagged[i]["word"]).lower()
        w2 = re.sub(r'[^\w]', '', flagged[i + 1]["word"]).lower()
        if (w1, w2) in compounds:
            flagged[i]["is_profanity"] = True
            flagged[i + 1]["is_profanity"] = True

    return flagged
