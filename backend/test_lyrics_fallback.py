#!/usr/bin/env python3
"""Test script for progressive artist fallback in lyrics fetching."""

import sys
from lyrics_fetcher import _extract_first_artist, fetch_lyrics


def test_extract_first_artist():
    """Test the _extract_first_artist helper function."""
    print("=" * 60)
    print("Testing _extract_first_artist()")
    print("=" * 60)

    test_cases = [
        ("Playboi Carti, Future, & Travis Scott", "Playboi Carti"),
        ("Playboi Carti & Future", "Playboi Carti"),
        ("Drake feat. Lil Baby", "Drake"),
        ("Drake ft. Lil Baby", "Drake"),
        ("Drake ft Lil Baby", "Drake"),
        ("Artist (feat. Other)", "Artist"),
        ("Artist (ft. Other)", "Artist"),
        ("Single Artist", "Single Artist"),
        ("Artist1 and Artist2", "Artist1"),
        ("Artist featuring Other", "Artist"),
    ]

    passed = 0
    failed = 0

    for input_artist, expected in test_cases:
        result = _extract_first_artist(input_artist)
        status = "✓" if result == expected else "✗"
        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} '{input_artist}' → '{result}' (expected: '{expected}')")

    print(f"\nResults: {passed} passed, {failed} failed\n")
    return failed == 0


def test_fetch_lyrics():
    """Test the fetch_lyrics function with real API calls."""
    print("=" * 60)
    print("Testing fetch_lyrics() with progressive fallback")
    print("=" * 60)

    test_cases = [
        {
            "name": "Multi-artist (comma + ampersand)",
            "artist": "Playboi Carti, Future, & Travis Scott",
            "title": "CHARGE DEM HOES A FEE",
            "duration": None,
        },
        {
            "name": "Featured artist (ampersand)",
            "artist": "Playboi Carti & Future",
            "title": "Type Shit",
            "duration": None,
        },
        {
            "name": "Single artist (baseline)",
            "artist": "Playboi Carti",
            "title": "Molly",
            "duration": None,
        },
        {
            "name": "Featured artist (feat.)",
            "artist": "Drake feat. Lil Baby",
            "title": "Yes Indeed",
            "duration": None,
        },
    ]

    print("\nNote: This makes real API calls to LRCLIB. Watch the logs above.\n")

    for test_case in test_cases:
        print(f"\n--- Test: {test_case['name']} ---")
        print(f"Artist: {test_case['artist']}")
        print(f"Title: {test_case['title']}")
        print()

        result = fetch_lyrics(
            artist=test_case['artist'],
            title=test_case['title'],
            duration=test_case['duration']
        )

        if result:
            has_plain = bool(result.get('plain_lyrics'))
            has_synced = bool(result.get('synced_lyrics'))
            print(f"✓ SUCCESS: Found lyrics (plain={has_plain}, synced={has_synced})")

            # Show a snippet of the lyrics
            if result.get('plain_lyrics'):
                snippet = result['plain_lyrics'][:100].replace('\n', ' ')
                print(f"  Preview: {snippet}...")
        else:
            print(f"✗ FAILED: No lyrics found")

        print()


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("LYRICS FALLBACK TEST SUITE")
    print("=" * 60 + "\n")

    # Test the helper function
    helper_passed = test_extract_first_artist()

    # Test the main function with API calls
    print("\n")
    test_fetch_lyrics()

    print("\n" + "=" * 60)
    print("TEST SUITE COMPLETE")
    print("=" * 60)

    if not helper_passed:
        print("\n⚠️  Some helper function tests failed!")
        sys.exit(1)
    else:
        print("\n✓ All helper function tests passed!")
        print("Check the fetch_lyrics() results above for API behavior.")
