"""Profanity detection using better-profanity library."""

from better_profanity import profanity

# Load the default word list
profanity.load_censor_words()


def flag_profanity(words: list[dict]) -> list[dict]:
    """
    Take a list of transcribed words and add an `is_profanity` flag to each.

    Args:
        words: List of {"word": str, "start": float, "end": float, "confidence": float}

    Returns:
        Same list with added "is_profanity": bool field
    """
    flagged = []
    for w in words:
        word_text = w["word"]
        # Check if the word itself is profane
        is_profane = profanity.contains_profanity(word_text)
        flagged.append({**w, "is_profanity": is_profane})
    return flagged
