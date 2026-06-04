# Cleanse — Auto Intro/Outro Edit (v1 Spec)

## Goal

Generate mix-friendly DJ edits from any analyzed track: a phrase-aligned **beat intro** and **outro**, built by looping the drum (or drums+bass) stem to the track's grid and transitioning into/out of the **untouched original audio** on a downbeat. Output must be grid-accurate, seam-clean, metadata-preserving, and tagged for the DJ library.

This reuses the existing Demucs stem pipeline. The only genuinely new capability is reliable downbeat alignment.

---

## The linchpin: the beatgrid (de-risk this FIRST)

Every edit is sample-accurate to the "1" of each bar, or it's garbage. Demucs gives stems; faster-whisper gives word timestamps; neither gives a beatgrid. So:

- **Preferred — import from Serato.** Serato beatgrids are human-tunable and reliable. The Recrate codebase already parses Serato's binary DB; if that grid can be read here, the downbeat is battle-tested and free. This is also a real edge no pure stem tool has.
- **Fallback — detect it.** `madmom` (DBNDownBeatTrackingProcessor) is the gold standard for downbeats but has dependency/install pain. `librosa` is easy but unreliable on the downbeat specifically (fine for tempo, not for the "1").

**Action before any DSP work:** a throwaway spike that, for a handful of representative tracks, prints detected/imported downbeat sample positions and BPM, and lets a human eyeball whether the "1" is correct. Do not build the loop/assembly code until the grid source is trusted. If the "1" is off by one beat, the whole feature is unusable.

---

## Architecture / data flow

**Inputs**
- Original decoded audio (full fidelity)
- Demucs stems: drums, bass, other, vocals
- Beatgrid: BPM + downbeat sample positions (imported or detected)
- User options: intro length (16/32 bars), outro length, transition style, stem set (drums vs drums+bass)

**Output**
- Rendered audio (format TBD — see open questions), metadata preserved (BPM, key, artwork), tagged `(Intro Edit)`. If censoring is also enabled, stacks with the clean pass.

---

## v1 algorithm

1. **Bar math.** `samples_per_bar = (60 / BPM) * 4 * sampleRate`. All cuts snap to downbeat sample positions from the grid.
2. **Pick the source loop.** Not the real intro (often sparse) — a representative 2- or 4-bar drum phrase from the main groove. v1 default: first downbeat where the drum stem hits full energy (RMS threshold). User can nudge which bar.
3. **Build a seamless loop.** Cut the source loop on exact downbeats. Because it's an integer number of bars at the exact BPM, it's rhythmically seamless by construction; only kill splice clicks with a zero-crossing snap or a 2–10 ms micro-crossfade on the stem.
4. **Repeat to length.** Tile the drum (or drums+bass) loop for the chosen 16/32 bars.
5. **Transition into the body.** Enter the full original track on a downbeat. v1 = hard drop on the "1" (cleanest, most common for club/hip-hop). Crossfade-join is only to kill the seam click, not a musical fade.
6. **Body = original audio.** Use the untouched original for the main track, NOT the Demucs recombination — only the intro/outro loops are stem-derived, so the body inherits zero separation artifacts.
7. **Outro.** Mirror the above: ride out on the looped beat for N bars after a chosen downbeat near the end.
8. **Render + tag.** Carry BPM/key/artwork, append `(Intro Edit)`, stack with clean pass if active.

---

## v1 scope boundaries (explicitly OUT)

- Non-constant tempo (live drums, older recordings) — restrict to steady-tempo material.
- Non-4/4 time signatures.
- "Smart" loop-source selection beyond the first-strong-bar default + manual override.
- Build-up transitions, risers, filter sweeps (that's v1.5).
- Mashup / key-matching (that's v2).

---

## UI requirements

- Intro length selector (16 / 32 bars), outro toggle + length.
- Transition style (v1: hard drop only).
- Stem set toggle (drums only / drums + bass).
- **Preview is non-negotiable.** Auto-detection will occasionally pick the wrong downbeat. Let the DJ hear the ~4 bars around the drop and nudge the entry point and loop-source bar before render. Same logic as the existing censor editor: put a human in the loop where detection has a ceiling.

---

## Phasing

**v1** — 4/4, steady tempo, drums-only or drums+bass loop, fixed 16/32 bar intro + outro, hard-drop transition, grid imported-or-detected, manual override of entry point and loop bar, preview.

**v1.5** — build-up transitions (bass-in for last 8 bars), optional riser samples, smarter auto loop-source picking.

**v2** — mashup builder (clean acapella of A over instrumental of B, tempo/key-matched).

---

## Effort estimate (v1)

| Component | Hours |
|---|---|
| Grid (reuse Serato parser vs. standalone madmom) | 4–8 |
| Seamless loop construction + splice DSP | 4–6 |
| Intro/outro assembly + transition logic | 4–6 |
| Render / metadata / tagging into existing pipeline | 2–4 |
| UI (bar count, transition, manual override, preview) | 6–10 |

**Total: ~25–35h.** Spread lives almost entirely in (a) reusing the Serato grid vs. detecting, and (b) how smart the auto loop-picker needs to be. Reuse the grid + ship a manual loop default → low end.

---

## v1 acceptance criteria

- Imported/detected downbeat is correct on the test set (manual eyeball + a couple of programmatic sanity checks where possible).
- Loop seam is click-free at the boundary.
- Body audio is verifiably the original, not the stem recombination.
- Full metadata (BPM, key, artwork) survives to the output file.
- Preview plays the transition zone and entry-point nudges take effect before render.

---

## Open questions for Tristan

1. Does Cleanse already do any beat/tempo detection, or is this net-new?
2. Can the Serato grid parser from Recrate be reused/shared here, or is Cleanse fully siloed from that code?
3. Output formats needed (WAV / AIFF / MP3 / all)?
4. Default intro length — 16 or 32 bars?
