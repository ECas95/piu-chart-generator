# Research and development of the generator

Technical history of the algorithm (v362 → v5 / variant F). Each version came from a concrete failure observed while playing.

## Problem
Given a source chart (SM/SSC, 5-key BMS or PRIME NX), produce 4 Single and 4 Double levels **without adding or moving notes**: lower levels are subsets of the original rhythm; the only decision is which panel each note lands on.

## v362 → v363: impossible spins
- **Cause:** the foot plan allowed the same foot several times in a row right after the other foot released a hold, and in Double the anti-spin guard was off. Players alternate feet naturally, so their "natural" reading diverged and they ended up facing backwards.
- **Fix:** strict parity (the same foot twice only for a jack on the same panel, or while the other foot holds).
- `playability.py`: an independent natural-foot Viterbi. Acceptance gate: no stance beyond 90°, no double steps under 200 ms, at most 45° in bands 1–3; it retries seeds and, failing that, excludes the conflicting notes (ledgered).
- **Level:** estimate of a frozen native difficulty model (`lib/engine/difficulty_model.py` + `data/official_chart_metrics.json`, 21 official neighbours, validated ±1 against real charts); density is retuned until the estimate falls inside the band.
- `rhythm_extension`: grid tolerance bug (float32 drift, 1e-4) fixed; local grid per previous note and an 80 ms minimum gap (DDR sources reach 18–20).

## v2–v3: study of official charts
1,566 official Single charts (Fiesta 2, Prime, Prime 2, XX) were analysed. Measured facts: they never end facing backwards; turns are 0 % at levels 1–5, ~3 % at 6–12 and 11–14 % at 13+; one-step crossovers ~80–88 %; turns appear in hot sections and on eighth notes, almost never on the first note of a run; jumps 6–10 %; holds ~18 % at 13+. Scripts are in `docs/research/` (`audit_official.py`, `make_profiles.py`), rule proposals in `CHARTING_RULES.md`. Result: a `TurnBudget` in `musical.py` with per-level turn targets.

## v3.1: the wrong foot
A level-18 chart left players facing backwards even though aggregate statistics looked normal. **Cause:** the composer followed a validated pattern's *panels* with the wrong *foot*. **Fix:** each pattern stores its foot per note (`feet`, `start_foot`, `end_foot`); "following" = panel and foot; a post-compose check in `compose()`: every crossed stance needs 3 notes before and 2 after followed exactly, otherwise it is blocked and recomposed.

## v4: variants
`PIU_VARIANT`: **A** safe (crossovers only inside patterns), **B** official (crossovers whose 6-note context appears ≥ 5 times in official charts), **C** fluid (no crossovers, twists only).

## v5: ArrowVortex generator
Port of `StreamGenerator.cpp` (alternating-feet random walk, difficulty = step length) into `hybrid/vortex.py`, applied live from the real feet (precomputed hints drifted out of phase: ~45 % followed versus 80–97 %). A per-level side weight is needed because the x-rule alone gives ~27 % sideways stances on pump. Variants **D** (patterns + vortex) and **E** (vortex alone). **Variant F = E + whole T1–T5 twists** (~1 per 40/24/18 notes by band, none with gaps under 80 ms, level ≥ 6): 0 backwards stances, turns 3.1/5.0/5.9 % versus 1.9/5.8/8.0 % official. F is the default.

## Double
PumpDoublify of the generated Single + the playability gate; if it fails, the same rhythm is composed on 10 panels.

## Lessons
- Aggregate statistics cannot see a backwards stance: always judge with `playability.gate` + `MODEL.estimate`.
- Delete failed run directories before retrying (the generators return an existing `song.json`).
- Generated charts have no full human review; playability is not certified.
