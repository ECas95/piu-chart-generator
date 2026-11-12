# PIU chart generator — step charts from other charts (standalone)

Takes **one** source chart and generates **4 Single and 4 Double levels** (T0 easiest … T3 = full original rhythm) as `.NX` (PRIME format) and as a StepMania 5 `song.ssc`.

This is the project's final algorithm: **v364 "faithful" + variant F** (hand-validated patterns, T1–T5 twists, ArrowVortex stream generator, strict foot parity, anti-spin gate, PumpDoublify for Doubles, level = estimate of a native difficulty model).

## Usage

Requirements: Python 3.11+ and `numpy`. Nothing else; it uses no external paths and none of the rest of the project.

```powershell
python piugen.py "C:\Charts\song.sm"  --out "C:\Charts\out" --title "My song" --artist "Me"
python piugen.py song.ssc | song.bme | song.NX  --out out
```

Options: `--id` (output folder), `--music` (audio for `#MUSIC`), `--djmax` (keyboard source: stream chords collapse to single notes), `--lead-in-ms N` (drop notes before N ms and start on the first strong beat), `--variant A..F` (default F), `--no-ssc`.

**With an SSC input, the final `song.ssc` = its original header + its original charts untouched (with their SPEEDS/SCROLLS) + 8 generated charts** (4 Single and 4 Double) built from the highest-level Single chart. Generated charts are written as `Edit` difficulty (named `S<level>_T<k>` / `D<level>_T<k>`) so they never overwrite the original slots, and each carries its own timing. With a `.sm` input only the header is kept (its charts are not copied). `--title/--artist/--music` override only when given; `--no-keep-metadata` writes a generic header without the originals. If the input is a folder, its `.ssc`/`.sm` is used and previous piugen outputs are ignored.

**Source and difficulty ceiling.** The simfile's highest-level Single is used; only if there is no Single is the highest-level Double used (even if the Double is harder, the Single wins). No generated chart is harder than that original: tier T3 (full original rhythm) is labelled with the original's level and the others are proportionally lower; notes are always a subset of the original (never added). With BMS/NX, which carry no level, the ceiling is the model's estimate for the full Single. The raw model level is stored in every receipt `.json` (`model_level`, `level_cap`).

Inputs: SM/SSC (dance-/pump-single or -double), 5-key BMS/BME with constant BPM, or PRIME NX (Single or Double). A simfile with variable `SPEEDS`/`SCROLLS` is accepted with a warning (generated charts use constant speed); a BMS with BPM changes or stops is rejected.

Output in `OUT/<id>/`: `Single_T0..T3.NX`, `Double_T0..T3.NX`, one `.json` receipt per chart (gate result, omitted/converted notes) and `song.ssc`. Audio is neither generated nor copied.

## How it works (summary)

1. Source → internal NX keeping the exact clock (`lib/nx_adapter.py`, `lib/hybrid/bms_adapter.py`).
2. The original rhythm is preserved: **notes are never added or moved**. Lower levels are subsets of the original by metric strength (`faithful.reductions`).
3. `hybrid/composer.py` assigns panels with a beam search under strict foot parity; `hybrid/musical.py` applies the validated patterns, twists and official motifs; `hybrid/vortex.py` is a port of the ArrowVortex generator.
4. `playability.py` (natural-foot Viterbi) rejects backwards stances; conflicting spots are omitted/converted with a log and the chart is recomposed.
5. Double = PumpDoublify of the Single (`pumpdoublify_adapter.py`, `lib/pumpdoublify/`) + gate; if it fails, the same rhythm is composed on 10 panels.
6. Each chart's level is the native difficulty model's estimate (`engine/difficulty_model.py` + `data/official_chart_metrics.json`, 21 official neighbours).

## Layout

```
piugen.py            CLI
lib/faithful.py      per-song orchestrator (reductions, Single, Double, receipts)
lib/hybrid/          composer, musical, vortex, sources, validation, bms_adapter, pattern/motif JSON
lib/engine/          difficulty model, nx20, quality_charting, travel
lib/playability.py   anti-spin gate        lib/pumpdoublify*   Single -> Double
lib/nx_ssc.py        NX -> .ssc            lib/simfile.py      SM/SSC reader
lib/user_patterns/   tools to transcribe/validate new patterns (optional)
data/                official_chart_metrics.json
docs/                development history and research
```

## Quick checks

```powershell
python lib\faithful.py --selftest
python lib\playability.py
```

## Notes

- Generated charts have **no full human review**: playability is not certified.
- `lib/user_patterns/*.py` are development tools from the original project (some expect data that is not included); the generator does not use them.
- To add a pattern, edit `lib/hybrid/user_patterns_single.json` (see `lib/user_patterns/analyze.py`, `check_patterns.py`).
- Some development tools in `lib/user_patterns/` and `lib/engine/ez2_convert.py` contain hard-coded drive paths from the author's machine; adjust them before use.
- Sister project: the PIU omnimix mod ([piu-omnimix](https://github.com/ECas95/piu-omnimix)).

## Documentation
- `docs/DEVELOPMENT.md`: research and evolution, v362 → variant F.
- `docs/research/`: scripts and proposals from the official-chart study.

## License
MIT.
