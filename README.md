# Generador de charts PIU a partir de otros charts (autónomo)

Toma **un** chart fuente y genera **4 niveles de Single y 4 de Double** (T0 más fácil … T3 = ritmo original completo), en `.NX` (formato PRIME) y en un `song.ssc` de StepMania 5.

Es el algoritmo final del proyecto: **v364 "faithful" + variante F** (patrones validados por el usuario, giros T1-T5, generador ArrowVortex, paridad estricta de pies, gate anti-giro, PumpDoublify para los Double, nivel = estimación del modelo nativo).

## Uso

Requisitos: Python 3.11+ y `numpy`. Nada más; no usa rutas externas ni el resto del proyecto.

```powershell
python piugen.py "C:\Charts\cancion.sm"  --out "C:\Charts\salida" --title "Mi cancion" --artist "Yo"
python piugen.py cancion.ssc | cancion.bme | cancion.NX  --out salida
```

Opciones: `--id` (carpeta de salida), `--music` (audio para `#MUSIC`), `--djmax` (fuente de teclado: acordes de stream pasan a nota simple), `--lead-in-ms N` (descarta notas antes de N ms y arranca en el primer beat fuerte), `--variant A..F` (por defecto F), `--no-ssc`.

**Con un SSC de entrada, el `song.ssc` final = su cabecera original + sus charts originales intactos (con sus SPEEDS/SCROLLS) + 8 generados** (4 Single y 4 Double) a partir del chart Single de mayor nivel. Los generados salen como dificultad `Edit` (nombre `S<nivel>_T<k>` / `D<nivel>_T<k>`) para no pisar las casillas de los originales, y cada uno lleva su propio timing. Con `.sm` de entrada solo se conserva la cabecera (sus charts no se copian). `--title/--artist/--music` sobrescriben solo si se pasan; `--no-keep-metadata` da cabecera genérica sin originales. Si la entrada es una carpeta, usa su `.ssc`/`.sm` e ignora salidas previas de piugen.

**Fuente y tope de dificultad.** Se usa el Single de mayor nivel del simfile; solo si no hay ningún Single, el Double de mayor nivel (aunque el Double sea más difícil, gana el Single). Ningún chart generado sale más difícil que ese original: el tier T3 (ritmo original completo) se etiqueta con el nivel del original y los demás quedan proporcionales por debajo; las notas son siempre un subconjunto del original (nunca se añaden). Con BMS/NX, que no traen nivel, el tope es la estimación del modelo para el Single completo. El nivel crudo del modelo queda en cada recibo `.json` (`model_level`, `level_cap`).

Entradas: SM/SSC (dance-/pump-single o -double), BMS/BME de 5 teclas con BPM constante, o NX de PRIME (Single o Double). Un simfile con `SPEEDS`/`SCROLLS` variables se acepta con aviso (los generados salen a velocidad constante); un BMS con cambios de BPM o stops se rechaza.

Salida en `SALIDA/<id>/`: `Single_T0..T3.NX`, `Double_T0..T3.NX`, un `.json` por chart (recibo, gate, notas omitidas/convertidas) y `song.ssc`. El audio no se genera ni se copia.

## Cómo funciona (resumen)

1. Fuente → NX interno conservando el reloj exacto (`lib/nx_adapter.py`, `lib/hybrid/bms_adapter.py`).
2. Se conserva el ritmo original: **no se añaden ni mueven notas**. Los niveles bajos son subconjuntos del original por fuerza métrica (`faithful.reductions`).
3. `hybrid/composer.py` asigna paneles por beam search con paridad estricta de pies; `hybrid/musical.py` aplica los patrones de usuario, giros y motivos oficiales; `hybrid/vortex.py` es el port del generador de ArrowVortex.
4. `playability.py` (Viterbi del pie natural) rechaza posturas hacia atrás; los puntos conflictivos se omiten/convierten con registro y se recompone.
5. Double = PumpDoublify del Single (`pumpdoublify_adapter.py`, `lib/pumpdoublify/`) + gate; si falla, se compone el mismo ritmo en 10 paneles.
6. El nivel de cada chart es la estimación del modelo de dificultad nativo (`engine/difficulty_model.py` + `data/official_chart_metrics.json`, 21 vecinos oficiales).

## Estructura

```
piugen.py            CLI
lib/faithful.py      orquestador por canción (reducciones, Single, Double, recibos)
lib/hybrid/          composer, musical, vortex, sources, validation, bms_adapter, JSON de patrones/motivos
lib/engine/          modelo de dificultad, nx20, quality_charting, travel
lib/playability.py   gate anti-giro        lib/pumpdoublify*   Single -> Double
lib/nx_ssc.py        NX -> .ssc            lib/simfile.py      lector SM/SSC
lib/user_patterns/   herramientas para transcribir/validar patrones nuevos (opcional)
data/                official_chart_metrics.json
```

## Pruebas rápidas

```powershell
python lib\faithful.py --selftest
python lib\playability.py
```

## Notas

- Los charts generados son **sin revisión humana**: no se certifica jugabilidad.
- `lib/user_patterns/*.py` son herramientas de desarrollo del proyecto original (algunas esperan datos que no se incluyen); el generador no las usa.
- Para añadir un patrón nuevo, editar `lib/hybrid/user_patterns_single.json` (ver `lib/user_patterns/analyze.py`, `check_patterns.py`).
- El volcado crudo anterior (`PIU_ALGORITMO_COMPLETO`) sigue ahí como referencia histórica; esta carpeta es la versión usable.

## Documentación
- `docs/DESARROLLO.md`: investigación y evolución v362 → variante F.
- `docs/research/`: scripts y propuestas del estudio de charts oficiales.
- Algunas herramientas de `lib/user_patterns/` y `lib/engine/ez2_convert.py` tienen rutas de unidad fijas del autor; ajústalas para usarlas.
- Proyecto hermano: el mod PIU omnimix (repo `piu-omnimix`).
