# Cleanse — Lyrics-Aligned Profanity Detection (Second Detection Channel)

**Engineering Spec v1.0 — June 2026**
**Status:** Draft for implementation
**Depends on:** Demucs-first pipeline reorder (Stage 4, conditional — see §3)

---

## 1. Problem & Goal

The ASR channel (faster-whisper) misses profanity in three ways: it mishears words against dense instrumentation, it sanitizes output ("f***", soft substitutes) due to censored captions in Whisper's training data, and it occasionally skips words entirely. Each miss is a shipped export with an audible cuss word — the single worst failure mode for a censoring product.

We already fetch lyrics via lyricsgenius. Genius lyrics are near-ground-truth text for the explicit version of most commercial tracks. If we **force-align the lyrics text to the audio**, we get a timestamp for every lyric word — including profane words the ASR never produced. Scanning the *lyrics text* for profanity and reading timestamps from the *alignment* gives us a detection channel that is independent of ASR errors.

**Goal:** Materially reduce missed-profanity rate by fusing a lyrics-alignment detection channel with the existing ASR channel.

**Secondary goal:** Tighter censor cut boundaries — CTC forced alignment produces more precise word boundaries than Whisper's native word timestamps.

**Non-goals (v1):**
- Replacing the ASR channel (fusion is strictly additive — the lyrics channel can never *remove* an ASR detection)
- Songs with no retrievable lyrics (channel silently no-ops)
- Languages beyond English and Spanish (matches current wordlist coverage)
- Karaoke-style lyric display in the UI

---

## 2. Key Design Decisions

**D1 — Aligner: torchaudio's built-in forced alignment, not WhisperX/MFA.**
torchaudio (≥2.1, we ship 2.7.1) includes `torchaudio.functional.forced_align` and the `MMS_FA` wav2vec2 pipeline built for exactly this. Rationale:
- Zero new heavyweight dependencies — no WhisperX → pyannote chain, no Montreal Forced Aligner (Kaldi binary, a PyInstaller nightmare)
- MMS_FA is multilingual → English and Spanish from one model, matching `custom_profanity.txt` / `custom_profanity_es.txt`
- One new model weight download, managed exactly like the whisper/demucs weights
- CTC alignment is cheap — a fraction of transcription cost

**D2 — Align against the Demucs vocal stem, not the full mix.** Alignment quality on isolated vocals is dramatically better. Demucs already runs in the pipeline; the stem is free.

**D3 — Fusion with confidence tiers, not blind union.** Lyrics can mismatch the actual recording (radio edit, remix, live, wrong Genius match). Per-word and global alignment scores gate whether a lyrics-only detection auto-censors or gets flagged for review in the manual editor.

**D4 — The channel self-disables on low confidence.** A bad alignment must degrade to current behavior, never to garbage censors. Gate failures are logged and surfaced in the API response so the UI can explain why.

---

## 3. Architecture

### Revised pipeline order

```
ingest
  └─ demucs separate (vocals / instrumental)
       ├─ faster-whisper transcribe (input: VOCAL STEM)      ── ASR channel
       └─ lyrics fetch ─ normalize ─ forced align (stem)     ── lyrics channel
                │                                                  │
                └────────────► detection_fusion ◄──────────────────┘
                                     │
                          censor render (mute/beep/reverse/tape-stop)
                                     │
                                  export (WAV/AIFF/video)
```

**Prerequisite note:** this assumes separation runs *before* transcription. If the current pipeline transcribes the full mix first, the reorder happens in Stage 4 and is a win on its own (lower WER on stems). The lyrics fetch + alignment branch runs in parallel with transcription — both consume the vocal stem.

### New modules (`backend/`)

| Module | Responsibility |
|---|---|
| `lyrics_normalizer.py` | Genius raw text → aligned-ready token sequence with traceability |
| `lyrics_aligner.py` | (vocal stem, tokens, lang) → per-word timestamps + scores |
| `detection_fusion.py` | Merge ASR + lyrics detections into unified detection list |

### Modified modules

| Module | Change |
|---|---|
| `audio_processor.py` | Orchestration: parallel branch, fusion step |
| `profanity_detector.py` | Expose `scan_tokens()` for raw lyric tokens; add fuzzy/phonetic matching layer |
| `lyrics_fetcher.py` | Return raw text + fetch metadata (matched title/artist, for sanity checks) |
| `main.py` | Response schema additions (§6) |
| model manager / weights cache | MMS_FA checkpoint download + checksum |

### New dependencies

- `rapidfuzz` (pure wheel, trivial to bundle) — fuzzy matching
- `jellyfish` or `phonetics` — double metaphone (pick whichever bundles cleaner; both are small)
- **No uroman.** MMS_FA's docs suggest uroman for romanization, but it's a Perl tool — for EN/ES we implement a ~30-line Latin normalizer in-house (§4.1)

---

## 4. Module Specs

### 4.1 `lyrics_normalizer.py`

**Input:** raw Genius lyrics string.
**Output:** `list[LyricToken]`

```python
@dataclass
class LyricToken:
    idx: int            # position in normalized sequence
    raw: str            # original surface form ("Fuckin',")
    norm: str           # alignment form ("fuckin")
    char_span: tuple[int, int]  # span in raw lyrics, for traceability/debugging
    is_adlib: bool      # came from (parenthetical)
```

**Normalization rules:**
1. Strip section headers: `[Verse 1]`, `[Chorus]`, `[Bridge: Artist]` — regex `^\[.*\]$` per line
2. Strip Genius artifacts: contributor counts, "Embed" suffix, "You might also like" injections
3. Parentheticals: **keep** the words (background vocals are sung and may contain profanity) but tag `is_adlib=True` — fusion treats their scores with more leniency since ad-libs align worse
4. Lowercase; strip punctuation except intra-word apostrophes
5. Diacritic folding for ES: `á→a, é→e, í→i, ó→o, ú→u, ü→u, ñ→n` (MMS_FA charset is `a–z` + `'`)
6. Digits → `<star>` token (MMS_FA's wildcard, matches any audio). Don't bother with num2words in v1 — profanity is never numeric
7. Any token that normalizes to empty or contains residual non-charset chars → `<star>`

**Tests:** table-driven — headers, ad-libs, ES diacritics, apostrophes, digits, empty lines, Genius artifacts.

### 4.2 `lyrics_aligner.py`

**API:**

```python
@dataclass
class AlignedWord:
    token_idx: int
    start: float        # seconds
    end: float
    score: float        # mean per-frame CTC prob, 0–1

@dataclass
class AlignmentResult:
    words: list[AlignedWord]
    global_score: float      # mean of word scores, ad-libs excluded
    coverage: float          # aligned-word span / vocal-activity span (sanity)

def align(stem: np.ndarray | Path, tokens: list[LyricToken],
          language: str, device: str) -> AlignmentResult: ...
```

**Implementation:**
1. Load `torchaudio.pipelines.MMS_FA` model — cached singleton, lazy-loaded on first use (same pattern as whisper/demucs model loading)
2. Resample stem to 16 kHz mono
3. Compute emissions. For tracks > ~5 min, chunk emissions (e.g., 60 s windows, batched) to bound memory — emissions are concatenated before alignment; CTC alignment itself runs on the full sequence (it's cheap, O(T·N) on CPU is fine)
4. `forced_align(emissions, targets)` → frame-level token spans → merge into word spans
5. Word score = mean token probability across the word's frames

**Device:** try MPS first on Apple Silicon, fall back to CPU on any MPS op failure (wav2vec2 emission is the only heavy op; verify MPS support in the spike — torch MPS coverage for wav2vec2 has historically been fine, but verify on 2.7.1). CPU is acceptable: target < 0.1× realtime.

**Edge cases:**
- Instrumental intros/outros/breaks: CTC blank tokens absorb them natively — no special handling
- Audio longer than lyrics (extended/DJ edit): alignment is globally monotonic; extra audio maps to blanks. `coverage` will read low → gate catches it
- Lyrics longer than audio (radio edit of the file vs. explicit lyrics): tail words get near-zero scores → per-word gate catches them

### 4.3 Lyrics-text profanity scan (`profanity_detector.py` additions)

Scan **normalized lyric tokens** (not audio, not ASR output) against the existing wordlists:

1. **Exact** — current wordlist lookup (EN + ES lists by detected/declared language)
2. **Fuzzy** — `rapidfuzz` ratio ≥ 88 against wordlist entries, min token length 4 (prevents "duck"-class false positives on short words; tune in Stage 3)
3. **Phonetic** — double metaphone key equality against precomputed wordlist keys (catches "phuck", "shyt", "biatch"-class spellings — these appear in Genius transcriptions of stylized delivery)

Output per hit: `{token_idx, matched_term, match_type: "exact"|"fuzzy"|"phonetic"}`.

The same fuzzy/phonetic layer should also be applied to the ASR transcript (it's the same function) — that's a free recall improvement on the existing channel and ships as part of this work.

### 4.4 `detection_fusion.py`

**Inputs:** ASR detections (existing shape: word, start, end, confidence), lyrics detections (token hit + `AlignedWord`), thresholds (config).

**Unified output:**

```python
@dataclass
class Detection:
    word: str
    start: float
    end: float
    source: Literal["asr", "lyrics", "both"]
    confidence: float          # asr prob, align score, or max of both
    match_type: str            # exact/fuzzy/phonetic
    review_required: bool
```

**Merge logic:**
1. Match ASR ↔ lyrics detections: temporal IoU ≥ 0.3 **or** midpoint distance ≤ 250 ms, same/equivalent matched term → merge as `source="both"`. Timestamps: use the aligner's boundaries when its word score ≥ `T_TIMESTAMP` (default 0.55), else union of both spans. `review_required=False`.
2. **Lyrics-only** detections:
   - `global_score ≥ T_GLOBAL` (default 0.50) **and** word `score ≥ T_AUTO` (default 0.60) → auto-censor, `review_required=False`
   - word score in `[T_REVIEW, T_AUTO)` (default 0.35–0.60), or `is_adlib` → include but `review_required=True` (amber state in editor)
   - below `T_REVIEW` → drop, log
3. **ASR-only** detections: unchanged from current behavior, `review_required=False`.
4. Output sorted by start time; overlapping censor spans merged at render time (existing behavior).

All thresholds live in one config block, overridable via request for tuning.

### 4.5 Channel quality gate

Before fusion, the lyrics channel disables itself entirely (status reported, ASR-only behavior preserved) when any of:
- No lyrics found / Genius fetch error
- Fetch sanity check fails: matched Genius title/artist vs. file tags (tinytag) — fuzzy match below threshold (guards wrong-song matches)
- `global_score < T_CHANNEL` (default 0.40) — lyrics don't match this recording (remix, live, cover, clean-version lyrics)
- `coverage < 0.5`
- Language not in {en, es}

---

## 5. Model Weights & Packaging

- MMS_FA checkpoint: download on first use into the existing model cache directory alongside whisper/demucs weights, with checksum validation. **Verify exact size in Stage 0** and update the "first run" UX copy if it's large.
- Offline / download failure → channel disabled with `status="model_unavailable"`; processing proceeds ASR-only.
- PyInstaller: no new binaries — torchaudio is already bundled. Add `rapidfuzz` + metaphone lib to `cleanse-backend.spec` hidden imports if needed. Validate on both mac arches and Windows in Stage 6.

---

## 6. API Schema Changes (`main.py`)

`detections[]` items gain: `source`, `match_type`, `review_required`, optional `align_score`.

New top-level field:

```json
"lyrics_channel": {
  "status": "ok | no_lyrics | low_confidence | wrong_match | model_unavailable | unsupported_language | disabled",
  "global_score": 0.78,
  "matched_title": "...",
  "matched_artist": "..."
}
```

Config/request flag: `enable_lyrics_channel` (default `true`).

Backward compatibility: with the channel disabled, the response must be byte-identical to current output (regression-tested).

---

## 7. UI Changes (Electron / React)

Scope is deliberately small for v1:

1. **Source badge** per censor segment in the transcript-synced editor: `ASR`, `Lyrics`, `Both` (subtle, e.g., tiny glyph + tooltip)
2. **Review state**: `review_required` segments render amber, pre-enabled but visually distinct; one-click confirm/dismiss. A count chip ("2 to review") near the export button so they're not missed
3. **Channel status banner** in the editor when status ≠ `ok` — e.g., "Lyrics couldn't be matched to this recording — detection ran on transcription only"
4. **Settings toggle**: "Use lyrics to improve detection" (default on)

No waveform/wavesurfer changes beyond the badge/amber styling on existing region rendering.

---

## 8. Performance Budget

- Lyrics channel total (fetch + normalize + align + scan) adds **< 10%** to end-to-end processing time for a 4-min track
- Lyrics fetch runs concurrently with transcription (network-bound, free)
- Alignment runs after the stem exists; reuse the in-memory stem, don't re-read from disk
- Memory: chunked emissions keep peak under control for long files; cap supported alignment length at 20 min (matches sane DJ-edit lengths), beyond which channel disables with status `disabled`

---

## 9. Failure Modes

| Failure | Behavior |
|---|---|
| No lyrics on Genius | Channel off, status `no_lyrics`, silent to flow |
| Wrong song matched | Tag sanity check or global score gate → `wrong_match` |
| Genius lyrics are the clean version | Lyrics scan finds nothing → channel contributes zero detections; ASR channel unaffected (fusion is additive-only) |
| Remix / live / different arrangement | Global score / coverage gate → `low_confidence` |
| File has no/poor tags | Sanity check degrades to score-gate-only (don't hard-fail on missing tags) |
| Genius rate limit / network error | Bounded retries (2, jittered), then `no_lyrics` |
| MPS op failure | Per-call CPU fallback, logged once via Sentry breadcrumb |

---

## 10. Testing & Metrics

**Unit:** normalizer table tests; fuzzy/phonetic matcher table tests (true hits + near-miss negatives: "duck", "ship", "ass" in "class"); fusion logic with synthetic detection lists covering every tier and gate.

**Integration fixtures:** local-only fixture directory (audio not committed) of ~10 tracks with hand-labeled profanity timestamps committed as JSON. Must include: clean-mix ASR-misses (the motivating cases), a Spanish track, a track with ad-lib profanity, a radio-edit-audio/explicit-lyrics mismatch (gate test), a no-lyrics obscure track.

**Metrics gates (Stage 4 exit criteria):**
- Recall on hand-labeled profane words: lyrics channel catches ≥ 80% of words the ASR channel missed on the fixture set
- Timestamp MAE for `both`-source detections ≤ 120 ms vs. hand labels
- Zero new false-positive auto-censors on the fixture set (review-flagged FPs acceptable)
- Channel-disabled output byte-identical to pre-change output (regression)

---

## 11. Staged Implementation Plan (Claude Code)

**Stage 0 — Alignment spike (0.5 day)**
Standalone script in `backend/spikes/`: take 2 known tracks (one EN with a confirmed ASR miss, one ES), run Demucs → MMS_FA alignment → print timestamps for hand-picked profane words. Verify checkpoint size, MPS vs CPU behavior, and timestamp accuracy by ear/in an editor.
*Exit:* profane-word timestamps within ~150 ms on both tracks; go/no-go on MMS_FA.

**Stage 1 — `lyrics_normalizer.py` (0.5 day)**
Module + full unit suite. Pure-Python, no model deps — fast to land.

**Stage 2 — `lyrics_aligner.py` (1 day)**
Model loading/caching, chunked emissions, word spans + scores, coverage metric, device fallback. Tests against Stage 0 tracks with committed expected-output JSON (tolerance bands).

**Stage 3 — Fuzzy/phonetic detection layer (0.5 day)**
`scan_tokens()` in `profanity_detector.py`, applied to both lyric tokens and ASR words. Threshold tuning against the false-positive table tests.

**Stage 4 — Fusion + orchestration (1 day)**
`detection_fusion.py`, pipeline reorder (separate-first) if not already done, parallel lyrics branch, schema changes, quality gates, regression tests, fixture metrics run.
*Exit:* §10 metrics gates pass.

**Stage 5 — UI (1 day)**
Badges, review flow, status banner, settings toggle.

**Stage 6 — Packaging & perf (0.5–1 day)**
Weight download/caching + checksum, PyInstaller spec updates, build + smoke test on mac arm64, mac x64, Windows; perf budget validation; Sentry breadcrumbs for gate decisions.

**Total: ~5 days.** Stages 1–3 are independent and parallelizable across Claude Code sessions; Stage 4 integrates.

---

## 12. Open Questions / Risks

1. **MMS_FA checkpoint size + license** — verify in Stage 0 (model is CC-BY-NC per MMS release notes historically — **confirm current license terms before shipping in a paid product**; if NC is a problem, fallback is a wav2vec2 CTC model with a permissive license, e.g., torchaudio's `WAV2VEC2_ASR_BASE_960H` for EN + a HF Spanish CTC model, same alignment code)
2. MPS support for wav2vec2 emission on torch 2.7.1 — spike verifies; CPU fallback is acceptable
3. Genius ToS/rate limits at scale — current usage already exists; alignment adds no new fetch volume
4. Whether the pipeline reorder (separate-first) changes timing expectations in the manual editor for existing users — verify transcript offsets are unaffected
