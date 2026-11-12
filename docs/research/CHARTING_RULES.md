# Experimental generation rules (EZ2Dancer / RIO)

These rules apply only to slots that were previously auto-generated. Original charts must never be write targets. Installed levels, names, modes and ordinals must be preserved, with before/after hashes of the originals.

## Musicality and progression

- Build a reference grid from the attacks and durations of each song's original charts. Do not use earlier AUTO charts as a rhythm source. For Single prefer Single originals; for Double, Double originals. If a mode is missing, transfer the rhythm and rebuild the geometry. Exclude co-op/routine.
- Use the exact timestamps and split headers of the existing NX. Do not round milliseconds or pull a note earlier by snapping backwards. A created note must occupy a row of the original grid and have a reference attack; a hold must keep the attack and end of a reference.
- Choose attacks per phrase of 8 or 16 beats, prioritising the originals' recurring accents and phrase starts. Load must rise and fall with the source and its rests must be kept. Avoid removing notes by proximity globally: it breaks motifs, off-beats and resolutions.
- Calibrate rows/second, notes/second, 1/4/8-second bursts, jumps and holds against official charts of the same mode/level. Metrics are controls, not a sufficient formula for difficulty. Also compare with the song's closest original.
- When several AUTO charts of one mode exist, their sustained loads should grow with level; easy versions should keep a coherent subset of the hard ones' attacks. Do not raise a level merely to obtain different numbers.

## Geometry and feet

- Keep a state for both feet and the held panels; beam-search the whole sequence per phrase. Costs: each foot's travel, abrupt posture changes, fast same-foot repetition, crossovers, loss of alternation and consecutive turns. Restart softly after rests.
- Resolve jumps as simultaneous contacts of both feet; never assign a whole jump to one foot. Avoid triples and brackets in this first experimental version: enable them only if an explicit model of possible contacts is implemented and validated.
- A hold blocks the foot that holds it until its end. Never write a tap/head over BODY/TAIL, nor let the same foot step on a remote panel while still holding. Reject the collision and look for another geometry; never fix it by overwriting cells.
- In easy charts, penalise fast jacks, crossovers and turns heavily. In intermediates, allow short corpus-backed crossover motifs. In hard charts, do not introduce these only to inflate difficulty: they must follow the rhythm and have preparation and recovery.
- In Double model the two pads as one continuous surface, including the four inner panels. Transitions between pads need feasible per-foot travel, not just left/right alternation. Do not generate jumps between the outer corners of the two pads or large displacements during a hold. Build traversals from compatible official motifs.

## Motifs and variety

- Reference motifs store mode, level band, beat intervals, lanes and hold context. A clean 4-tap sequence does not by itself guarantee a comfortable link with the previous one: revalidate entry and exit against the foot state.
- Prefer frequent corpus motifs and allowed transforms: Single mirror (0↔4, 1↔3, 2 fixed), Double mirror (0↔9, 1↔8, 2↔7, 3↔6, 4↔5). Do not shift indices arbitrarily in Double, because it changes the physical distance.
- Reusing a motif in repeated musical phrases gives identity, but avoid repeating the same 4-panel sequence indefinitely. Change motif or mirror at source variations; use stable, distinct seeds per song/slot/version.

## Post-write validation

1. Structurally valid NX20; slot mode/columns and level preserved.
2. Timing headers identical to the reference, attacks on the same rows, no note beyond the duration, no note lost to a collision.
3. Complete HEAD→BODY→TAIL holds, no orphan bodies, no per-lane overlaps, no attacks inserted inside the same hold.
4. At most two simultaneous contacts, counting active holds. A viable foot model throughout the phrase.
5. Loads, jacks, jumps, panel distribution and Double travel within the limits chosen per level, measured again on the written NX bytes.
6. No original modified. Catalogue snapshot, old AUTO files and a SHA-256 manifest for exact rollback.

The local corpus and automatic checks give a more consistent version; musical quality and the feel of turns still need in-play feedback.

## Problems found in `fill_modes.py`

The earlier generator depends on `C:\EZ2AC\PIU\universal_piu_converter_v0_4`, which no longer exists. It selects the chart with the most notes without distinguishing mode or co-op; a global density of 1.0/0.72/0.50 decides the ladder. It validates before thinning the chart, then modifies jumps and removes attacks without repeating that validation. The stored boolean `ok` no longer describes the final result. `write_on_grid` snaps backwards and can overwrite cells when crossing a hold. The canonical form declares only the initial BPM. The EZ2 score uses a negative coefficient for jumps and bursts, so those loads can artificially lower the level. The current models ignore crossovers, feet, Double travel, hold duration and per-phrase rhythm.
