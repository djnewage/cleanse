"""Regression tests for the v1.17.0 wrong-song lyrics incident.

A mashup tagged 'The Notorious B.I.G. - Me & My Bitch x Doin It (What If
Mix)' fetched SYNCED lyrics for 'Hypnotize': the swapped-tags metadata
candidate turned the artist into a "title", the title-only LRCLIB search
matched a different song by the same artist, and its duration (230s vs 226s)
passed the tolerance gate by coincidence. The wrong lyrics then poisoned
Whisper's initial_prompt and rewrote transcribed words, muting less than
v1.16 did with no lyrics at all.

Three defenses, each tested here:
1. Title-only LRCLIB search is disabled for guessed metadata candidates.
2. fetch_lyrics stamps from_tag_metadata so guessed-candidate lyrics are
   never used as the transcription prompt.
3. apply_lyrics_pipeline rejects synced lyrics whose content doesn't match
   the transcript BEFORE any correction touches the words.
"""

import lyrics_fetcher as lf
from main import apply_lyrics_pipeline


def _search_stub(monkeypatch, responder):
    """Route requests.get through `responder(url, params) -> list | None`.
    None means HTTP 404; a list is the /search JSON body."""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, dict(params or {})))

        class R:
            status_code = 404

        body = responder(url, params or {})
        if body is None:
            return R()
        r = R()
        r.status_code = 200
        r.json = lambda: body
        return r

    monkeypatch.setattr(lf.requests, "get", fake_get)
    return calls


class TestTitleOnlyRestriction:
    def test_disallowed_never_searches_without_artist(self, monkeypatch):
        calls = _search_stub(monkeypatch, lambda url, params: [] if url.endswith("/search") else None)
        result = lf._fetch_lrclib("Artist", "Title", duration=200.0, allow_title_only=False)
        assert result is None
        searches = [p for u, p in calls if u.endswith("/search")]
        assert searches, "expected at least one search attempt"
        assert all("artist_name" in p for p in searches)

    def test_allowed_still_falls_back_to_title_only(self, monkeypatch):
        calls = _search_stub(monkeypatch, lambda url, params: [] if url.endswith("/search") else None)
        lf._fetch_lrclib("Artist", "Title", duration=200.0, allow_title_only=True)
        searches = [p for u, p in calls if u.endswith("/search")]
        assert any("artist_name" not in p for p in searches)


class TestFetchLyricsCandidateTrust:
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setattr(lf, "_LYRICS_CACHE_DIR", str(tmp_path))
        monkeypatch.setattr(lf, "fetch_genius_lyrics", lambda a, t: None)

    def test_fallback_candidate_hit_flagged_untrusted(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)
        rounds = []

        def fake_round(artist, title, duration, allow_title_only=True):
            rounds.append((artist, title, allow_title_only))
            if artist == "Chief Keef":  # only the title-field guess hits
                return {"plain_lyrics": "words", "synced_lyrics": None,
                        "lyrics_source": "lrclib", "duration_mismatch": False}
            return None

        monkeypatch.setattr(lf, "_fetch_lyrics_round", fake_round)
        result = lf.fetch_lyrics("Glo Radio", "Chief Keef - Whos Concerned", 180.0)
        assert result["from_tag_metadata"] is False
        # Tags-as-is may use title-only; every guessed candidate may not.
        assert rounds[0][2] is True
        assert all(allow is False for _, _, allow in rounds[1:])

    def test_tag_candidate_hit_flagged_trusted(self, monkeypatch, tmp_path):
        self._setup(monkeypatch, tmp_path)
        monkeypatch.setattr(
            lf, "_fetch_lyrics_round",
            lambda a, t, d, allow_title_only=True: {
                "plain_lyrics": "words", "synced_lyrics": None,
                "lyrics_source": "genius", "duration_mismatch": False,
            },
        )
        result = lf.fetch_lyrics("Chief Keef", "Whos Concerned", 180.0)
        assert result["from_tag_metadata"] is True

    def test_incident_swapped_tags_title_only_no_longer_fetches(self, monkeypatch, tmp_path):
        """The exact failure shape: artist-name-as-title matches a different
        song by that artist whose duration coincidentally fits the audio."""
        self._setup(monkeypatch, tmp_path)

        def responder(url, params):
            if not url.endswith("/search"):
                return None
            # The long mashup title matches nothing on LRCLIB; only a search
            # whose track_name is the ARTIST (the swapped-tags guess) hits.
            if "Notorious" not in params.get("track_name", ""):
                return []
            if "artist_name" in params:
                return []  # LRCLIB has no artist matching the mashup title
            return [{  # title-only for "The Notorious B.I.G." -> Hypnotize
                "duration": 230.0,
                "syncedLyrics": "[00:10.00] sicka than your average",
                "plainLyrics": "sicka than your average",
            }]

        _search_stub(monkeypatch, responder)
        result = lf.fetch_lyrics(
            "The Notorious B.I.G.", "Me & My Bitch x Doin It (What If Mix)", 226.0
        )
        assert result is None


class TestPipelineRejectsWrongSyncedLyrics:
    # Transcript: a repetitive hook, the shape that coincidentally clears
    # word-level alignment scores against unrelated rap lyrics.
    def _transcript(self):
        words = []
        t = 10.0
        for _ in range(8):
            for text in ["just", "me", "and", "my", "bitch"]:
                words.append({
                    "word": text, "start": round(t, 2), "end": round(t + 0.3, 2),
                    "confidence": 0.9, "is_profanity": text == "bitch",
                })
                t += 0.4
        return words

    WRONG_SYNCED = "\n".join(
        f"[00:{10 + i * 4:02d}.00] {line}"
        for i, line in enumerate([
            "sicka than your average poppa twist cabbage off instinct",
            "niggaz don't think stink pink gators detroit players",
            "timbs for hooligans in brooklyn dead right head right",
            "poppa been smooth since days of underoos never lose",
            "never choose to bruise crews who do something to us",
            "girls walk to us wanna do us screw us who us",
        ])
    )

    def test_wrong_song_synced_lyrics_ignored(self):
        words = self._transcript()
        before = [(w["word"], w["is_profanity"]) for w in words]
        result = apply_lyrics_pipeline(
            [dict(w) for w in words], 226.0, "en",
            lyrics=None, synced_lyrics=self.WRONG_SYNCED,
        )
        assert [(w["word"], w["is_profanity"]) for w in result] == before
        assert not any("original_word" in w for w in result)

    def test_matching_synced_lyrics_still_correct_words(self):
        words = self._transcript()
        # Whisper misheard one 'bitch' as 'bich' (low confidence).
        words[4]["word"] = "bich"
        words[4]["confidence"] = 0.3
        words[4]["is_profanity"] = False
        matching = "\n".join(
            f"[00:{10 + i * 2:02d}.00] just me and my bitch" for i in range(8)
        )
        result = apply_lyrics_pipeline(
            [dict(w) for w in words], 226.0, "en",
            lyrics=None, synced_lyrics=matching,
        )
        corrected = [w for w in result if w.get("original_word") == "bich"]
        assert corrected and corrected[0]["word"] == "bitch"
        assert corrected[0]["is_profanity"] is True
