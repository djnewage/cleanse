"""Profanity detection using better-profanity library."""

import re
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

    # Remove empty strings
    return [v for v in variations if v]


def flag_profanity(words: list[dict]) -> list[dict]:
    """
    Take a list of transcribed words and add an `is_profanity` flag to each.

    Enhanced version that checks multiple normalized variations of each word
    to catch contractions, punctuation, and common variations.

    Args:
        words: List of {"word": str, "start": float, "end": float, "confidence": float}

    Returns:
        Same list with added "is_profanity": bool field
    """
    flagged = []
    for w in words:
        word_text = w["word"]

        # Generate normalized variations and check if any are profane
        variations = _normalize_word(word_text)
        is_profane = any(profanity.contains_profanity(variant) for variant in variations)

        flagged.append({**w, "is_profanity": is_profane})
    return flagged
